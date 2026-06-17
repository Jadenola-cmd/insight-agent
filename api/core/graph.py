from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from api.core.state import AnalysisState
from api.nodes.node1_diagnosis import run_diagnosis
from api.nodes.node2_confirmation import run_node2_confirmation
from api.nodes.node3_preview import describe_plan, generate_transform_plan
from api.nodes.node3_transform import run_transform
from api.nodes.node4_analysis import run_analysis
from api.nodes.node5_report import run_report
from api.nodes.node6_followup import run_followup


def node0_clarification(state: AnalysisState) -> dict:
    """纯透传节点：analysis_goal 由 v03.py 澄清路由写入 session_state.json，
    再经 _initial_state() 读入 graph state，此节点不做任何处理。"""
    return {"current_node": "node0_clarification"}


def node1_diagnosis(state: AnalysisState) -> dict:
    report = run_diagnosis(state["raw_data_path"])
    return {
        "current_node": "node1_diagnosis",
        "analysis_results": {"diagnosis": report},
    }


def node2_confirmation(state: AnalysisState) -> dict:
    """Human-in-the-loop 双阶段：
    Phase 1: 字段口径确认（interrupt 推送 diagnosis）
    Phase 2: join 方案确认（interrupt 推送 join_plan）
    """
    return run_node2_confirmation(state)


def node3_preview(state: AnalysisState) -> dict:
    """生成清洗 plan 并 interrupt 等待用户确认；approved 值写入 transform_approved。"""
    plan, llm_available = generate_transform_plan(state["user_confirmations"])
    described = describe_plan(plan)
    approved = interrupt({"transform_plan": described})
    return {
        "current_node": "node3_preview",
        "transform_plan": described,
        "transform_approved": approved,
    }


def _route_after_preview(state: AnalysisState) -> str:
    if state.get("transform_approved"):
        return "node3_transform"
    return END


def node3_transform(state: AnalysisState) -> dict:
    result = run_transform(
        state["raw_data_path"],
        state["user_confirmations"],
        state["cleaned_data_path"],
        state.get("confirmed_join_plan"),
        state.get("merged_data_path"),
    )
    return {
        "current_node": "node3_transform",
        "analysis_results": {**state["analysis_results"], "transform": result},
    }


def node4_analysis(state: AnalysisState) -> dict:
    data_path = state.get("merged_data_path") or state["cleaned_data_path"]
    result = run_analysis(data_path)
    return {
        "current_node": "node4_analysis",
        "analysis_results": {**state["analysis_results"], "analysis": result["results"]},
        "charts_data": result["charts"],
    }


def node5_report(state: AnalysisState) -> dict:
    data_path = state.get("merged_data_path") or state["cleaned_data_path"]
    result = run_report(
        data_path,
        state["analysis_results"],
        state["charts_data"],
        state["report_path"],
    )
    return {
        "current_node": "node5_report",
        "analysis_results": {
            **state["analysis_results"],
            "report": {
                "modules": result["modules"],
                "pdf_generated": result["pdf_generated"],
                "llm_available": result["llm_available"],
            },
        },
        "report_html": result["report_html"],
    }


def node6_followup(state: AnalysisState) -> dict:
    """追问对话：每次调用处理一轮 interrupt，通过 self-loop 边支持多轮。
    每次调用只有一个 interrupt()，节点在收到消息后立即处理并返回（状态随即
    写入 checkpoint），再经条件边回到 node6_followup 等待下一条消息。
    发送 None/空字符串即可退出循环（folloup_done=True → 条件边指向 END）。"""
    message = interrupt({"type": "followup_ready"})
    if not message:
        return {"current_node": "node6_followup", "followup_done": True}

    data_path = state.get("merged_data_path") or state["cleaned_data_path"]
    result = run_followup({
        "followup_message": message,
        "cleaned_data_path": data_path,
        "analysis_results": state["analysis_results"].get("analysis", {}),
        "report_html": state.get("report_html", ""),
        "followup_history": list(state.get("followup_history") or []),
    })
    return {
        "current_node": "node6_followup",
        "followup_history": result["followup_history"],
        "report_html": result["report_html"],
        "followup_done": False,
    }


def _route_after_node6(state: AnalysisState) -> str:
    """followup_done=True 时退出；否则 self-loop 继续等待下一条追问。"""
    if state.get("followup_done"):
        return END
    return "node6_followup"


def _build_graph():
    builder = StateGraph(AnalysisState)

    builder.add_node("node0_clarification", node0_clarification)
    builder.add_node("node1_diagnosis", node1_diagnosis)
    builder.add_node("node2_confirmation", node2_confirmation)
    builder.add_node("node3_preview", node3_preview)
    builder.add_node("node3_transform", node3_transform)
    builder.add_node("node4_analysis", node4_analysis)
    builder.add_node("node5_report", node5_report)
    builder.add_node("node6_followup", node6_followup)

    builder.set_entry_point("node0_clarification")
    builder.add_edge("node0_clarification", "node1_diagnosis")
    builder.add_edge("node1_diagnosis", "node2_confirmation")
    builder.add_edge("node2_confirmation", "node3_preview")
    builder.add_conditional_edges("node3_preview", _route_after_preview)
    builder.add_edge("node3_transform", "node4_analysis")
    builder.add_edge("node4_analysis", "node5_report")
    builder.add_edge("node5_report", "node6_followup")
    # node6 self-loop：每次处理一条消息后返回，由条件边决定继续或退出
    builder.add_conditional_edges("node6_followup", _route_after_node6)

    return builder.compile(checkpointer=MemorySaver())


# 单例：MemorySaver 按 thread_id（= session_id）隔离各会话的 checkpoint。
# 注意：进程重启会丢失所有未完成的会话状态，见 DEBT.md。
graph = _build_graph()


def graph_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
