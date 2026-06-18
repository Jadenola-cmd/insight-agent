from pathlib import Path

import pandas as pd
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from api.core.state import AnalysisState
from api.modules.registry import default_registry
from api.modules.visualization import VisualizationModule
from api.nodes.hypothesis_tree import (
    apply_ops,
    generate_chat_ops,
    generate_conclusion_narrative,
    generate_initial_ops,
)
from api.nodes.node0_clarification import run_clarification
from api.nodes.node1_diagnosis import run_diagnosis
from api.nodes.node2_confirmation import run_node2_confirmation
from api.nodes.node3_preview import describe_plan, generate_transform_plan
from api.nodes.node3_transform import run_transform
from api.nodes.node4_analysis import run_analysis
from api.nodes.node5_report import _compute_confidence, _generate_narrative, run_report
from api.nodes.node6_followup import run_followup


def node0_clarification(state: AnalysisState) -> dict:
    """两种入口模式，靠 raw_data_path 对应文件是否已存在区分：

    - 旧版（v0.3 线性流程）：upload 已先写入 raw.csv，此处纯透传直接进入
      node1_diagnosis，不打断，兼容现有 /routes/analyze.py + v03.py 澄清侧链路。
    - Minerva（PRD v1.0 阶段一问题定义）：数据尚未上传，节点自循环 interrupt
      等待用户消息，调用 run_clarification 推进对话，收敛后产出 problem_card，
      stage 切到 awaiting_data 等待 node_awaiting_data 接管。
    """
    if Path(state["raw_data_path"]).exists():
        return {"current_node": "node0_clarification"}

    message = interrupt({
        "type": "problem_definition",
        "history": state.get("clarification_history", []),
    })
    result = run_clarification({
        "user_message": message,
        "clarification_history": state.get("clarification_history", []),
        "round": state.get("clarification_round", 0),
        "raw_data_paths": [],
    })
    update = {
        "current_node": "node0_clarification",
        "clarification_history": result["clarification_history"],
        "clarification_round": result["round"],
        "analysis_goal": result["analysis_goal"],
    }
    if result["done"]:
        update["problem_card"] = {
            "question": result.get("question") or result["analysis_goal"],
            "baseline": result.get("baseline", ""),
            "business_meaning": result.get("business_meaning", ""),
            "analysis_goal": result["analysis_goal"],
        }
        update["stage"] = "awaiting_data"
    else:
        update["stage"] = "problem_definition"
    return update


def _route_after_node0(state: AnalysisState) -> str:
    if state.get("stage") == "awaiting_data":
        return "node_awaiting_data"
    if Path(state["raw_data_path"]).exists():
        return "node1_diagnosis"
    return "node0_clarification"


def node_awaiting_data(state: AnalysisState) -> dict:
    """阶段一结束、阶段二开始前的人工触发点：等待前端调用 POST /api/upload
    （携带本 session_id）把数据写入 raw_data_path 后再 resume 推进。数据本身
    不进 state（CLAUDE.md 约束4），此处只做信号等待。"""
    interrupt({"type": "awaiting_data", "problem_card": state.get("problem_card")})
    return {"current_node": "node_awaiting_data", "stage": "data_setup"}


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
    """生成清洗 plan 并 interrupt 等待用户确认。

    resume 值为 {"action": "confirm"|"reject", "plan": [...]（仅 confirm 时使用）}：
    - confirm：plan 为前端可能编辑过（删除/修改某些步骤）的最终版本，写入
      transform_plan 供 node3_transform 直接执行（不再重新生成）
    - reject：不写 transform_plan，路由回 node2_confirmation 让用户重新确认口径
    """
    plan, llm_available = generate_transform_plan(state["user_confirmations"])
    described = describe_plan(plan)
    decision = interrupt({"transform_plan": described})
    action = decision.get("action", "confirm")
    final_plan = decision.get("plan") if action == "confirm" and decision.get("plan") else described
    return {
        "current_node": "node3_preview",
        "transform_plan": final_plan,
        "transform_approved": action == "confirm",
        "transform_preview_action": action,
    }


def _route_after_preview(state: AnalysisState) -> str:
    if state.get("transform_preview_action") == "reject":
        return "node2_confirmation"
    return "node3_transform"


def node3_transform(state: AnalysisState) -> dict:
    result = run_transform(
        state["raw_data_path"],
        state["user_confirmations"],
        state["cleaned_data_path"],
        state.get("confirmed_join_plan"),
        state.get("merged_data_path"),
        final_plan=state.get("transform_plan"),
    )
    return {
        "current_node": "node3_transform",
        "analysis_results": {**state["analysis_results"], "transform": result},
    }


def _route_after_transform(state: AnalysisState) -> str:
    """problem_card 只在 Minerva 入口（node0_clarification 自循环收敛）写入，
    旧版线性流程该字段始终为 None，据此区分走向。"""
    if state.get("problem_card"):
        return "node_hypothesis_tree"
    return "node4_analysis"


def _data_path(state: AnalysisState) -> str:
    """merged_data_path 在 state 里始终是一个非空路径字符串（_initial_state 预设），
    但只有真正执行过 join 时该文件才会被写入；单表场景必须落回 cleaned_data_path，
    否则会去读一个不存在的文件。"""
    join_plan = state.get("confirmed_join_plan")
    if join_plan and join_plan.get("joins"):
        return state["merged_data_path"]
    return state["cleaned_data_path"]


def node4_analysis(state: AnalysisState) -> dict:
    data_path = _data_path(state)
    result = run_analysis(data_path)
    return {
        "current_node": "node4_analysis",
        "analysis_results": {**state["analysis_results"], "analysis": result["results"]},
        "charts_data": result["charts"],
    }


def node5_report(state: AnalysisState) -> dict:
    data_path = _data_path(state)
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

    data_path = _data_path(state)
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


def node_hypothesis_tree(state: AnalysisState) -> dict:
    """阶段二（假设树）：首次进入时 LLM 一次性生成初始树；之后每次 interrupt
    等待用户下一步动作 {"action": "chat"|"verify"|"conclude", ...}：
    - chat：message 经 LLM 转为增量操作（可能为空，纯聊天不调整树），留在本节点
    - verify：携带 node_id + module（registry 模块名），路由去 node_verification
    - conclude：路由去 node_conclusion 生成综合结论
    """
    tree = state.get("hypothesis_tree") or []
    if not tree:
        tree = apply_ops(tree, generate_initial_ops(state.get("problem_card") or {}))

    decision = interrupt({
        "type": "hypothesis_tree",
        "tree": tree,
        "last_verification": state.get("last_verification"),
        "problem_card": state.get("problem_card"),
    })
    action = decision.get("action", "chat")

    if action == "verify":
        return {
            "current_node": "node_hypothesis_tree",
            "hypothesis_tree": tree,
            "stage": "verification",
            "verifying_node_id": decision.get("node_id"),
            "verifying_module": decision.get("module"),
        }
    if action == "conclude":
        return {"current_node": "node_hypothesis_tree", "hypothesis_tree": tree, "stage": "conclusion"}

    ops = generate_chat_ops(tree, state.get("problem_card") or {}, decision.get("message", ""))
    tree = apply_ops(tree, ops)
    return {"current_node": "node_hypothesis_tree", "hypothesis_tree": tree, "stage": "hypothesis_tree"}


def _route_after_hypothesis(state: AnalysisState) -> str:
    stage = state.get("stage")
    if stage == "verification":
        return "node_verification"
    if stage == "conclusion":
        return "node_conclusion"
    return "node_hypothesis_tree"


def node_verification(state: AnalysisState) -> dict:
    """阶段三（验证执行）：复用 registry.get_module(name) 拿到的分析模块在
    全量清洗后数据上跑一次（与 node4_analysis 同一套模块，未做按假设的数据
    子集过滤，留待后续迭代），用 node5_report 的置信度规则+叙事生成判定
    该假设是 verified（置信度非"低"）还是 partial，结果写回假设树对应节点。"""
    node_id = state.get("verifying_node_id")
    module = default_registry.get_module(state.get("verifying_module") or "")
    tree = state.get("hypothesis_tree") or []
    df = pd.read_parquet(_data_path(state))

    last_verification = None
    if module is None or not module.validate(df):
        summary = "所选验证方式不适用于当前数据，请换一个假设或模块重新验证。"
        ops = [{"op": "update_summary", "node_id": node_id, "summary": summary,
                "node": None, "status": None, "merge_ids": None, "merged_node": None}]
    else:
        metrics = module.run(df, {})
        confidence = _compute_confidence(df, module.name, module.category, metrics)
        narrative, _ = _generate_narrative(module.category, metrics)
        status = "verified" if confidence["level"] != "低" else "partial"
        ops = [
            {"op": "update_status", "node_id": node_id, "status": status,
             "node": None, "summary": None, "merge_ids": None, "merged_node": None},
            {"op": "update_summary", "node_id": node_id, "summary": narrative.get("conclusion", ""),
             "node": None, "status": None, "merge_ids": None, "merged_node": None},
        ]
        last_verification = {
            "node_id": node_id,
            "module": module.name,
            "category": module.category,
            "chart": VisualizationModule().transform(module.get_chart_spec(metrics)),
            "confidence": confidence,
            "narrative": narrative,
        }

    tree = apply_ops(tree, ops)
    return {
        "current_node": "node_verification",
        "hypothesis_tree": tree,
        "stage": "hypothesis_tree",
        "verifying_node_id": None,
        "verifying_module": None,
        "last_verification": last_verification,
    }


def node_conclusion(state: AnalysisState) -> dict:
    """阶段三结束：汇总假设树各节点验证结果生成综合结论（写入 report_html，
    复用既有的 GET /api/report/{session_id}/html 展示路径）。"""
    narrative = generate_conclusion_narrative(state.get("problem_card") or {}, state.get("hypothesis_tree") or [])
    return {"current_node": "node_conclusion", "report_html": narrative, "stage": "conclusion"}


def _build_graph():
    builder = StateGraph(AnalysisState)

    builder.add_node("node0_clarification", node0_clarification)
    builder.add_node("node_awaiting_data", node_awaiting_data)
    builder.add_node("node1_diagnosis", node1_diagnosis)
    builder.add_node("node2_confirmation", node2_confirmation)
    builder.add_node("node3_preview", node3_preview)
    builder.add_node("node3_transform", node3_transform)
    builder.add_node("node4_analysis", node4_analysis)
    builder.add_node("node5_report", node5_report)
    builder.add_node("node6_followup", node6_followup)
    builder.add_node("node_hypothesis_tree", node_hypothesis_tree)
    builder.add_node("node_verification", node_verification)
    builder.add_node("node_conclusion", node_conclusion)

    builder.set_entry_point("node0_clarification")
    # node0 自循环：旧版（数据已上传）直入node1；Minerva版对话未收敛时自循环，
    # 收敛后转 node_awaiting_data 等待上传
    builder.add_conditional_edges("node0_clarification", _route_after_node0)
    builder.add_edge("node_awaiting_data", "node1_diagnosis")
    builder.add_edge("node1_diagnosis", "node2_confirmation")
    builder.add_edge("node2_confirmation", "node3_preview")
    builder.add_conditional_edges("node3_preview", _route_after_preview)
    # node3_transform 之后：旧版直入node4分析报告；Minerva版转假设树验证循环
    builder.add_conditional_edges("node3_transform", _route_after_transform)
    builder.add_edge("node4_analysis", "node5_report")
    builder.add_edge("node5_report", "node6_followup")
    # node6 self-loop：每次处理一条消息后返回，由条件边决定继续或退出
    builder.add_conditional_edges("node6_followup", _route_after_node6)
    # 假设树循环：chat留在原节点，verify/conclude路由出去，verification完成后绕回
    builder.add_conditional_edges("node_hypothesis_tree", _route_after_hypothesis)
    builder.add_edge("node_verification", "node_hypothesis_tree")
    builder.add_edge("node_conclusion", END)

    return builder.compile(checkpointer=MemorySaver())


# 单例：MemorySaver 按 thread_id（= session_id）隔离各会话的 checkpoint。
# 注意：进程重启会丢失所有未完成的会话状态，见 DEBT.md。
graph = _build_graph()


def graph_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
