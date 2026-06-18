"""假设树固定操作函数 + LLM增量生成（Minerva重构 Step2/3，2026-06-18）。

对应 api/core/schema.py 的 HypothesisNode/HypothesisTreeOp：LLM 只负责输出
HypothesisTreeOp 列表（JSON），树本身的增删改一律由本模块的 apply_ops 执行，
不允许 LLM 直接吐自由文本树或整棵树重写（CLAUDE.md 约束3 对 Node3 清洗 plan
的同一原则，延伸到假设树）。
"""
import json

from api.services.llm import chat_json

VALID_STATUSES = {"pending", "verifying", "verified", "rejected", "partial"}


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


def generate_conclusion_narrative(problem_card: dict, tree: list[dict]) -> str:
    """阶段三结束、综合结论：汇总假设树各节点验证状态，生成一段HTML格式的结论。"""
    system_prompt = (
        "你是商业分析报告撰写助手。基于问题陈述和假设树的验证结果，写一段"
        "综合结论：哪些假设被验证支持、哪些被排除，最终业务解释是什么，"
        "给出可执行的下一步建议。输出严格的JSON，不要输出任何多余文字、"
        "不要使用Markdown代码块。"
    )
    user_prompt = f"""问题陈述卡片（JSON）：{json.dumps(problem_card, ensure_ascii=False)}
假设树最终状态（JSON）：{json.dumps(tree, ensure_ascii=False)}

请输出以下JSON结构：
{{"conclusion_html": "一段可直接展示的HTML（用<p>分段）"}}
"""
    result = chat_json(system_prompt, user_prompt)
    if result and result.get("conclusion_html"):
        return result["conclusion_html"]

    verified = [n for n in tree if n.get("status") in ("verified", "partial")]
    rejected = [n for n in tree if n.get("status") == "rejected"]
    lines = ["<p>综合结论（AI解读暂不可用，以下为各假设验证状态汇总）：</p>", "<ul>"]
    for node in tree:
        lines.append(f"<li>[{node.get('status')}] {node.get('label')}：{node.get('verification_summary') or '未验证'}</li>")
    lines.append("</ul>")
    return "".join(lines)
