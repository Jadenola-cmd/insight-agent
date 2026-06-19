from typing import Literal, Optional, TypedDict

from pydantic import BaseModel


class ColumnConfirmation(TypedDict):
    """用户对 Node1 诊断报告中单个字段的确认/修改结果。"""

    original_name: str
    final_name: str
    business_meaning: str
    include: bool
    missing_value_strategy: Literal["none", "fill", "drop_rows"]
    fill_value: str | float | None


class ConfirmedSchema(TypedDict):
    """Node2 提交、Node3 直接依赖的口径确认结果（state 内部类型）。"""

    columns: list[ColumnConfirmation]
    resolved_table_issues: list[str]


class ColumnConfirmationRequest(BaseModel):
    """`/api/analyze/{session_id}/confirm` 请求体中单个字段的确认结果。
    字段含义与 `ColumnConfirmation` 一一对应，供 FastAPI 做请求体校验。"""

    original_name: str
    final_name: str
    business_meaning: str
    include: bool
    missing_value_strategy: Literal["none", "fill", "drop_rows"] = "none"
    fill_value: Optional[str | float] = None


class ConfirmedSchemaRequest(BaseModel):
    """`/api/analyze/{session_id}/confirm` 请求体，对应 `ConfirmedSchema`。"""

    columns: list[ColumnConfirmationRequest]
    resolved_table_issues: list[str] = []


# ---- Join Plan 相关 ----

class JoinEntry(TypedDict):
    """单条 join 定义。"""

    table: str
    on: dict[str, str]  # {"left_col": "user_id", "right_col": "user_id"}
    how: Literal["left", "inner", "right", "outer"]
    purpose: str


class JoinPlan(TypedDict):
    """LLM 生成的 join 方案。"""

    primary_table: str
    joins: list[JoinEntry]


class JoinEntryRequest(BaseModel):
    """`/api/analyze/{session_id}/confirm/join` 请求体中单条 join。"""

    table: str
    on: dict[str, str]
    how: Literal["left", "inner", "right", "outer"] = "left"
    purpose: str = ""


class JoinPlanRequest(BaseModel):
    """`/api/analyze/{session_id}/confirm/join` 请求体。"""

    primary_table: str
    joins: list[JoinEntryRequest]


# ---- Minerva 假设树相关（PRD v1.0，2026-06-18 设计） ----

class ProblemCard(TypedDict):
    """阶段一（问题定义）输出，对应 PRD 第三节"问题陈述卡片"。"""

    question: str
    baseline: str
    business_meaning: str
    analysis_goal: str


HypothesisStatus = Literal["pending", "verifying", "verified", "rejected", "partial"]
# pending=待验证 verifying=验证中 verified=已验证(支持) rejected=已排除 partial=部分验证


class HypothesisNode(TypedDict):
    """假设树单个节点。group 是叙述性分组名（如"需求侧"），不是节点 id；
    根因分组节点 parent 为 None。"""

    id: str
    parent: str | None
    group: str
    label: str
    priority: bool
    status: HypothesisStatus
    verification_summary: str | None
    confidence_level: Literal["高", "中", "低"] | None


HypothesisTreeOpType = Literal[
    "add_node", "update_status", "update_summary", "merge_node", "remove_node"
]
# LLM 每轮只允许输出这组增量操作，禁止直接吐自由文本/整棵树重写，
# 由固定函数（待 Step2/3 实现）应用到已有 hypothesis_tree 上。


class HypothesisTreeOp(TypedDict):
    """假设树增量更新操作。各 op 类型只使用其相关字段，其余为 None：
    - add_node: node
    - update_status: node_id, status
    - update_summary: node_id, summary, confidence_level（可选，验证完成时一并写回置信度）
    - merge_node: merge_ids（被合并的源节点）, merged_node（合并后的新节点）
    - remove_node: node_id
    """

    op: HypothesisTreeOpType
    node: HypothesisNode | None
    node_id: str | None
    status: HypothesisStatus | None
    summary: str | None
    confidence_level: Literal["高", "中", "低"] | None
    merge_ids: list[str] | None
    merged_node: HypothesisNode | None
