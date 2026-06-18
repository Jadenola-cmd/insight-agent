import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

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
        # Minerva（PRD v1.0）：未上传数据时 node0_clarification 走对话式问题定义，
        # 旧版（raw.csv 已存在）这些字段始终保持空值，不影响线性流程
        "stage": "",
        "problem_card": None,
        "hypothesis_tree": [],
        "clarification_history": [],
        "clarification_round": 0,
        "verifying_node_id": None,
        "verifying_module": None,
        "last_verification": None,
    }


@router.get("/api/analyze/{session_id}/stream")
async def analyze_stream(session_id: str) -> StreamingResponse:
    """启动 LangGraph 流程，两种入口（见 node0_clarification 的判断逻辑）：
    - 旧版：raw.csv 已上传，Node1 数据诊断 -> Node2 中断等待口径确认；
      `waiting_confirmation` 事件后本次 SSE 结束，用户确认后调用
      `POST /api/analyze/{session_id}/confirm` 恢复。
    - Minerva：raw.csv 尚不存在，进入阶段一问题定义对话（推送 `clarification/
      waiting`），用 `POST /api/analyze/{session_id}/resume` 推进。"""

    def event_generator():
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
                    # 多表场景下 node2_confirmation 函数体含两个 interrupt()，只有两阶段都
                    # 恢复后该节点才算真正完成；此前 Phase1 的 /confirm 接口里节点还卡在
                    # Phase2 interrupt 上，从未返回，导致前端时间线的"口径确认"永远停在
                    # waiting_confirmation。这里补发 confirmation/confirmed，与单表场景
                    # （/confirm 内直接完成）保持一致。
                    yield _sse("confirmation", "confirmed", confirmed.get("user_confirmations"))
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


class ResumeRequest(BaseModel):
    value: object = None


@router.post("/api/analyze/{session_id}/resume")
async def analyze_resume(session_id: str, body: ResumeRequest) -> dict:
    """通用 interrupt 恢复入口，服务 Minerva 新增节点（node0_clarification 自循环/
    node_awaiting_data/node_hypothesis_tree）：value 直接作为 resume 值传给对应
    节点的 interrupt() 调用方。node2/node3_preview/node6 仍用各自专属确认接口
    （历史原因，未迁移），不受本接口影响。"""
    config = graph_config(session_id)
    state_snapshot = graph.get_state(config)
    if not state_snapshot.tasks or not any(t.interrupts for t in state_snapshot.tasks):
        raise HTTPException(status_code=409, detail="当前会话不在等待恢复状态")

    for _ in graph.stream(Command(resume=body.value), config, stream_mode="updates"):
        pass

    updated = graph.get_state(config)
    for task in updated.tasks:
        if task.interrupts:
            return {"status": "waiting", "interrupt": task.interrupts[0].value}
    return {"status": "done", "stage": updated.values.get("stage")}


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
