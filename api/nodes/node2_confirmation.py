"""Node2: 字段口径确认 + Join方案确认（双阶段 Human-in-the-loop）。

Phase 1: 推送诊断报告，等待用户提交 confirmed_schema
Phase 2: 基于 confirmed_schema 和上传的多个表，LLM 生成 join_plan 提案，等待用户确认
"""

import json
import os
from pathlib import Path

import pandas as pd
from langgraph.types import interrupt

from api.core.paths import session_dir
from api.services.llm import chat_json

TABLES_DIR_NAME = "tables"


def _tables_dir(session_id: str) -> Path:
    return session_dir(session_id) / TABLES_DIR_NAME


def _list_table_files(session_id: str) -> list[Path]:
    """列出 session 下所有独立表文件。"""
    td = _tables_dir(session_id)
    if not td.exists():
        return []
    return sorted(td.glob("*.csv"))


def _generate_join_plan(session_id: str, confirmed_schema: dict) -> dict | None:
    """使用 LLM 生成 join 方案；LLM 不可用时返回降级方案。

    规则：
    - 行数最多的事实表做 primary_table
    - 事实表之间 left join（保留上游所有用户）
    - 维度表 left join 补充属性
    - LLM 不可用时降级：全 left join，主表 events 表，key 用 user_id
    """
    table_files = _list_table_files(session_id)

    # 单表场景：无需 join
    if len(table_files) <= 1:
        return {"primary_table": "", "joins": []}

    # 收集各表信息
    table_infos = []
    for fp in table_files:
        try:
            df = pd.read_csv(fp)
            table_infos.append({
                "file": fp.name,
                "table_name": fp.stem,
                "row_count": len(df),
                "columns": [str(c) for c in df.columns],
                "sample_values": {str(c): str(df[c].dropna().head(3).tolist()) for c in df.columns[:10]},
            })
        except Exception:
            continue

    if len(table_infos) <= 1:
        return {"primary_table": "", "joins": []}

    # 尝试 LLM 生成
    system_prompt = (
        "你是数据分析助手，根据多个CSV表的结构信息，输出最优的join方案。\n"
        "规则：\n"
        "1. 行数最多的事实表做 primary_table\n"
        "2. 事实表之间 left join（保留上游所有用户）\n"
        "3. 维度表 left join 补充属性\n"
        "4. on 条件使用两个表中含义相同的列名\n"
        "严格按指定JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
    )
    user_prompt = f"""表信息列表：
{json.dumps(table_infos, ensure_ascii=False)}

已确认的字段口径：
{json.dumps(confirmed_schema, ensure_ascii=False)}

请输出join方案JSON：
{{
  "primary_table": "主表文件名（不含.csv）",
  "joins": [
    {{
      "table": "右表文件名（不含.csv）",
      "on": {{"left_col": "主表列名", "right_col": "右表列名"}},
      "how": "left",
      "purpose": "中文说明"
    }}
  ]
}}
"""

    result = chat_json(system_prompt, user_prompt)
    if result and isinstance(result.get("primary_table"), str) and isinstance(result.get("joins"), list):
        # 校验 joins 结构
        valid_joins = []
        for j in result["joins"]:
            if isinstance(j, dict) and "table" in j and "on" in j:
                valid_joins.append({
                    "table": j["table"],
                    "on": j["on"],
                    "how": j.get("how", "left"),
                    "purpose": j.get("purpose", ""),
                })
        return {"primary_table": result["primary_table"], "joins": valid_joins}

    # 降级：全 left join，主表选行数最多的，key 用 user_id
    primary = max(table_infos, key=lambda t: t["row_count"])
    fallback_joins = []
    for t in table_infos:
        if t["table_name"] == primary["table_name"]:
            continue
        # 尝试找到共同的 key 列
        left_col = "user_id" if "user_id" in primary["columns"] else primary["columns"][0]
        right_col = "user_id" if "user_id" in t["columns"] else t["columns"][0]
        fallback_joins.append({
            "table": t["table_name"],
            "on": {"left_col": left_col, "right_col": right_col},
            "how": "left",
            "purpose": f"自动关联 {t['table_name']}（LLM不可用，降级方案）",
        })

    return {"primary_table": primary["table_name"], "joins": fallback_joins}


def _build_table_columns_map(session_id: str) -> dict[str, list[str]]:
    """构建 {表名: [列名列表]} 映射，供前端展示可用字段。"""
    columns_map = {}
    for fp in _list_table_files(session_id):
        try:
            df = pd.read_csv(fp)
            columns_map[fp.stem] = [str(c) for c in df.columns]
        except Exception:
            columns_map[fp.stem] = []
    return columns_map


def run_node2_confirmation(state: dict) -> dict:
    """Node2 双阶段确认节点函数。

    供 graph.py 调用，内部包含两个 interrupt()：
    1. 第一阶段：字段口径确认
    2. 第二阶段：join 方案确认
    """
    diagnosis = state["analysis_results"]["diagnosis"]
    session_id = state.get("session_id", "")

    # ---- Phase 1: 字段口径确认 ----
    confirmed_schema = interrupt({"diagnosis": diagnosis})

    # 单表场景无需 join，跳过 Phase 2/3 确认，直接返回空方案
    if len(_list_table_files(session_id)) <= 1:
        empty_plan = {"primary_table": "", "joins": []}
        return {
            "current_node": "node2_confirmation",
            "user_confirmations": confirmed_schema,
            "proposed_join_plan": empty_plan,
            "confirmed_join_plan": empty_plan,
        }

    # ---- Phase 2: 生成 join 方案 ----
    proposed_join_plan = _generate_join_plan(session_id, confirmed_schema)
    table_columns = _build_table_columns_map(session_id)

    # ---- Phase 3: join 方案确认 ----
    confirmed_join_plan = interrupt({
        "join_plan": proposed_join_plan,
        "table_columns": table_columns,
    })

    return {
        "current_node": "node2_confirmation",
        "user_confirmations": confirmed_schema,
        "proposed_join_plan": proposed_join_plan,
        "confirmed_join_plan": confirmed_join_plan,
    }
