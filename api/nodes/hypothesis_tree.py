"""假设树固定操作函数 + LLM增量生成（Minerva重构 Step2/3，2026-06-18）。

对应 api/core/schema.py 的 HypothesisNode/HypothesisTreeOp：LLM 只负责输出
HypothesisTreeOp 列表（JSON），树本身的增删改一律由本模块的 apply_ops 执行，
不允许 LLM 直接吐自由文本树或整棵树重写（CLAUDE.md 约束3 对 Node3 清洗 plan
的同一原则，延伸到假设树）。
"""
import json

import pandas as pd

from api.services.llm import chat_json

VALID_STATUSES = {"pending", "verifying", "verified", "rejected", "partial"}

# 各分析模块 run() 接受的 config key，LLM 只能从对应集合里选列，不能瞎填字段名
MODULE_CONFIG_KEYS = {
    "trend_insight": ["date_column", "value_column"],
    "comparison": ["category_column", "value_column"],
    "segmentation": ["id_column", "value_column"],
    "attribution": ["dependent_column", "independent_columns"],
    "funnel": [],
}


def apply_ops(tree: list[dict], ops: list[dict]) -> list[dict]:
    """把一组增量操作应用到已有假设树上，返回新树（不修改入参）。"""
    tree = [dict(node) for node in tree]
    by_id = {node["id"]: node for node in tree}

    for op in ops:
        kind = op.get("op")
        if kind == "add_node" and op.get("node"):
            node = dict(op["node"])
            node.setdefault("status", "pending")
            node.setdefault("verification_summary", None)
            node.setdefault("confidence_level", None)
            if node["id"] in by_id:
                continue  # 防止LLM重复生成同id节点
            tree.append(node)
            by_id[node["id"]] = node
        elif kind == "update_status":
            node = by_id.get(op.get("node_id"))
            status = op.get("status")
            if node and status in VALID_STATUSES:
                node["status"] = status
        elif kind == "update_summary":
            node = by_id.get(op.get("node_id"))
            if node:
                node["verification_summary"] = op.get("summary")
                if op.get("confidence_level") in ("高", "中", "低"):
                    node["confidence_level"] = op.get("confidence_level")
        elif kind == "merge_node":
            merge_ids = set(op.get("merge_ids") or [])
            merged_node = op.get("merged_node")
            if not merge_ids or not merged_node:
                continue
            tree = [node for node in tree if node["id"] not in merge_ids]
            for node_id in merge_ids:
                by_id.pop(node_id, None)
            tree.append(merged_node)
            by_id[merged_node["id"]] = merged_node
        elif kind == "remove_node":
            node_id = op.get("node_id")
            tree = [node for node in tree if node["id"] != node_id]
            by_id.pop(node_id, None)

    return tree


def _fallback_initial_ops(problem_card: dict) -> list[dict]:
    """LLM不可用时的降级：给一个占位假设节点，不阻断流程。"""
    goal = problem_card.get("analysis_goal") or problem_card.get("question") or "待分析问题"
    return [{
        "op": "add_node",
        "node": {
            "id": "1.1",
            "parent": None,
            "group": "待分类",
            "label": f"针对「{goal}」补充具体假设（AI生成暂不可用，请手动编辑）",
            "priority": False,
            "status": "pending",
            "verification_summary": None,
        },
        "node_id": None, "status": None, "summary": None, "merge_ids": None, "merged_node": None,
    }]


def generate_initial_ops(problem_card: dict) -> list[dict]:
    """阶段二开场：基于问题陈述卡片，让LLM一次性生成初始假设树（多条 add_node）。"""
    system_prompt = (
        "你是结构化分析思维伙伴。基于用户的问题陈述卡片，穷举可能的原因假设，"
        "按【供给侧/需求侧/数据侧】等分组（group），标注哪些假设应优先验证"
        "（priority=true，验证成本低+解释力强的假设）。"
        "假设集合必须满足MECE原则（相互独立、完全穷尽）：不同分组的假设之间不能"
        "描述同一个因果机制（哪怕表述不同），生成前先检查每条新假设是否与已列出的"
        "假设本质重叠，重叠就合并或换一个更具体的角度，而不是同一件事换个说法重复列出。"
        "只输出增量操作列表，每条假设对应一个 op=add_node 操作，id格式如'1.1'/'2.1'，"
        "同分组共享数字前缀。严格按JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
    )
    user_prompt = f"""问题陈述卡片（JSON）：{json.dumps(problem_card, ensure_ascii=False)}

请输出以下JSON结构：
{{"ops": [{{"op": "add_node", "node": {{"id": "1.1", "parent": null, "group": "供给侧",
"label": "假设描述", "priority": true, "status": "pending", "verification_summary": null}}}}, ...]}}
"""
    result = chat_json(system_prompt, user_prompt)
    ops = result.get("ops") if result else None
    if not ops:
        return _fallback_initial_ops(problem_card)
    return ops


def generate_dedupe_ops(tree: list[dict], problem_card: dict) -> list[dict]:
    """初始树生成后的MECE自检：识别本质重叠（同一因果机制、表述不同）的假设节点，
    输出 merge_node 操作合并它们。LLM不可用或没有重叠时返回空列表，不阻断流程。"""
    if len(tree) < 2:
        return []
    system_prompt = (
        "你是结构化分析思维伙伴，正在检查一棵刚生成的假设树是否满足MECE"
        "（相互独立、完全穷尽）。重点检查不同分组（供给侧/需求侧/数据侧等）之间是否"
        "出现本质相同或高度重叠的假设——判断标准是背后的因果机制是否相同，而不是"
        "表面文字是否相似。对每组重叠假设输出一个 merge_node 操作，合并为一条更准确、"
        "更具体可验证的假设描述；没有重叠时返回空操作列表，不要为了凑数而合并。"
        "严格按JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
    )
    user_prompt = f"""问题陈述卡片（JSON）：{json.dumps(problem_card, ensure_ascii=False)}
当前假设树（JSON）：{json.dumps(tree, ensure_ascii=False)}

请输出以下JSON结构（无重叠时 ops 为空数组）：
{{"ops": [{{"op": "merge_node", "merge_ids": ["1.1", "2.3"], "merged_node": {{"id": "1.1",
"parent": null, "group": "供给侧", "label": "合并后的假设描述", "priority": true,
"status": "pending", "verification_summary": null}}}}]}}
"""
    result = chat_json(system_prompt, user_prompt)
    return (result.get("ops") if result else None) or []


def generate_chat_ops(tree: list[dict], problem_card: dict, message: str) -> list[dict]:
    """阶段二对话中的增量更新：用户补充信息/质疑现有假设时，LLM输出增量操作
    （新增/合并/删除假设节点），不重写整棵树。LLM不可用或无需调整时返回空列表。"""
    system_prompt = (
        "你是结构化分析思维伙伴，正在和用户讨论一棵假设树。根据用户本轮发言，"
        "判断是否需要调整假设树：补充新假设用 add_node，发现两个假设本质相同用 "
        "merge_node，假设明显不成立或用户要求去掉用 remove_node。"
        "如果用户只是提问/闲聊、不需要调整树结构，返回空操作列表。"
        "严格按JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
    )
    user_prompt = f"""问题陈述卡片（JSON）：{json.dumps(problem_card, ensure_ascii=False)}
当前假设树（JSON）：{json.dumps(tree, ensure_ascii=False)}
用户本轮发言：{message}

请输出以下JSON结构（无需调整时 ops 为空数组）：
{{"ops": [...]}}
"""
    result = chat_json(system_prompt, user_prompt)
    return (result.get("ops") if result else None) or []


def suggest_verification_config(hypothesis_node: dict, problem_card: dict, module_name: str, df: pd.DataFrame) -> dict:
    """验证假设前，让LLM从该模块允许的config key中挑选最贴合假设文本的列，
    取代此前 module.run(df, {}) 永远盲选第一个数值列（#6/#7/#9 根因之一）。
    LLM不可用或选不出来时返回空dict，模块退回各自的自动检测逻辑。"""
    allowed_keys = MODULE_CONFIG_KEYS.get(module_name, [])
    if not allowed_keys:
        return {}

    columns_info = [
        {"column": c, "dtype": str(df[c].dtype)} for c in df.columns
    ]
    system_prompt = (
        "你是数据分析助手，要为验证某个业务假设选择最相关的数据列。"
        f"目标分析模块只接受以下config字段：{allowed_keys}。"
        "只能从给定的列名中选择，不要编造列名；如果某个字段不需要指定（用默认即可），"
        "就不要输出该key。independent_columns 是数组。"
        "严格按JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
    )
    user_prompt = f"""问题陈述卡片（JSON）：{json.dumps(problem_card, ensure_ascii=False)}
待验证假设：{hypothesis_node.get("label")}（分组：{hypothesis_node.get("group")}）
数据列（列名+类型）：{json.dumps(columns_info, ensure_ascii=False)}

请输出以下JSON结构（config为空对象表示用默认自动检测）：
{{"config": {{}}}}
"""
    result = chat_json(system_prompt, user_prompt)
    config = result.get("config") if result else None
    if not isinstance(config, dict):
        return {}

    cleaned = {}
    for key, value in config.items():
        if key not in allowed_keys:
            continue
        if key == "independent_columns":
            if isinstance(value, list):
                valid = [c for c in value if c in df.columns]
                if valid:
                    cleaned[key] = valid
        elif isinstance(value, str) and value in df.columns:
            cleaned[key] = value
    return cleaned


def _fallback_conclusion(tree: list[dict]) -> dict:
    """LLM不可用时的降级：基于各分组验证状态统计生成稍详细的默认文案，
    而不是只说"AI解读暂不可用"。"""
    verified = [n for n in tree if n.get("status") == "verified"]
    partial = [n for n in tree if n.get("status") == "partial"]
    rejected = [n for n in tree if n.get("status") == "rejected"]
    pending = [n for n in tree if n.get("status") in ("pending", "verifying")]

    parts = [f"假设树共 {len(tree)} 条假设："]
    if verified:
        parts.append(f"{len(verified)} 条已验证支持（" + "、".join(n.get("label", "") for n in verified) + "）。")
    if partial:
        parts.append(f"{len(partial)} 条部分验证（" + "、".join(n.get("label", "") for n in partial) + "）。")
    if rejected:
        parts.append(f"{len(rejected)} 条已排除（" + "、".join(n.get("label", "") for n in rejected) + "）。")
    if pending:
        parts.append(f"{len(pending)} 条尚未验证。")
    executive_summary = "AI综合解读暂不可用，以下为各假设验证状态的自动汇总：" + "".join(parts)

    if verified or partial:
        recommendation = "建议优先围绕已验证支持的假设制定行动方案，并对部分验证的假设补充数据进一步确认。"
    else:
        recommendation = "当前尚无已验证支持的假设，建议补充数据或调整假设后继续验证。"

    caveats = []
    if pending:
        caveats.append("仍有假设未完成验证，结论可能不完整。")
    if not tree:
        caveats.append("假设树为空，以下结论不具备参考价值。")

    return {
        "executive_summary": executive_summary,
        "recommendation": recommendation,
        "caveats": caveats,
    }


def generate_conclusion_narrative(problem_card: dict, tree: list[dict]) -> dict:
    """阶段三结束、综合结论：汇总假设树各节点验证状态，生成结构化结论
    （执行摘要/建议/注意事项），交给 minerva_conclusion.html.j2 渲染，
    不再让LLM直接吐裸HTML。"""
    system_prompt = (
        "你是商业分析报告撰写助手。基于问题陈述和假设树的验证结果，撰写综合结论。"
        "executive_summary：说明哪些假设被验证支持、哪些被排除、最终业务解释是什么；"
        "recommendation：给出可执行的下一步建议；"
        "caveats：分析的局限性或需要注意的事项（如样本不足、仍有假设未验证），"
        "没有局限性时返回空数组。"
        "输出严格的JSON，不要输出任何多余文字、不要使用Markdown代码块、"
        "不要在字段值中包含HTML标签。"
    )
    user_prompt = f"""问题陈述卡片（JSON）：{json.dumps(problem_card, ensure_ascii=False)}
假设树最终状态（JSON）：{json.dumps(tree, ensure_ascii=False)}

请输出以下JSON结构：
{{"executive_summary": "...", "recommendation": "...", "caveats": ["..."]}}
"""
    result = chat_json(system_prompt, user_prompt)
    if result and result.get("executive_summary"):
        return {
            "executive_summary": result.get("executive_summary", ""),
            "recommendation": result.get("recommendation", ""),
            "caveats": result.get("caveats") or [],
        }

    return _fallback_conclusion(tree)
