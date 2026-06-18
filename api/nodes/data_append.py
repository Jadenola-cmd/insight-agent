"""Step5 增量上传支持：假设验证阶段中途发现缺字段时，追加上传一个文件并合并进
当前 session 的已清洗数据。不经过 LangGraph（不打断 node_hypothesis_tree 的
interrupt），直接对 cleaned_data_path/merged_data_path 指向的文件做读写，
与 node3_preview/node2 的 join 方案确认是同一种"propose 数据不进 state、只读写
文件路径"的设计（CLAUDE.md 约束4）。
"""

import json

import pandas as pd

from api.services.llm import chat_json


def generate_append_plan(existing_columns: list[str], new_df: pd.DataFrame, new_table_name: str) -> dict:
    """生成"新文件 -> 已有清洗数据"的合并方案（LLM 不可用时降级为同名列匹配）。"""
    new_columns = [str(c) for c in new_df.columns]
    sample_values = {str(c): str(new_df[c].dropna().head(3).tolist()) for c in new_df.columns[:10]}

    system_prompt = (
        "你是数据分析助手。用户在分析过程中追加上传了一个新文件，需要将其与已有的"
        "清洗后数据表合并。请输出合并方案。\n"
        "规则：\n"
        "1. on 条件优先选两表中含义相同的列名（如 user_id/订单号等标识列）\n"
        "2. how 默认 left（保留已有数据的全部行）\n"
        "严格按指定JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
    )
    user_prompt = f"""已有清洗后数据的列名：
{json.dumps(existing_columns, ensure_ascii=False)}

新文件「{new_table_name}」的列名：
{json.dumps(new_columns, ensure_ascii=False)}

新文件样例值：
{json.dumps(sample_values, ensure_ascii=False)}

请输出合并方案JSON：
{{
  "on": {{"left_col": "已有数据中的列名", "right_col": "新文件中的列名"}},
  "how": "left",
  "purpose": "中文说明"
}}
"""
    result = chat_json(system_prompt, user_prompt)
    if (
        result
        and isinstance(result.get("on"), dict)
        and "left_col" in result["on"]
        and "right_col" in result["on"]
    ):
        return {
            "on": {"left_col": result["on"]["left_col"], "right_col": result["on"]["right_col"]},
            "how": result.get("how", "left"),
            "purpose": result.get("purpose", ""),
        }

    # 降级：优先找同名列，否则各自取第一列
    common = [c for c in new_columns if c in existing_columns]
    left_col = common[0] if common else existing_columns[0]
    right_col = common[0] if common else new_columns[0]
    return {
        "on": {"left_col": left_col, "right_col": right_col},
        "how": "left",
        "purpose": f"自动关联 {new_table_name}（LLM不可用，降级方案，按列名匹配）",
    }


def execute_append(existing_df: pd.DataFrame, new_df: pd.DataFrame, plan: dict) -> pd.DataFrame:
    """按 plan 执行合并，返回合并后的 DataFrame（不落盘，由调用方写入对应路径）。"""
    on = plan["on"]
    how = plan.get("how", "left")
    merged = pd.merge(
        existing_df,
        new_df,
        left_on=on["left_col"],
        right_on=on["right_col"],
        how=how,
        suffixes=("", "_append"),
    )
    return merged
