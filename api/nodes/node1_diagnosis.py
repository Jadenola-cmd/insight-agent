import json

import pandas as pd

from api.services.llm import chat_json

HIGH_NULL_RATE_THRESHOLD = 0.5


def _column_stats(df: pd.DataFrame) -> list[dict]:
    n = len(df)
    columns = []
    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())
        null_rate = round(null_count / n, 4) if n else 0.0

        issues = []
        if null_rate > HIGH_NULL_RATE_THRESHOLD:
            issues.append(f"空值率过高（{null_rate:.0%}）")

        columns.append(
            {
                "name": str(col),
                "dtype": str(series.dtype),
                "null_rate": null_rate,
                "unique_count": int(series.nunique(dropna=True)),
                "sample_values": [str(v) for v in series.dropna().unique()[:5].tolist()],
                "issues": issues,
            }
        )
    return columns


def _detect_table_issues(df: pd.DataFrame) -> list[str]:
    issues = []
    columns = list(df.columns)

    # 数据完全一致的列：疑似重复字段
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            col_a, col_b = columns[i], columns[j]
            if df[col_a].equals(df[col_b]):
                issues.append(f'列 "{col_a}" 与 "{col_b}" 数据完全一致，疑似重复字段')

    # 列名规范化后相同：疑似命名冲突
    normalized: dict[str, list[str]] = {}
    for col in columns:
        key = str(col).strip().lower().replace("_", "").replace(" ", "")
        normalized.setdefault(key, []).append(str(col))
    for cols in normalized.values():
        if len(cols) > 1:
            issues.append(f"列名 {cols} 规范化后相同，疑似命名冲突")

    return issues


def _llm_infer(columns: list[dict]) -> dict | None:
    summary = json.dumps(
        [
            {k: v for k, v in col.items() if k != "issues"}
            for col in columns
        ],
        ensure_ascii=False,
    )

    system_prompt = (
        "你是数据分析助手，负责根据字段统计摘要推断每个字段的业务含义并识别口径问题。"
        "严格按指定JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
    )
    user_prompt = f"""字段统计摘要（JSON数组，每项含 name/dtype/null_rate/unique_count/sample_values）：
{summary}

请输出以下JSON结构：
{{
  "columns": [
    {{"name": "字段名（须与输入一致）", "inferred_meaning": "对该字段业务含义的简要推断", "issues": ["该字段可能存在的口径问题描述", "..."]}}
  ],
  "table_issues": ["整张表级别的口径问题，如字段含义重叠、命名不规范等，没有则返回空数组"]
}}
"""
    return chat_json(system_prompt, user_prompt)


def run_diagnosis(raw_data_path: str) -> dict:
    """Node1：读取原始数据，输出结构化诊断报告。

    LLM 不可用时仍返回 Pandas 统计结果，inferred_meaning 标记为降级提示，
    不阻断流程（用户仍可在 Node2 手动确认）。
    """
    df = pd.read_csv(raw_data_path)

    columns = _column_stats(df)
    table_issues = _detect_table_issues(df)

    llm_result = _llm_infer(columns)
    llm_columns_by_name: dict[str, dict] = {}
    if llm_result and isinstance(llm_result.get("columns"), list):
        llm_columns_by_name = {
            c["name"]: c for c in llm_result["columns"] if isinstance(c, dict) and "name" in c
        }
        table_issues.extend(llm_result.get("table_issues") or [])

    report_columns = []
    for col in columns:
        llm_col = llm_columns_by_name.get(col["name"], {})
        inferred_meaning = llm_col.get("inferred_meaning") or "AI推断暂不可用"
        combined_issues = col["issues"] + (llm_col.get("issues") or [])
        report_columns.append(
            {
                **col,
                "inferred_meaning": inferred_meaning,
                "issues": combined_issues,
            }
        )

    return {
        "row_count": len(df),
        "columns": report_columns,
        "table_issues": table_issues,
        "llm_available": llm_result is not None,
    }
