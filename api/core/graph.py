from pathlib import Path

import pandas as pd
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from jinja2 import Environment, FileSystemLoader, select_autoescape

from api.core.paths import report_html_path
from api.core.state import AnalysisState
from api.modules.registry import default_registry
from api.modules.visualization import VisualizationModule
from api.nodes.hypothesis_tree import (
    apply_ops,
    generate_chat_ops,
    generate_conclusion_narrative,
    generate_dedupe_ops,
    generate_initial_ops,
    suggest_verification_config,
)
from api.nodes.node0_clarification import run_clarification
from api.nodes.node1_diagnosis import run_diagnosis
from api.nodes.node2_confirmation import run_node2_confirmation
from api.nodes.node3_preview import build_data_preview, describe_plan, generate_transform_plan, schema_fingerprint
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


def node3_plan_init(state: AnalysisState) -> dict:
    """生成（或复用缓存）清洗 plan + 真实数据预览，写入 checkpoint，不含 interrupt()。

    必须与 node3_preview（含 interrupt）拆成两个节点：LangGraph 的 interrupt() 恢复
    时会把节点函数从头重新执行一遍（只是恢复点跳过暂停直接拿到 resume 值），如果
    LLM 调用写在 interrupt() 之前，每次恢复都会重新调一次 LLM——"确认执行"时真正
    用的 plan 就可能和用户刚看到的预览不是同一份（与假设树初始化的 resume 重跑坑
    同根因，见 [[project_langgraph_state_gotcha]]）。拆出本节点后它只在图真正路由
    进入时执行一次，不会被下游 interrupt 的恢复连带重跑。

    按 confirmed_schema 内容指纹缓存：口径退回重新提交但内容未变时直接复用缓存，
    不重新调用 LLM（LLM 采样随机性曾导致前后两次结果不一致，见 STATUS.md #3）。
    """
    schema = state["user_confirmations"]
    fingerprint = schema_fingerprint(schema)
    cache_hit = state.get("transform_plan_cache_key") == fingerprint and state.get("transform_plan_cache")
    force_regenerate = state.get("transform_preview_action") == "regenerate"

    if cache_hit and not force_regenerate:
        plan = state["transform_plan_cache"]
    else:
        plan, _ = generate_transform_plan(schema, state["analysis_results"].get("diagnosis"))

    described = describe_plan(plan)
    data_preview = build_data_preview(state["raw_data_path"], plan, state.get("confirmed_join_plan"))
    return {
        "current_node": "node3_plan_init",
        "transform_plan_cache_key": fingerprint,
        "transform_plan_cache": plan,
        "transform_plan_pending": described,
        "transform_data_preview": data_preview,
    }


def node3_preview(state: AnalysisState) -> dict:
    """interrupt 等待用户确认，只读 node3_plan_init 已写入 checkpoint 的 plan/预览。

    resume 值为 {"action": "confirm"|"reject"|"regenerate", "plan": [...]（仅 confirm 时使用）}：
    - confirm：plan 为前端可能编辑过（删除/修改某些步骤）的最终版本，写入
      transform_plan 供 node3_transform 直接执行（不再重新生成）
    - reject：不写 transform_plan，路由回 node2_confirmation 让用户重新确认口径
    - regenerate：路由回 node3_plan_init 强制重新生成新版 plan
    """
    described = state["transform_plan_pending"]
    decision = interrupt({"transform_plan": described, "data_preview": state["transform_data_preview"]})
    action = decision.get("action", "confirm")

    if action == "regenerate":
        return {"current_node": "node3_preview", "transform_preview_action": "regenerate"}

    final_plan = decision.get("plan") if action == "confirm" and decision.get("plan") else described
    return {
        "current_node": "node3_preview",
        "transform_plan": final_plan,
        "transform_approved": action == "confirm",
        "transform_preview_action": action,
    }


def _route_after_preview(state: AnalysisState) -> str:
    action = state.get("transform_preview_action")
    if action == "regenerate":
        return "node3_plan_init"
    if action == "reject":
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
        return "node_hypothesis_init"
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


def node_hypothesis_init(state: AnalysisState) -> dict:
    """假设树懒初始化，必须作为独立节点跑在 node_hypothesis_tree 的 interrupt() 之前。

    LangGraph 恢复 interrupt 时会把所在节点函数从头重新执行；若初始树生成放在
    node_hypothesis_tree 内部 interrupt() 之前，由于 interrupt() 暂停时这次生成
    从未通过 return 提交到 checkpoint，第一次 resume 时会重新整体生成一棵内容
    完全不同的新树，而用户实际看到/选择验证的是旧树的某个节点 —— 二者 id 凑巧都是
    "1.1" 这类格式，于是验证结果被错配到新树同id但语义完全不同的节点上
    （2026-06-18 实测复现）。本节点用普通 return 提交生成结果，确保
    node_hypothesis_tree 重跑时读到的 state.hypothesis_tree 已经非空。
    """
    tree = state.get("hypothesis_tree") or []
    if not tree:
        problem_card = state.get("problem_card") or {}
        tree = apply_ops(tree, generate_initial_ops(problem_card))
        tree = apply_ops(tree, generate_dedupe_ops(tree, problem_card))
    return {"current_node": "node_hypothesis_init", "hypothesis_tree": tree}


def node_hypothesis_tree(state: AnalysisState) -> dict:
    """阶段二（假设树）：每次 interrupt 等待用户下一步动作
    {"action": "chat"|"verify"|"conclude", ...}：
    - chat：message 经 LLM 转为增量操作（可能为空，纯聊天不调整树），留在本节点
    - verify：携带 node_id + module（registry 模块名），路由去 node_verification
    - conclude：路由去 node_conclusion 生成综合结论

    初始树生成已移至 node_hypothesis_init，本节点进入时 tree 必须已非空。
    """
    tree = state.get("hypothesis_tree") or []

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


# 前端推荐确认卡片里"标记为数据不足，跳过验证"对应的 verifying_module 哨兵值——
# 复用已有字段而不新增 state key（体验反馈#3：当前数据没有任何列能支撑该假设的因果
# 机制时，不应该硬选一个不相关的列跑出一个貌似严谨实则无意义的结论）。
SKIP_VERIFICATION_MODULE = "__skip__"


def node_verification(state: AnalysisState) -> dict:
    """阶段三（验证执行）：复用 registry.get_module(name) 拿到的分析模块在
    全量清洗后数据上跑一次（与 node4_analysis 同一套模块，未做按假设的数据
    子集过滤，留待后续迭代），用 node5_report 的置信度规则+叙事生成判定
    该假设是 verified（置信度非"低"）还是 partial，结果写回假设树对应节点。"""
    node_id = state.get("verifying_node_id")
    verifying_module = state.get("verifying_module")
    tree = state.get("hypothesis_tree") or []
    hypothesis_node = next((n for n in tree if n.get("id") == node_id), None)

    if verifying_module == SKIP_VERIFICATION_MODULE:
        summary = "当前数据缺少支撑该假设所需的字段，无法验证。"
        ops = [
            {"op": "update_status", "node_id": node_id, "status": "partial",
             "node": None, "summary": None, "merge_ids": None, "merged_node": None},
            {"op": "update_summary", "node_id": node_id, "summary": summary, "confidence_level": None,
             "node": None, "status": None, "merge_ids": None, "merged_node": None},
        ]
        tree = apply_ops(tree, ops)
        return {
            "current_node": "node_verification",
            "hypothesis_tree": tree,
            "stage": "hypothesis_tree",
            "verifying_node_id": None,
            "verifying_module": None,
            "last_verification": None,
        }

    module = default_registry.get_module(verifying_module or "")
    df = pd.read_parquet(_data_path(state))

    last_verification = None
    if module is None or not module.validate(df):
        summary = "所选验证方式不适用于当前数据，请换一个假设或模块重新验证。"
        ops = [{"op": "update_summary", "node_id": node_id, "summary": summary,
                "node": None, "status": None, "merge_ids": None, "merged_node": None}]
    else:
        config = (
            suggest_verification_config(hypothesis_node, state.get("problem_card") or {}, module.name, df)
            if hypothesis_node else {}
        )
        metrics = module.run(df, config)
        confidence = _compute_confidence(df, module.name, module.category, metrics)
        narrative, _ = _generate_narrative(
            module.category,
            metrics,
            hypothesis_label=hypothesis_node.get("label") if hypothesis_node else None,
            problem_card=state.get("problem_card"),
        )
        verdict_status = {"support": "verified", "refute": "rejected", "inconclusive": "partial"}.get(narrative.get("verdict"))
        status = verdict_status or ("verified" if confidence["level"] != "低" else "partial")
        ops = [
            {"op": "update_status", "node_id": node_id, "status": status,
             "node": None, "summary": None, "merge_ids": None, "merged_node": None},
            {"op": "update_summary", "node_id": node_id, "summary": narrative.get("conclusion", ""),
             "confidence_level": confidence["level"],
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


HYPOTHESIS_STATUS_LABELS = {
    "pending": "待验证",
    "verifying": "验证中",
    "verified": "已验证支持",
    "rejected": "已排除",
    "partial": "部分验证",
}

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_template_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=select_autoescape(["html"])
)


def node_conclusion(state: AnalysisState) -> dict:
    """阶段三结束：汇总假设树各节点验证结果生成结构化综合结论，渲染为HTML并
    落盘到 session_dir/report.html（解决此前 report_html 只存在于LangGraph
    内存state、进程重启/checkpoint丢失后报告拿不到的问题），同时仍写回
    state.report_html 保持 GET /api/report/{session_id}/html 兼容。"""
    problem_card = state.get("problem_card") or {}
    tree = state.get("hypothesis_tree") or []
    conclusion = generate_conclusion_narrative(problem_card, tree)

    groups: dict[str, list[dict]] = {}
    for node in tree:
        groups.setdefault(node.get("group") or "未分组", []).append(node)

    template = _template_env.get_template("minerva_conclusion.html.j2")
    report_html = template.render(
        problem_card=problem_card,
        groups=groups,
        status_labels=HYPOTHESIS_STATUS_LABELS,
        conclusion=conclusion,
    )

    session_id = state.get("session_id")
    if session_id:
        path = report_html_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report_html, encoding="utf-8")

    return {"current_node": "node_conclusion", "report_html": report_html, "stage": "conclusion"}


def _build_graph():
    builder = StateGraph(AnalysisState)

    builder.add_node("node0_clarification", node0_clarification)
    builder.add_node("node_awaiting_data", node_awaiting_data)
    builder.add_node("node1_diagnosis", node1_diagnosis)
    builder.add_node("node2_confirmation", node2_confirmation)
    builder.add_node("node3_plan_init", node3_plan_init)
    builder.add_node("node3_preview", node3_preview)
    builder.add_node("node3_transform", node3_transform)
    builder.add_node("node4_analysis", node4_analysis)
    builder.add_node("node5_report", node5_report)
    builder.add_node("node6_followup", node6_followup)
    builder.add_node("node_hypothesis_init", node_hypothesis_init)
    builder.add_node("node_hypothesis_tree", node_hypothesis_tree)
    builder.add_node("node_verification", node_verification)
    builder.add_node("node_conclusion", node_conclusion)

    builder.set_entry_point("node0_clarification")
    # node0 自循环：旧版（数据已上传）直入node1；Minerva版对话未收敛时自循环，
    # 收敛后转 node_awaiting_data 等待上传
    builder.add_conditional_edges("node0_clarification", _route_after_node0)
    builder.add_edge("node_awaiting_data", "node1_diagnosis")
    builder.add_edge("node1_diagnosis", "node2_confirmation")
    builder.add_edge("node2_confirmation", "node3_plan_init")
    builder.add_edge("node3_plan_init", "node3_preview")
    builder.add_conditional_edges("node3_preview", _route_after_preview)
    # node3_transform 之后：旧版直入node4分析报告；Minerva版转假设树验证循环
    builder.add_conditional_edges("node3_transform", _route_after_transform)
    builder.add_edge("node4_analysis", "node5_report")
    builder.add_edge("node5_report", "node6_followup")
    # node6 self-loop：每次处理一条消息后返回，由条件边决定继续或退出
    builder.add_conditional_edges("node6_followup", _route_after_node6)
    builder.add_edge("node_hypothesis_init", "node_hypothesis_tree")
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
