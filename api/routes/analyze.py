import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from langgraph.types import Command

from api.core.graph import graph, graph_config
from api.core.paths import cleaned_data_path, merged_data_path, raw_data_path, report_pdf_path
from api.core.schema import ConfirmedSchemaRequest, JoinPlanRequest
from api.core.session_state import load_session_state

router = APIRouter()


def _sse(node: str, status: str, data: dict) -> str:
    event = {"node": node, "status": status, "data": data}
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _initial_state(session_id: str) -> dict:
    session = load_session_state(session_id)
    return {
        "current_node": "",
        "analysis_type": "",
        "user_confirmations": {},
        "raw_data_path": str(raw_data_path(session_id)),
        "cleaned_data_path": str(cleaned_data_path(session_id)),
        "merged_data_path": str(merged_data_path(session_id)),
        "report_path": str(report_pdf_path(session_id)),
        "analysis_results": {},
        "charts_data": {},
        "report_html": "",
        # v0.3：从 session_state.json 读取澄清结果，node0 据此决定是否透传
        "analysis_goal": session.get("analysis_goal", ""),
        "transform_plan": [],
        "transform_approved": False,
        "followup_history": [],
        "followup_done": False,
        # Join 方案确认
        "proposed_join_plan": None,
        "confirmed_join_plan": None,
        # session_id 供 node2_confirmation 定位表文件
        "session_id": session_id,
    }


@router.get("/api/analyze/{session_id}/stream")
async def analyze_stream(session_id: str) -> StreamingResponse:
    """启动 LangGraph 流程：Node1 数据诊断 -> Node2 中断等待口径确认。
    流程在 Node2 的 `interrupt()` 处暂停，本次 SSE 流会在推送
    `waiting_confirmation` 事件后结束；用户提交确认后通过
    `POST /api/analyze/{session_id}/confirm` 恢复流程。"""

    def event_generator():
        path = raw_data_path(session_id)
        if not path.exists():
            yield _sse("diagnosis", "error", {"message": "未找到上传文件，请重新上传"})
            return

        # 若 checkpoint 已存在且图处于活跃状态，说明流程已启动，禁止重复 stream
        # 避免 LangGraph 把 _initial_state() 误当作上一个 interrupt 的 resume 值
        config = graph_config(session_id)
        existing = graph.get_state(config)
        if existing.values and existing.tasks:
            yield _sse("diagnosis", "error", {
                "message": "分析已启动，请勿重复调用 /stream；若需重新开始请重新上传文件"
            })
            return

        yield _sse("diagnosis", "running", {})

        config = graph_config(session_id)
        try:
            for chunk in graph.stream(_initial_state(session_id), config, stream_mode="updates"):
                if "node1_diagnosis" in chunk:
                    diagnosis = chunk["node1_diagnosis"]["analysis_results"]["diagnosis"]
                    yield _sse("diagnosis", "done", diagnosis)
                elif "__interrupt__" in chunk:
                    payload = chunk["__interrupt__"][0].value
                    if "diagnosis" in payload:
                        # node2_confirmation Phase 1 interrupt
                        yield _sse("confirmation", "waiting_confirmation", payload["diagnosis"])
                    elif "history" in payload:
                        # node0_clarification interrupt（analysis_goal 未预设时）
                        yield _sse("clarification", "waiting", payload)
                    else:
                        yield _sse("node", "interrupt", payload)
        except Exception as exc:
            yield _sse("diagnosis", "error", {"message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/api/analyze/{session_id}/confirm")
async def analyze_confirm(session_id: str, confirmed_schema: ConfirmedSchemaRequest) -> StreamingResponse:
    """提交 Node2 Phase 1 的口径确认结果，恢复被中断的流程。
    流程会继续到 Node2 Phase 2（join 方案确认），推送 join_plan 后再次中断。"""

    def event_generator():
        config = graph_config(session_id)

        state_snapshot = graph.get_state(config)
        if not state_snapshot.tasks or not any(
            t.interrupts for t in state_snapshot.tasks
        ):
            yield _sse("confirmation", "error", {"message": "当前会话不在等待确认状态"})
            return

        try:
            for chunk in graph.stream(
                Command(resume=confirmed_schema.model_dump()), config, stream_mode="updates"
            ):
                if "node2_confirmation" in chunk:
                    yield _sse(
                        "confirmation",
                        "confirmed",
                        chunk["node2_confirmation"]["user_confirmations"],
                    )
                elif "__interrupt__" in chunk:
                    payload = chunk["__interrupt__"][0].value
                    if "join_plan" in payload:
                        # node2_confirmation Phase 2: join 方案确认
                        yield _sse("join_plan", "waiting_confirmation", {
                            "join_plan": payload["join_plan"],
                            "table_columns": payload.get("table_columns", {}),
                        })
                    elif "transform_plan" in payload:
                        # node3_preview interrupt：推送清洗计划，SSE 在此结束
                        yield _sse("transform", "waiting_preview", {
                            "transform_plan": payload["transform_plan"]
                        })
                    else:
                        yield _sse("node", "interrupt", payload)
        except Exception as exc:
            yield _sse("confirmation", "error", {"message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/api/analyze/{session_id}/confirm/join")
async def analyze_confirm_join(session_id: str, join_plan: JoinPlanRequest) -> StreamingResponse:
    """提交 Node2 Phase 2 的 join 方案确认结果，恢复流程继续到 Node3 清洗预览。"""

    def event_generator():
        config = graph_config(session_id)

        state_snapshot = graph.get_state(config)
        if not state_snapshot.tasks or not any(
            t.interrupts for t in state_snapshot.tasks
        ):
            yield _sse("join_plan", "error", {"message": "当前会话不在等待 join 确认状态"})
            return

        try:
            for chunk in graph.stream(
                Command(resume=join_plan.model_dump()), config, stream_mode="updates"
            ):
                if "node2_confirmation" in chunk:
                    confirmed = chunk["node2_confirmation"]
                    yield _sse("join_plan", "confirmed", {
                        "confirmed_join_plan": confirmed.get("confirmed_join_plan"),
                    })
                elif "__interrupt__" in chunk:
                    payload = chunk["__interrupt__"][0].value
                    if "transform_plan" in payload:
                        yield _sse("transform", "waiting_preview", {
                            "transform_plan": payload["transform_plan"]
                        })
                    else:
                        yield _sse("node", "interrupt", payload)
        except Exception as exc:
            yield _sse("join_plan", "error", {"message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/api/report/{session_id}/pdf")
async def report_pdf(session_id: str) -> FileResponse:
    """下载 Node5 生成的 PDF 报告。"""
    path = report_pdf_path(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告尚未生成")
    return FileResponse(path, media_type="application/pdf", filename="report.pdf")


@router.get("/api/report/{session_id}/html")
async def report_html(session_id: str) -> HTMLResponse:
    """返回 Node5 生成的 report_html（state 中的字符串，未落盘）。"""
    config = graph_config(session_id)
    state_snapshot = graph.get_state(config)
    html = state_snapshot.values.get("report_html")
    if not html:
        raise HTTPException(status_code=404, detail="报告尚未生成")
    return HTMLResponse(content=html)
