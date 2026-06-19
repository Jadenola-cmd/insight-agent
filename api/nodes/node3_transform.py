import json
from pathlib import Path

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

TABLES_DIR_NAME = "tables"


def _tables_dir(session_dir: Path) -> Path:
    return session_dir / TABLES_DIR_NAME


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
    不阻断流程（仅执行确定性部分）。"""
    included_columns = [
        {"final_name": col["final_name"], "business_meaning": col["business_meaning"]}
        for col in confirmed_schema["columns"]
        if col["include"]
    ]
    resolved_table_issues = confirmed_schema.get("resolved_table_issues", [])

    system_prompt = (
        "你是数据清洗助手，根据字段业务含义和用户对表级口径问题的处理说明，输出补充清洗操作列表。\n"
        "严格按指定JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。\n"
        "只允许输出以下5种操作类型：cast_type、strip_whitespace、standardize_categories、"
        "unit_convert、drop_duplicates。列名必须使用给定的 final_name。\n"
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
        print(f"cast_type: 列'{column}' 转换为'{to}' 失败，跳过: {e}")
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


# drop_duplicates 是 LLM 自由生成的"补充清洗操作"，没有走用户逐字段确认（不像
# fillna/drop_rows_with_null 来自confirmed_schema里用户的明确选择）。subset 选了
# 几个低基数字段组合时，会把事件日志表里大量"看起来相同但实际是独立事件"的行误判
# 为重复，一次性删掉大半数据且不会报错（曾在QA回归里复现：16237行被去重到84行）。
# 删除比例超过阈值时跳过该操作，保留原数据，避免静默的灾难性数据丢失。
MAX_DROP_DUPLICATES_RATIO = 0.5


def op_drop_duplicates(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    deduped = df.drop_duplicates(subset=op.get("subset"))
    if len(df) > 0 and len(deduped) < len(df) * (1 - MAX_DROP_DUPLICATES_RATIO):
        print(
            f"drop_duplicates: subset={op.get('subset')} 会删除 "
            f"{len(df) - len(deduped)}/{len(df)} 行（超过{MAX_DROP_DUPLICATES_RATIO:.0%}），"
            "疑似字段组合误判重复，跳过该操作"
        )
        return df
    return deduped


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


def _execute_join_plan(df: pd.DataFrame, join_plan: dict, raw_data_path: str) -> pd.DataFrame:
    """按 confirmed_join_plan 依次执行 pd.merge()，合并多表。

    硬约束：merge 必须是固定 pd.merge() 调用，不能 eval/exec 任何 LLM 输出。
    """
    if not join_plan or not join_plan.get("joins"):
        return df

    # 从 raw_data_path 推导 session_dir
    session_dir_path = Path(raw_data_path).parent
    tables_dir = _tables_dir(session_dir_path)

    for join_entry in join_plan["joins"]:
        table_name = join_entry["table"]
        on = join_entry["on"]
        how = join_entry.get("how", "left")

        # 读取右表
        right_path = tables_dir / f"{table_name}.csv"
        if not right_path.exists():
            print(f"join: 右表文件不存在 {right_path}，跳过")
            continue

        try:
            right_df = pd.read_csv(right_path)
        except Exception as e:
            print(f"join: 读取右表 {table_name} 失败: {e}，跳过")
            continue

        left_col = on.get("left_col")
        right_col = on.get("right_col")

        if left_col not in df.columns:
            print(f"join: 左表缺少列 '{left_col}'，跳过 join {table_name}")
            continue
        if right_col not in right_df.columns:
            print(f"join: 右表 '{table_name}' 缺少列 '{right_col}'，跳过")
            continue

        # 固定 pd.merge() 调用，严禁 eval/exec
        df = pd.merge(df, right_df, left_on=left_col, right_on=right_col, how=how, suffixes=("", f"_{table_name}"))

    return df


def _apply_plan(df: pd.DataFrame, plan: list[dict]) -> pd.DataFrame:
    """按固定 op_* 函数集合依次执行 plan，单步失败跳过不中止（与原 run_transform 行为一致）。
    供 run_transform 与 node3_preview 的数据预览复用，避免执行逻辑出现第二处定义。"""
    for op in plan:
        try:
            df = OP_FUNCTIONS[op["op"]](df, op)
        except Exception as e:
            print(f"清洗操作 {op.get('op')} 执行失败，跳过: {e}")
    return df


def run_transform(
    raw_data_path: str,
    confirmed_schema: dict,
    cleaned_data_path: str,
    join_plan: dict | None = None,
    merged_data_path: str | None = None,
    final_plan: list[dict] | None = None,
) -> dict:
    """Node3：执行确定性清洗 plan，写入 cleaned_data_path（parquet）；
    若有 join_plan，则先执行 merge 再清洗，结果写入 merged_data_path。

    final_plan：Node3预览阶段用户确认（可能编辑过，如删除某条建议操作）的最终
    清洗计划。给定时直接按此执行，不再重新推导/调用LLM，确保"预览看到的"与
    "实际执行的"一致。
    """
    df = pd.read_csv(raw_data_path)

    # ---- 先执行 join（如果有） ----
    if join_plan and join_plan.get("joins"):
        df = _execute_join_plan(df, join_plan, raw_data_path)

    # ---- 清洗 ----
    if final_plan is not None:
        plan = _order_plan(final_plan)
        llm_available = True
    else:
        deterministic_ops = _build_deterministic_ops(confirmed_schema)
        llm_ops, llm_available = _llm_supplementary_ops(confirmed_schema, deterministic_ops)
        plan = _order_plan(deterministic_ops + llm_ops)

    df = _apply_plan(df, plan)

    # 写入 cleaned_data_path（始终写入，向后兼容）
    df.to_parquet(cleaned_data_path, index=False)

    # 若有 join，额外写入 merged_data_path
    if merged_data_path and join_plan and join_plan.get("joins"):
        df.to_parquet(merged_data_path, index=False)

    return {
        "plan": plan,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": [str(c) for c in df.columns],
        "llm_available": llm_available,
        "join_applied": bool(join_plan and join_plan.get("joins")),
    }
