"""Node3预览：清洗计划预览确认（PRD Step4，设计阶段实现，未接入 api/core/graph.py）。

在现有 node3_transform.run_transform() 之前插入：生成清洗 plan 但不执行，
等待用户确认后才由 node3_transform.run_transform() 执行（现有
api/nodes/node3_transform.py 不动）。

对应路由（实现见 api/routes/v03.py）：
  POST /api/analyze/{session_id}/transform/confirm  body: {"approved": true/false}
      -> approved=true 时，路由层调用 node3_transform.run_transform() 执行清洗；
      -> approved=false 时，本路由仅记录取消状态，提示用户重新提交 Node2 口径确认
         （具体UX待定）。

generate_transform_plan() 复用 node3_transform 中的确定性推导 + LLM补充 + 排序逻辑，
不重复实现 op_* 函数集合（CLAUDE.md 约束3：清洗操作的固定函数集合只在
node3_transform.py 中定义一处）。
"""
import hashlib
import json

import pandas as pd
from langgraph.types import interrupt

from api.nodes.node3_transform import (
    _apply_plan,
    _build_deterministic_ops,
    _execute_join_plan,
    _llm_supplementary_ops,
    _order_plan,
)

PREVIEW_SAMPLE_ROWS = 5

# 9种操作类型的人类可读描述模板，用于前端逐条展示「待执行操作」（docs/ARCHITECTURE.md 3.4节）
OP_DESCRIPTIONS = {
    "rename_column": lambda op: f"重命名列：{op['from']} -> {op['to']}",
    "drop_columns": lambda op: f"删除列：{', '.join(op['columns'])}",
    "cast_type": lambda op: f"类型转换：{op['column']} -> {op['to']}",
    "strip_whitespace": lambda op: f"去除首尾空格：{', '.join(op['columns'])}",
    "standardize_categories": lambda op: f"统一分类取值：{op['column']}（{op['mapping']}）",
    "unit_convert": lambda op: (
        f"单位换算：{op['column']} × {op['factor']}"
        + (f" -> {op['new_name']}" if op.get("new_name") else "")
    ),
    "fillna": lambda op: f"填充缺失值：{op['column']} -> {op['value']}",
    "drop_rows_with_null": lambda op: f"删除缺失值所在行：{', '.join(op['columns'])}",
    "drop_duplicates": lambda op: "删除重复行" + (f"（按 {op['subset']} 判定）" if op.get("subset") else "（整行完全一致）"),
}


def generate_transform_plan(confirmed_schema: dict) -> tuple[list[dict], bool]:
    """生成最终清洗 plan（确定性 + LLM补充，按 docs/ARCHITECTURE.md 3.3节排序），不执行。

    复用 node3_transform 中的内部函数，避免清洗操作枚举/排序逻辑出现第二处定义。
    """
    deterministic_ops = _build_deterministic_ops(confirmed_schema)
    llm_ops, llm_available = _llm_supplementary_ops(confirmed_schema, deterministic_ops)
    plan = _order_plan(deterministic_ops + llm_ops)
    return plan, llm_available


def schema_fingerprint(confirmed_schema: dict) -> str:
    """confirmed_schema 内容指纹，用于判断是否需要重新调用 LLM 生成清洗 plan。
    确认口径退回重新提交但内容未变时，复用上次 plan，避免 LLM 采样随机性导致
    "预览看到的"和"上次执行的"实际不一致（见 STATUS.md #3）。"""
    canonical = json.dumps(confirmed_schema, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_data_preview(raw_data_path: str, plan: list[dict], join_plan: dict | None = None) -> dict:
    """在真实数据上跑一遍 plan（写到内存，不落地最终 cleaned_data_path），
    给前端展示清洗前后的行列数对比与样例数据，而不只是操作文字描述。"""
    df = pd.read_csv(raw_data_path)
    if join_plan and join_plan.get("joins"):
        df = _execute_join_plan(df, join_plan, raw_data_path)
    before_rows, before_columns = len(df), len(df.columns)

    df_after = _apply_plan(df.copy(), plan)

    sample = df_after.head(PREVIEW_SAMPLE_ROWS).astype(object).where(pd.notnull(df_after.head(PREVIEW_SAMPLE_ROWS)), None)
    return {
        "before_rows": before_rows,
        "before_columns": before_columns,
        "after_rows": len(df_after),
        "after_columns": [str(c) for c in df_after.columns],
        "dtypes": {str(c): str(df_after[c].dtype) for c in df_after.columns},
        "sample_rows": sample.to_dict(orient="records"),
    }


def describe_plan(plan: list[dict]) -> list[dict]:
    """为每条操作附加人类可读描述，供前端逐条展示。"""
    described = []
    for op in plan:
        describe = OP_DESCRIPTIONS.get(op["op"])
        described.append({**op, "description": describe(op) if describe else op["op"]})
    return described


def run_preview(state: dict) -> dict:
    """生成 transform_plan 并写入 state，不执行清洗。

    输入 state 需包含：
      - user_confirmations: dict，即 Node2 产出的 confirmed_schema

    返回更新后的片段：
      - transform_plan: list[dict]，附人类可读描述的清洗操作列表
      - llm_available: bool
    """
    plan, llm_available = generate_transform_plan(state["user_confirmations"])
    return {
        "transform_plan": describe_plan(plan),
        "llm_available": llm_available,
    }


def node3_preview(state: dict) -> dict:
    """LangGraph 节点版本（设计阶段，graph.py 暂未接入）。

    接入方式（未来修改 graph.py 时）：
      node2_confirmation -> node3_preview --(interrupt，等待 /transform/confirm)--> node3_transform
    `interrupt()` 暂停流程，路由层推送 transform/interrupted 事件（携带
    transform_plan），用户提交 {"approved": true/false} 后用
    Command(resume=approved) 恢复；approved=false 的处理方式（重新进入Node2还是
    直接中止）留待接入时与前端交互一起确定。
    """
    plan, llm_available = generate_transform_plan(state["user_confirmations"])
    described = describe_plan(plan)
    approved = interrupt({"transform_plan": described})
    return {
        "current_node": "node3_preview",
        "transform_plan": described,
        "transform_approved": approved,
        "llm_available": llm_available,
    }
