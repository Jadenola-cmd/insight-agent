import pandas as pd
import statsmodels.api as sm

from api.modules.base import BaseAnalysisModule

# 自变量数量上限，避免OLS引入过多噪声列
MAX_INDEPENDENT_COLUMNS = 5


class AttributionModule(BaseAnalysisModule):
    """贡献/驱动因素类分析：用标准化OLS回归系数估计各自变量对因变量的贡献占比。

    预留接口：未来可复用 empirical-agent 的 OLS/DID 基础设施替换此处的简化实现。
    """

    name = "attribution"
    category = "贡献/驱动因素"

    def validate(self, df: pd.DataFrame) -> bool:
        numeric_columns = self._numeric_columns(df)
        return len(numeric_columns) >= 2 and len(df) >= 3

    def run(self, df: pd.DataFrame, config: dict) -> dict:
        numeric_columns = self._numeric_columns(df)
        dependent_column = config.get("dependent_column") or numeric_columns[0]
        independent_columns = config.get("independent_columns") or [
            c for c in numeric_columns if c != dependent_column
        ]
        independent_columns = independent_columns[:MAX_INDEPENDENT_COLUMNS]

        data = df[[dependent_column] + independent_columns].dropna()

        # 标准化（z-score）后系数才能跨变量比较贡献大小
        std = data.std()
        independent_columns = [c for c in independent_columns if std[c] > 0]
        if std[dependent_column] == 0 or not independent_columns:
            return {
                "dependent_column": dependent_column,
                "independent_columns": independent_columns,
                "r_squared": 0.0,
                "factors": [],
            }

        standardized = (data - data.mean()) / std
        y = standardized[dependent_column]
        x = sm.add_constant(standardized[independent_columns])

        model = sm.OLS(y, x).fit()
        coefficients = model.params.drop("const")

        abs_coefs = coefficients.abs()
        total = abs_coefs.sum()
        contributions = (abs_coefs / total * 100) if total != 0 else abs_coefs * 0

        factors = sorted(
            (
                {
                    "variable": col,
                    "coefficient": round(float(coefficients[col]), 4),
                    "contribution_pct": round(float(contributions[col]), 2),
                }
                for col in independent_columns
            ),
            key=lambda item: item["contribution_pct"],
            reverse=True,
        )

        return {
            "dependent_column": dependent_column,
            "independent_columns": independent_columns,
            "r_squared": round(float(model.rsquared), 4),
            "factors": factors,
        }

    def get_chart_spec(self, results: dict) -> dict:
        return {
            "title": {"text": f"{results['dependent_column']} 的驱动因素贡献占比"},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [f["variable"] for f in results["factors"]]},
            "yAxis": {"type": "value", "name": "贡献占比(%)"},
            "series": [
                {
                    "name": "贡献占比",
                    "type": "bar",
                    "data": [f["contribution_pct"] for f in results["factors"]],
                }
            ],
        }

    @staticmethod
    def _numeric_columns(df: pd.DataFrame) -> list[str]:
        return list(df.select_dtypes(include="number").columns)
