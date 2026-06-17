import pandas as pd

from api.modules.base import BaseAnalysisModule
from api.modules._metrics import select_numeric_metric

# 分类列的唯一值数量范围：太少没有对比意义，太多更像ID列
MIN_CATEGORIES = 2
MAX_CATEGORIES = 50


class ComparisonModule(BaseAnalysisModule):
    """对比/分组类分析：按分类列聚合数值列，输出排序后的对比结果（TOP/BOTTOM）。"""

    name = "comparison"
    category = "对比/分组"

    def validate(self, df: pd.DataFrame) -> bool:
        return self._find_category_column(df) is not None and len(self._numeric_columns(df)) > 0

    def run(self, df: pd.DataFrame, config: dict) -> dict:
        category_column = config.get("category_column") or self._find_category_column(df)
        default_value_column, default_agg = select_numeric_metric(df, config.get("value_column"))
        value_column = default_value_column
        agg = config.get("agg") or default_agg

        grouped = df.groupby(category_column)[value_column].agg(agg).sort_values(ascending=False)
        total = float(grouped.sum())

        categories = [str(c) for c in grouped.index]
        values = [round(float(v), 4) for v in grouped.to_numpy()]
        shares = [round(v / total * 100, 2) if total != 0 else 0.0 for v in values]

        top_n = min(5, len(categories))
        top = [
            {"category": categories[i], "value": values[i], "share_pct": shares[i]}
            for i in range(top_n)
        ]
        bottom_n = min(3, len(categories))
        bottom = [
            {"category": categories[-i - 1], "value": values[-i - 1], "share_pct": shares[-i - 1]}
            for i in range(bottom_n)
        ] if len(categories) > top_n else []

        return {
            "category_column": category_column,
            "value_column": value_column,
            "agg": agg,
            "categories": categories,
            "values": values,
            "shares": shares,
            "total": round(total, 4),
            "top": top,
            "bottom": bottom,
        }

    def get_chart_spec(self, results: dict) -> dict:
        return {
            "title": {"text": f"{results['category_column']} 各分组 {results['value_column']} 对比（{results['agg']}）"},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": results["categories"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "name": results["value_column"],
                    "type": "bar",
                    "data": results["values"],
                }
            ],
        }

    @staticmethod
    def _numeric_columns(df: pd.DataFrame) -> list[str]:
        return list(df.select_dtypes(include="number").columns)

    @staticmethod
    def _find_category_column(df: pd.DataFrame) -> str | None:
        for column in df.select_dtypes(include=["object", "category", "string"]).columns:
            unique_count = df[column].nunique(dropna=True)
            if MIN_CATEGORIES <= unique_count <= MAX_CATEGORIES:
                return column
        return None
