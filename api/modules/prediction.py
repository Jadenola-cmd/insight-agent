import pandas as pd

from api.modules.base import BaseAnalysisModule


class PredictionModule(BaseAnalysisModule):
    """预测类分析：后期扩展，当前为空壳，validate 始终返回 False。"""

    name = "prediction"
    category = "预测"

    def validate(self, df: pd.DataFrame) -> bool:
        return False

    def run(self, df: pd.DataFrame, config: dict) -> dict:
        raise NotImplementedError

    def get_chart_spec(self, results: dict) -> dict:
        raise NotImplementedError
