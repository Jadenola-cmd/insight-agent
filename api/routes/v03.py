"""v0.3 新增接口：Node0问题澄清 / Node3清洗计划预览确认 / Node6追问对话。

均为设计阶段实现，路由直接调用对应 node 函数，不经过 api/core/graph.py 的
LangGraph 图（不修改 graph.py）。Node1-5 主流程涉及的
confirmed_schema/cleaned_data_path/analysis_results/report_html 通过
graph.get_state() 只读获取；clarification_history/analysis_goal/
transform_plan/followup_history 等新增字段持久化在
api/data/<session_id>/session_state.json（api/core/session_state.py）。
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from api.core.graph import graph, graph_config
from api.core.paths import cleaned_data_path, raw_data_path
from api.core.session_state import load_session_state, save_session_state
from api.nodes.node0_clarification import run_clarification
from api.nodes.node3_preview import run_preview
from api.nodes.node3_transform import run_transform
from api.nodes.node6_followup import run_followup

router = APIRouter()


def _sse(node: str, status: str, data: dict) -> str:
    event = {"node": node, "status": status, "data": data}
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# ---- Node0 问题澄清 ----

class ClarifyMessageRequest(BaseModel):
    message: str


@router.post("/api/clarify/{session_id}/message")
async def clarify_message(session_id: str, body: ClarifyMessageRequest) -> dict:
    """推进一轮问题澄清对话；done=true 时返回的 analysis_goal 即最终结果。"""
    session = load_session_state(session_id)
    result = run_clarification({
        "user_message": body.message,
        "clarification_history": session.get("clarification_history", []),
        "round": session.get("round", 0),
        "raw_data_paths": session.get("raw_data_paths", []),
    })
    session["clarification_history"] = result["clarification_history"]
    session["round"] = result["round"]
    session["analysis_goal"] = result["analysis_goal"]
    save_session_state(session_id, session)
    return result


@router.get("/api/clarify/{session_id}/stream")
async def clarify_stream(session_id: str) -> StreamingResponse:
    """SSE推送澄清对话过程（设计阶段：回放已记录的 clarification_history）。

    完整实现时应改为接收用户消息后实时推送LLM回复；当前用于验证
    session_state 中的 clarification_history/analysis_goal 是否正确写入。
    """
    def event_generator():
        session = load_session_state(session_id)
        history = session.get("clarification_history", [])
        reply = history[-1].get("content", "") if history else ""
        analysis_goal = session.get("analysis_goal", "")
        # 有 analysis_goal 说明 LLM 已确认目标，通知前端完成；否则只推送本轮回复
        status = "done" if analysis_goal else "reply"
        yield _sse("clarification", status, {
            "reply": reply,
            "clarification_history": history,
            "analysis_goal": analysis_goal,
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---- Node3 清洗计划预览确认 ----

class TransformConfirmRequest(BaseModel):
    approved: bool
    plan: list[dict] | None = None
    action: str | None = None  # "regenerate" 时忽略 approved，强制重新生成 plan 后再次中断


@router.get("/api/analyze/{session_id}/transform/preview")
async def transform_preview(session_id: str) -> dict:
    """生成并返回清洗 plan 预览（不执行）。confirmed_schema 取自 Node2 的 graph state。"""
    config = graph_config(session_id)
    state_snapshot = graph.get_state(config)
    confirmed_schema = state_snapshot.values.get("user_confirmations")
    if not confirmed_schema:
        raise HTTPException(status_code=404, detail="未找到 confirmed_schema，请先完成 Node2 口径确认")

    result = run_preview({"user_confirmations": confirmed_schema})
    session = load_session_state(session_id)
    session["transform_plan"] = result["transform_plan"]
    save_session_state(session_id, session)
    return result


@router.post("/api/analyze/{session_id}/transform/confirm")
async def transform_confirm(session_id: str, body: TransformConfirmRequest) -> StreamingResponse:
    """恢复 node3_preview interrupt。

    approved=true：携带（可能被前端编辑过的）plan，继续执行
      node3→node4→node5→node6_followup，SSE: transform/done → analysis/done →
      report/done → followup/ready。
    approved=false：回退到 node2_confirmation 重新做口径确认（不再终止会话），
      SSE 推送 confirmation/waiting_confirmation，前端据此重新展示口径确认表单。
    """
    def event_generator():
        config = graph_config(session_id)
        state_snapshot = graph.get_state(config)

        if not state_snapshot.tasks or not any(t.interrupts for t in state_snapshot.tasks):
            yield _sse("transform", "error", {"message": "当前会话不在等待清洗确认状态"})
            return

        if body.action == "regenerate":
            resume_value = {"action": "regenerate"}
        else:
            resume_value = {"action": "confirm", "plan": body.plan} if body.approved else {"action": "reject"}

        try:
            for chunk in graph.stream(Command(resume=resume_value), config, stream_mode="updates"):
                if "node3_transform" in chunk:
                    yield _sse("transform", "done",
                               chunk["node3_transform"]["analysis_results"]["transform"])
                elif "node4_analysis" in chunk:
                    yield _sse("analysis", "done", {
                        "results": chunk["node4_analysis"]["analysis_results"]["analysis"],
                        "charts": chunk["node4_analysis"]["charts_data"],
                    })
                elif "node5_report" in chunk:
                    report = chunk["node5_report"]["analysis_results"]["report"]
                    yield _sse("report", "done", {
                        "modules": report["modules"],
                        "pdf_generated": report["pdf_generated"],
                        "pdf_url": f"/api/report/{session_id}/pdf",
                    })
                elif "__interrupt__" in chunk:
                    payload = chunk["__interrupt__"][0].value
                    if "transform_plan" in payload:
                        # regenerate 后 node3_preview self-loop 再次中断，推送新版 plan
                        yield _sse("transform", "waiting_preview", {
                            "transform_plan": payload["transform_plan"],
                            "data_preview": payload.get("data_preview"),
                        })
                    elif "diagnosis" in payload:
                        # 拒绝清洗计划，回退到 node2_confirmation 重新做口径确认
                        yield _sse("confirmation", "waiting_confirmation", payload["diagnosis"])
                    else:
                        # node6_followup interrupt：报告已生成，等待追问
                        yield _sse("followup", "ready", {})
                    break
        except Exception as exc:
            yield _sse("transform", "error", {"message": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---- Node6 追问对话 ----

class FollowupRequest(BaseModel):
    message: str


@router.post("/api/analyze/{session_id}/followup")
async def followup(session_id: str, body: FollowupRequest) -> dict:
    """恢复 node6_followup interrupt（或回退到直接调用），执行一轮追问并更新报告。"""
    config = graph_config(session_id)
    state_snapshot = graph.get_state(config)
    values = state_snapshot.values

    # 图当前处于 node6 interrupt：用 Command(resume=message) 恢复
    if state_snapshot.tasks and any(t.interrupts for t in state_snapshot.tasks):
        for _ in graph.stream(Command(resume=body.message), config, stream_mode="updates"):
            pass  # 同步执行至下一个 interrupt
        updated = graph.get_state(config)
        history = updated.values.get("followup_history", [])
        report_html = updated.values.get("report_html", "")
        # 同步写 session_state.json，供 /followup/stream 读取
        session = load_session_state(session_id)
        session["followup_history"] = history
        session["report_html"] = report_html
        save_session_state(session_id, session)
        latest = history[-1] if history else {}
        return {**latest, "followup_history": history}

    # 回退：图已结束或不在 node6，直接调用（兼容旧 session）
    if not values.get("cleaned_data_path") or not values.get("analysis_results", {}).get("analysis"):
        raise HTTPException(status_code=404, detail="未找到分析结果，请先完成Node1-5主流程")

    session = load_session_state(session_id)
    result = run_followup({
        "followup_message": body.message,
        "cleaned_data_path": values["cleaned_data_path"],
        "analysis_results": values["analysis_results"]["analysis"],
        "report_html": session.get("report_html", values.get("report_html", "")),
        "followup_history": session.get("followup_history", []),
    })
    session["followup_history"] = result["followup_history"]
    session["report_html"] = result["report_html"]
    save_session_state(session_id, session)
    return result


@router.get("/api/analyze/{session_id}/followup/stream")
async def followup_stream(session_id: str) -> StreamingResponse:
    """SSE推送追问历史（设计阶段：回放已记录的 followup_history）。"""
    def event_generator():
        session = load_session_state(session_id)
        yield _sse("node6_followup", "done", {"followup_history": session.get("followup_history", [])})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
