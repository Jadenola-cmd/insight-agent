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
