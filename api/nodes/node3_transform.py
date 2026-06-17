import json

import pandas as pd

from api.services.llm import chat_json

# LLM 补充 plan 只允许输出这5类操作（其余4类由 confirmed_schema 确定性推导）
ALLOWED_LLM_OPS = {
    "cast_type",
    "strip_whitespace",
    "standardize_categories",
    "unit_convert",
    "drop_duplicates",
}

# 固定执行顺序，与 plan 数组中的原始顺序无关（见 docs/ARCHITECTURE.md 3.3节）
EXECUTION_ORDER = [
    "rename_column",
    "drop_columns",
    "cast_type",
    "strip_whitespace",
    "standardize_categories",
    "unit_convert",
    "fillna",
    "drop_rows_with_null",
    "drop_duplicates",
]


def _build_deterministic_ops(confirmed_schema: dict) -> list[dict]:
    """根据 confirmed_schema 直接推导 rename/drop_columns/fillna/drop_rows_with_null。"""
    ops = []
    drop_columns = []
    drop_rows_null_columns = []

    for col in confirmed_schema["columns"]:
        if not col["include"]:
            drop_columns.append(col["original_name"])
            continue

        if col["final_name"] != col["original_name"]:
            ops.append({"op": "rename_column", "from": col["original_name"], "to": col["final_name"]})

        if col["missing_value_strategy"] == "fill":
            ops.append({"op": "fillna", "column": col["final_name"], "value": col["fill_value"]})
        elif col["missing_value_strategy"] == "drop_rows":
            drop_rows_null_columns.append(col["final_name"])

    if drop_columns:
        ops.append({"op": "drop_columns", "columns": drop_columns})
    if drop_rows_null_columns:
        ops.append({"op": "drop_rows_with_null", "columns": drop_rows_null_columns})

    return ops


def _llm_supplementary_ops(confirmed_schema: dict, deterministic_ops: list[dict]) -> tuple[list[dict], bool]:
    """请求 LLM 输出补充清洗操作（仅 ALLOWED_LLM_OPS 范围内）。

    返回 (ops, llm_available)。LLM 不可用或返回格式不合法时返回 ([], False)，
    不阻断流程（仅执行确定性部分）。
    """
    included_columns = [
        {"final_name": col["final_name"], "business_meaning": col["business_meaning"]}
        for col in confirmed_schema["columns"]
        if col["include"]
    ]
    resolved_table_issues = confirmed_schema.get("resolved_table_issues", [])

    system_prompt = (
        "你是数据清洗助手，根据字段业务含义和用户对表级口径问题的处理说明，输出补充清洗操作列表。"
        "严格按指定JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
        "只允许输出以下5种操作类型：cast_type、strip_whitespace、standardize_categories、"
        "unit_convert、drop_duplicates。列名必须使用给定的 final_name。"
        "如果没有需要补充的操作，ops 返回空数组。"
    )
    user_prompt = f"""字段列表（final_name + business_meaning）：
{json.dumps(included_columns, ensure_ascii=False)}

已确定执行的清洗操作（供参考，避免重复处理同一列）：
{json.dumps(deterministic_ops, ensure_ascii=False)}

用户对表级口径问题的处理说明：
{json.dumps(resolved_table_issues, ensure_ascii=False)}

请输出以下JSON结构：
{{
  "ops": [
    {{"op": "cast_type", "column": "...", "to": "int|float|string|datetime|bool", "format": "可选，datetime专用的pandas格式串"}},
    {{"op": "strip_whitespace", "columns": ["..."]}},
    {{"op": "standardize_categories", "column": "...", "mapping": {{"原值": "标准值"}}}},
    {{"op": "unit_convert", "column": "...", "factor": 0.01, "new_name": "可选"}},
    {{"op": "drop_duplicates", "subset": ["..."]}}
  ]
}}
"""
    result = chat_json(system_prompt, user_prompt)
    if not result or not isinstance(result.get("ops"), list):
        return [], result is not None

    ops = [op for op in result["ops"] if isinstance(op, dict) and op.get("op") in ALLOWED_LLM_OPS]
    return ops, True


def _order_plan(ops: list[dict]) -> list[dict]:
    """按 EXECUTION_ORDER 重排 plan；未识别的 op 直接报错中止；合并多条 drop_columns。"""
    grouped: dict[str, list[dict]] = {op_name: [] for op_name in EXECUTION_ORDER}
    for op in ops:
        op_type = op.get("op")
        if op_type not in grouped:
            raise ValueError(f"未知的清洗操作类型: {op_type}")
        grouped[op_type].append(op)

    if len(grouped["drop_columns"]) > 1:
        merged_columns: list[str] = []
        for op in grouped["drop_columns"]:
            for column in op.get("columns", []):
                if column not in merged_columns:
                    merged_columns.append(column)
        grouped["drop_columns"] = [{"op": "drop_columns", "columns": merged_columns}] if merged_columns else []

    ordered = []
    for op_name in EXECUTION_ORDER:
        ordered.extend(grouped[op_name])
    return ordered


# ---- op_* 执行函数：固定 Python 函数集合，严禁 eval/exec ----


def op_rename_column(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    return df.rename(columns={op["from"]: op["to"]})


def op_drop_columns(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    columns = [c for c in op["columns"] if c in df.columns]
    return df.drop(columns=columns)


def op_cast_type(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    """类型转换失败时跳过该列，不中止流程。"""
    column = op["column"]
    if column not in df.columns:
        return df
    to = op["to"]
    try:
        if to == "datetime":
            df[column] = pd.to_datetime(df[column], format=op.get("format"), errors="coerce")
        elif to == "int":
            df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
        elif to == "float":
            df[column] = pd.to_numeric(df[column], errors="coerce")
        elif to == "string":
            df[column] = df[column].astype("string")
        elif to == "bool":
            bool_map = {"true": True, "1": True, "yes": True, "是": True, "false": False, "0": False, "no": False, "否": False}
            df[column] = df[column].astype("string").str.strip().str.lower().map(bool_map)
        else:
            print(f"cast_type: 未知目标类型 '{to}'，跳过列 '{column}'")
    except Exception as e:
        print(f"cast_type: 列 '{column}' 转换为 '{to}' 失败，跳过: {e}")
    return df


def op_strip_whitespace(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    for column in op["columns"]:
        if pd.api.types.is_object_dtype(df[column]) or pd.api.types.is_string_dtype(df[column]):
            df[column] = df[column].str.strip()
    return df


def op_standardize_categories(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    df[op["column"]] = df[op["column"]].replace(op["mapping"])
    return df


def op_unit_convert(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    column = op["column"]
    df[column] = pd.to_numeric(df[column], errors="coerce") * op["factor"]

    new_name = op.get("new_name")
    if new_name and new_name != column:
        df = df.rename(columns={column: new_name})

    return df


def op_fillna(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    df[op["column"]] = df[op["column"]].fillna(op["value"])
    return df


def op_drop_rows_with_null(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    columns = [c for c in op["columns"] if c in df.columns]
    return df.dropna(subset=columns)


def op_drop_duplicates(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    return df.drop_duplicates(subset=op.get("subset"))


OP_FUNCTIONS = {
    "rename_column": op_rename_column,
    "drop_columns": op_drop_columns,
    "cast_type": op_cast_type,
    "strip_whitespace": op_strip_whitespace,
    "standardize_categories": op_standardize_categories,
    "unit_convert": op_unit_convert,
    "fillna": op_fillna,
    "drop_rows_with_null": op_drop_rows_with_null,
    "drop_duplicates": op_drop_duplicates,
}


def run_transform(raw_data_path: str, confirmed_schema: dict, cleaned_data_path: str) -> dict:
    """Node3：执行确定性清洗 plan，写入 cleaned_data_path（parquet）。"""
    df = pd.read_csv(raw_data_path)

    deterministic_ops = _build_deterministic_ops(confirmed_schema)
    llm_ops, llm_available = _llm_supplementary_ops(confirmed_schema, deterministic_ops)

    plan = _order_plan(deterministic_ops + llm_ops)

    for op in plan:
        try:
            df = OP_FUNCTIONS[op["op"]](df, op)
        except Exception as e:
            print(f"清洗操作 {op.get('op')} 执行失败，跳过: {e}")

    df.to_parquet(cleaned_data_path, index=False)

    return {
        "plan": plan,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": [str(c) for c in df.columns],
        "llm_available": llm_available,
    }
