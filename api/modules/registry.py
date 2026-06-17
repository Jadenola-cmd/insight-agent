import pandas as pd

from api.modules.attribution import AttributionModule
from api.modules.base import BaseAnalysisModule
from api.modules.comparison import ComparisonModule
from api.modules.prediction import PredictionModule
from api.modules.segmentation import SegmentationModule
from api.modules.trend import TrendInsightModule


class AnalysisRegistry:
    """管理所有已注册的分析模块，按数据自动判断可运行模块。"""

    def __init__(self) -> None:
        self._modules: list[BaseAnalysisModule] = []

    def register(self, module: BaseAnalysisModule) -> None:
        self._modules.append(module)

    def get_runnable_modules(self, df: pd.DataFrame) -> list[BaseAnalysisModule]:
        return [module for module in self._modules if module.validate(df)]

    def get_module(self, name: str) -> BaseAnalysisModule | None:
        """按 name 查找模块（Node6追问按LLM判断结果定位模块时使用）。"""
        for module in self._modules:
            if module.name == name:
                return module
        return None


def _build_default_registry() -> AnalysisRegistry:
    registry = AnalysisRegistry()
    for module in (
        TrendInsightModule(),
        ComparisonModule(),
        SegmentationModule(),
        AttributionModule(),
        PredictionModule(),
    ):
        registry.register(module)
    return registry


# 单例：Node4 主流程使用的默认注册表（PredictionModule 当前为空壳，validate 始终 False）
default_registry = _build_default_registry()
