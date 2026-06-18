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
    transform_preview_action: str
    followup_history: list
    followup_done: bool

    # Join 方案确认（Node2 第二阶段中断）
    proposed_join_plan: dict | None
    confirmed_join_plan: dict | None

    # Minerva 假设驱动对话重构（PRD v1.0，2026-06-18 设计，详见 STATUS.md）
    # 具体结构见 api/core/schema.py 的 ProblemCard / HypothesisNode / HypothesisTreeOp，
    # state 中仍按 CLAUDE.md 约定存 dict/list（与 transform_plan 等现有字段风格一致）。
    stage: str  # "" (旧版直入) | "problem_definition" | "awaiting_data" | "hypothesis_tree" | "verification" | "conclusion"
    problem_card: dict | None
    hypothesis_tree: list[dict]
    clarification_history: list  # node0_clarification 自循环时累积的对话记录
    clarification_round: int
    verifying_node_id: str | None  # node_hypothesis_tree -> node_verification 传递目标假设id
    verifying_module: str | None   # 用户/前端指定的验证用分析模块名（registry.get_module）
