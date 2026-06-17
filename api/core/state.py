from typing import TypedDict


class AnalysisState(TypedDict):
    """LangGraph 状态：控制流与数据流分离。
    数据流字段只存文件路径，禁止存放 DataFrame（见 CLAUDE.md 约束4）。"""

    # 控制流
    current_node: str
    analysis_type: str
    user_confirmations: dict
    session_id: str

    # 数据流（路径引用）
    raw_data_path: str
    cleaned_data_path: str
    merged_data_path: str
    report_path: str
    analysis_results: dict
    charts_data: dict
    report_html: str

    # v0.3 新增（PRD Step0/Step4/Step7，详见 docs/ARCHITECTURE.md）
    analysis_goal: str
    transform_plan: list
    transform_approved: bool
    followup_history: list
    followup_done: bool

    # Join 方案确认（Node2 第二阶段中断）
    proposed_join_plan: dict | None
    confirmed_join_plan: dict | None
