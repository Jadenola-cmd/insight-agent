import json
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from api.services.llm import chat_json

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# 置信度等级排序：用于三维度取最低值（见 docs/ARCHITECTURE.md 5.1节）
LEVEL_RANK = {"高": 2, "中": 1, "低": 0}

# 分析方法维度：各模块类别对应的固定等级
METHOD_LEVELS = {
    "趋势/时序": "高",
    "对比/分组": "高",
    "用户/人群": "高",
    "贡献/驱动因素": "中",
    "预测": "低",
}

# 每个模块结果中，"相关字段"对应的列名取值方式（用于计算空值率）
MODULE_RELEVANT_COLUMNS = {
    "trend_insight": lambda m: [m["date_column"], m["value_column"]],
    "comparison": lambda m: [m["category_column"], m["value_column"]],
    "segmentation": lambda m: [m["id_column"], m["value_column"]],
    "attribution": lambda m: [m["dependent_column"], *m["independent_columns"]],
}


def _sample_size_level(row_count: int) -> str:
    if row_count > 1000:
        return "高"
    if row_count >= 200:
        return "中"
    return "低"


def _null_rate_level(rate: float) -> str:
    if rate < 0.05:
        return "高"
    if rate <= 0.20:
        return "中"
    return "低"


def _compute_confidence(df: pd.DataFrame, module_name: str, category: str, metrics: dict) -> dict:
    """三维度（样本量/相关字段空值率/分析方法）取最低值，规则写死不经过LLM，原因对用户可见。"""
    sample_level = _sample_size_level(len(df))
    sample_reason = f"样本量 {len(df)} 行（{sample_level}）"

    column_getter = MODULE_RELEVANT_COLUMNS.get(module_name)
    columns = [c for c in column_getter(metrics) if c in df.columns] if column_getter else []
    null_rate = float(df[columns].isna().mean().mean()) if columns else 0.0
    null_level = _null_rate_level(null_rate)
    null_reason = f"相关字段平均空值率 {null_rate * 100:.1f}%（{null_level}）"

    method_level = METHOD_LEVELS.get(category, "中")
    method_reason = f"分析方法：{category}（{method_level}）"

    level = min((sample_level, null_level, method_level), key=lambda l: LEVEL_RANK[l])
    return {"level": level, "reasons": [sample_reason, null_reason, method_reason]}


def _fallback_narrative(category: str, metrics: dict) -> dict:
    return {
        "conclusion": f"{category}模块分析已完成，关键结果见图表（AI解读暂不可用）。",
        "data_support": json.dumps(metrics, ensure_ascii=False),
        "recommendation": "AI解读暂不可用，请结合图表与原始数据进行人工解读。",
    }


def _generate_narrative(category: str, metrics: dict) -> tuple[dict, bool]:
    """调用LLM生成"结论-数据支撑-运营建议"三段式文字；不可用时降级但不阻断流程。"""
    system_prompt = (
        "你是商业分析报告撰写助手。根据给定分析模块的结果数据，生成"
        "“结论-数据支撑-运营建议”三段式文字，严格按JSON格式输出，不要输出任何多余文字、"
        "不要使用Markdown代码块。"
        "结论：一句话给出本模块最重要的发现；"
        "数据支撑：引用结果中的具体数字说明结论依据；"
        "运营建议：基于结论给出可执行的运营建议。"
    )
    user_prompt = f"""分析模块类别：{category}
分析结果（JSON）：{json.dumps(metrics, ensure_ascii=False)}

请输出以下JSON结构：
{{"conclusion": "...", "data_support": "...", "recommendation": "..."}}
"""
    result = chat_json(system_prompt, user_prompt)
    if not result or not all(k in result for k in ("conclusion", "data_support", "recommendation")):
        return _fallback_narrative(category, metrics), result is not None

    return result, True


def run_report(cleaned_data_path: str, analysis_results: dict, charts_data: dict, report_path: str) -> dict:
    """Node5：为每个分析模块生成三段式洞察+置信度，组装报告HTML并转换为PDF。"""
    df = pd.read_parquet(cleaned_data_path)

    modules = []
    llm_available = False
    for module_name, entry in analysis_results.get("analysis", {}).items():
        category = entry["category"]
        metrics = entry["metrics"]

        narrative, module_llm_available = _generate_narrative(category, metrics)
        llm_available = llm_available or module_llm_available
        confidence = _compute_confidence(df, module_name, category, metrics)

        modules.append({
            "name": module_name,
            "category": category,
            "narrative": narrative,
            "confidence": confidence,
            "chart_spec": charts_data.get(module_name),
        })

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html"]))
    template = env.get_template("report.html.j2")
    report_html = template.render(modules=modules)

    # 报告改为 HTML 直接展示（GET /api/report/{session_id}/html），PDF生成暂停用，见 DEBT.md
    # pdf_generated = _write_pdf(report_html, report_path)
    pdf_generated = False

    return {
        "report_html": report_html,
        "modules": [
            {
                "name": m["name"],
                "category": m["category"],
                "confidence": m["confidence"],
                "narrative": m["narrative"],
            }
            for m in modules
        ],
        "llm_available": llm_available,
        "pdf_generated": pdf_generated,
    }


# def _write_pdf(report_html: str, report_path: str) -> bool:
#     """WeasyPrint 依赖系统级 Pango/Cairo/GDK-Pixbuf（见 DEBT.md），未安装时延迟到此处才报错，
#     不阻断 report_html 的生成；失败时返回 False，PDF 文件不会写入。"""
#     try:
#         from weasyprint import HTML
#     except OSError:
#         return False
#
#     HTML(string=report_html).write_pdf(report_path)
#     return True
