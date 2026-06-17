from abc import ABC, abstractmethod

import pandas as pd


class BaseAnalysisModule(ABC):
    """所有分析模块的统一接口（问题驱动，见 CLAUDE.md 约束1）。"""

    name: str
    category: str

    @abstractmethod
    def validate(self, df: pd.DataFrame) -> bool:
        """判断该模块是否可在当前数据上运行。"""

    @abstractmethod
    def run(self, df: pd.DataFrame, config: dict) -> dict:
        """执行分析，返回标准化结果（metrics + insight_data）。"""

    @abstractmethod
    def get_chart_spec(self, results: dict) -> dict:
        """将 run() 的结果转换为标准 ECharts option（见 CLAUDE.md 约束2）。"""
