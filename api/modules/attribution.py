import pandas as pd
import statsmodels.api as sm

from api.modules.base import BaseAnalysisModule

# 自变量数量上限，避免OLS引入过多噪声列
MAX_INDEPENDENT_COLUMNS = 5
# 分类自变量one-hot展开前的取值数上限，避免高基数列（如user_id）炸出大量哑变量
MAX_CATEGORY_LEVELS = 15


class AttributionModule(BaseAnalysisModule):
    """贡献/驱动因素类分析：用标准化OLS回归系数估计各自变量对因变量的贡献占比。

    LLM推荐的config里dependent_column/independent_columns未必是数值列（如渠道、
    风险分层、放款结果这类分类字段，业务上是合理的归因对象），run()内部对非数值列
    做二元编码/one-hot展开而不是假设全表已是数值，避免500（详见DEBT.md）。

    预留接口：未来可复用 empirical-agent 的 OLS/DID 基础设施替换此处的简化实现。
    """

    name = "attribution"
    category = "贡献/驱动因素"

    def validate(self, df: pd.DataFrame) -> bool:
        numeric_columns = self._numeric_columns(df)
        return len(numeric_columns) >= 2 and len(df) >= 3

    def run(self, df: pd.DataFrame, config: dict) -> dict:
        numeric_columns = self._numeric_columns(df)
        requested_dependent = config.get("dependent_column") or numeric_columns[0]
        requested_independent = (
            config.get("independent_columns")
            or [c for c in numeric_columns if c != requested_dependent]
        )
        requested_independent = [c for c in requested_independent if c != requested_dependent][
            :MAX_INDEPENDENT_COLUMNS
        ]

        working = df[[requested_dependent] + requested_independent].dropna().copy()

        dependent_column = requested_dependent
        if dependent_column not in numeric_columns:
            encoded = self._binary_encode(working[dependent_column])
            if encoded is None:
                # 因变量不是数值也不是二元分类（如>2个取值），无法合理编码，
                # 退回全表第一个数值列作因变量，保证至少能跑出一个结果而不是直接报错
                return self.run(
                    df,
                    {
                        "dependent_column": numeric_columns[0],
                        "independent_columns": [c for c in numeric_columns if c != numeric_columns[0]],
                    },
                )
            working[dependent_column] = encoded

        independent_columns = [c for c in requested_independent if c != dependent_column]
        categorical_columns = [
            c
            for c in independent_columns
            if c not in numeric_columns and working[c].nunique() <= MAX_CATEGORY_LEVELS
        ]
        numeric_independent = [c for c in independent_columns if c in numeric_columns]

        if categorical_columns:
            dummies = pd.get_dummies(working[categorical_columns].astype(str), drop_first=True).astype(int)
            working = pd.concat([working.drop(columns=categorical_columns), dummies], axis=1)
            independent_columns = numeric_independent + list(dummies.columns)
        else:
            independent_columns = numeric_independent

        data = working[[dependent_column] + independent_columns]

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

    @staticmethod
    def _binary_encode(series: pd.Series) -> pd.Series | None:
        """非数值列恰好只有2个取值时（如success/fail、true/false）映射为0/1，
        否则返回None交给调用方降级处理。"""
        levels = sorted(series.dropna().unique().tolist(), key=str)
        if len(levels) != 2:
            return None
        mapping = {levels[0]: 0, levels[1]: 1}
        return series.map(mapping)
