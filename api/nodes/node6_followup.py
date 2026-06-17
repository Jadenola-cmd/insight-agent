"""Node6：追问对话（PRD Step7，设计阶段实现，未接入 api/core/graph.py）。

报告生成后可被多次触发，每次追问视为一次独立调用，结果累积进 followup_history。

对应路由（实现见 api/routes/v03.py）：
  POST /api/analyze/{session_id}/followup  body: {"message": "..."}
      -> 调用 run_followup()；可回答时返回追加的报告片段 + 新 report_html，
         需要新数据时返回 data_request 提示用户需补传哪张表/字段。
  GET  /api/analyze/{session_id}/followup/stream  SSE推送
      -> 实现时将 run_followup() 的返回值包装为
         {"node": "node6_followup", "status": "done", "data": {...}} SSE事件。
"""
import json

import pandas as pd

from api.modules.registry import default_registry
from api.modules.visualization import VisualizationModule
from api.nodes.node5_report import _generate_narrative
from api.services.llm import chat_json


def _judge_followup(message: str, df_columns: list[str], analysis_results: dict) -> dict | None:
    """LLM判断追问能否基于现有数据回答，并指出对应分析模块。"""
    available_modules = [
        {"name": name, "category": entry["category"]} for name, entry in analysis_results.items()
    ]
    system_prompt = (
        "你是商业分析追问助手。判断用户的追问能否基于现有清洗后数据列与已运行的"
        "分析模块回答。严格按指定JSON格式输出，不要输出任何多余文字、不要使用"
        "Markdown代码块。"
    )
    user_prompt = f"""现有数据列：{json.dumps(df_columns, ensure_ascii=False)}
已运行的分析模块：{json.dumps(available_modules, ensure_ascii=False)}
用户追问：{message}

请输出以下JSON结构：
{{
  "answerable": true/false,
  "module": "若answerable=true，给出最匹配的模块name（取自已运行模块列表）",
  "reason": "简短说明判断依据",
  "data_request": "若answerable=false，说明需要补充哪张表/哪些字段"
}}
"""
    return chat_json(system_prompt, user_prompt)


def _render_followup_section(message: str, category: str, narrative: dict) -> str:
    """生成追加到 report_html 的「补充分析（追问）」片段，复用 report.html.j2 的样式class。"""
    return f"""
  <div class="module followup">
    <h2>追问：{message}</h2>
    <p style="color:#909399;font-size:9pt;">补充分析 · {category}</p>
    <div class="narrative">
      <p><span class="label">结论：</span>{narrative['conclusion']}</p>
      <p><span class="label">数据支撑：</span>{narrative['data_support']}</p>
      <p><span class="label">运营建议：</span>{narrative['recommendation']}</p>
    </div>
  </div>
"""


def run_followup(state: dict) -> dict:
    """处理一次追问对话。

    输入 state 需包含：
      - followup_message: str
      - cleaned_data_path: str
      - analysis_results: dict，Node4 输出（{module_name: {category, metrics}}）
      - report_html: str，当前报告HTML（可回答时在末尾追加新章节）
      - followup_history: list

    返回更新后的片段：
      - followup_history: 追加本轮记录 {message, answerable, ...}
      - report_html: 可回答时为追加后的新HTML；不可回答时原样返回
      - needs_more_data: bool
      - data_request: str（needs_more_data=true 时）
    """
    message = state["followup_message"]
    analysis_results = state.get("analysis_results", {})
    report_html = state.get("report_html", "")
    history = state.get("followup_history", [])

    df = pd.read_parquet(state["cleaned_data_path"])
    judgement = _judge_followup(message, [str(c) for c in df.columns], analysis_results)

    if not judgement or not judgement.get("answerable"):
        data_request = (
            judgement.get("data_request") if judgement else None
        ) or "现有数据无法回答该问题，请补充相关数据表或换一种问法。"
        history = history + [{"message": message, "answerable": False, "data_request": data_request}]
        return {
            "followup_history": history,
            "report_html": report_html,
            "needs_more_data": True,
            "data_request": data_request,
        }

    module_name = judgement.get("module")
    module = default_registry.get_module(module_name)
    if module is None or not module.validate(df):
        data_request = "未找到匹配的分析模块，请补充说明你想了解的具体指标。"
        history = history + [{"message": message, "answerable": False, "data_request": data_request}]
        return {
            "followup_history": history,
            "report_html": report_html,
            "needs_more_data": True,
            "data_request": data_request,
        }

    metrics = module.run(df, {})
    chart_spec = VisualizationModule().transform(module.get_chart_spec(metrics))
    narrative, _llm_available = _generate_narrative(module.category, metrics)

    section_html = _render_followup_section(message, module.category, narrative)
    if "</body>" in report_html:
        new_report_html = report_html.replace("</body>", section_html + "</body>")
    else:
        new_report_html = report_html + section_html

    history = history + [
        {
            "message": message,
            "answerable": True,
            "module": module_name,
            "narrative": narrative,
            "chart_spec": chart_spec,
        }
    ]

    return {
        "followup_history": history,
        "report_html": new_report_html,
        "needs_more_data": False,
    }
