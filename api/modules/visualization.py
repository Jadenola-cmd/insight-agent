# chart_spec -> ECharts option 的轻量转换层（CLAUDE.md 约束5：不引入分析逻辑，不修改 series 数据）

DEFAULT_COLORS = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272"]


class VisualizationModule:
    """对分析模块输出的 chart_spec 做默认值补全，统一前端/PDF渲染风格。"""

    def transform(self, chart_spec: dict) -> dict:
        option = dict(chart_spec)
        option.setdefault("color", DEFAULT_COLORS)
        option.setdefault("tooltip", {"trigger": "axis"})
        option.setdefault("legend", {})
        return option
