import pandas as pd

from api.modules.base import BaseAnalysisModule
from api.modules._metrics import is_dimension_like

# 用户/实体ID列名关键词（不区分大小写）
ID_KEYWORDS = ["id", "user", "customer", "用户", "客户", "编号", "会员", "账号"]

# 分群数量对应的标签（从低到高）
SEGMENT_LABELS = {
    1: ["全部"],
    2: ["低", "高"],
    3: ["低", "中", "高"],
    4: ["低", "中低", "中高", "高"],
}


class SegmentationModule(BaseAnalysisModule):
    """用户/人群类分析：按数值指标将实体分群，输出各群体规模与贡献。"""

    name = "segmentation"
    category = "用户/人群"

    def validate(self, df: pd.DataFrame) -> bool:
        return self._find_id_column(df) is not None and len(self._numeric_columns(df)) > 0

    def run(self, df: pd.DataFrame, config: dict) -> dict:
        id_column = config.get("id_column") or self._find_id_column(df)
        value_column = config.get("value_column") or self._numeric_columns(df)[0]

        # value_column 若是按 id_column 重复但取值不变的维度属性（如 join 进来的用户静态属性，
        # 同一用户的多条事件行上重复出现同一个值），sum 会把它按该用户的行数虚假放大，
        # 应取 first（等价于该用户的真实值）；只有逐行变化的事件级指标才适合 sum 累加。
        agg = "first" if is_dimension_like(df, value_column, id_column) else "sum"
        entity_values = df.groupby(id_column)[value_column].agg(agg)
        # 部分实体可能完全没有该指标（如多表join后未匹配到对应行），无法参与分群，排除
        entity_values = entity_values.dropna()

        n_bins = min(4, entity_values.nunique())
        labels = SEGMENT_LABELS[n_bins]

        ranks = entity_values.rank(method="first")
        segment_idx = pd.qcut(ranks, q=n_bins, labels=False)

        segment_df = pd.DataFrame({"value": entity_values, "segment": segment_idx.map(lambda i: labels[i])})

        total_entities = len(segment_df)
        total_value = float(segment_df["value"].sum())

        segments = []
        for label in labels:
            group = segment_df[segment_df["segment"] == label]
            entity_count = len(group)
            value_sum = float(group["value"].sum())
            segments.append({
                "segment": label,
                "entity_count": entity_count,
                "entity_share_pct": round(entity_count / total_entities * 100, 2) if total_entities else 0.0,
                "value_sum": round(value_sum, 4),
                "value_share_pct": round(value_sum / total_value * 100, 2) if total_value else 0.0,
                "avg_value": round(value_sum / entity_count, 4) if entity_count else 0.0,
            })

        return {
            "id_column": id_column,
            "value_column": value_column,
            "total_entities": total_entities,
            "segments": segments,
        }

    def get_chart_spec(self, results: dict) -> dict:
        return {
            "title": {"text": f"{results['id_column']} 分群（按 {results['value_column']}）"},
            "tooltip": {"trigger": "item"},
            "series": [
                {
                    "name": "实体数量",
                    "type": "pie",
                    "radius": "60%",
                    "data": [
                        {"name": seg["segment"], "value": seg["entity_count"]}
                        for seg in results["segments"]
                    ],
                }
            ],
        }

    @staticmethod
    def _numeric_columns(df: pd.DataFrame) -> list[str]:
        return list(df.select_dtypes(include="number").columns)

    @staticmethod
    def _find_id_column(df: pd.DataFrame) -> str | None:
        for column in df.columns:
            name_lower = str(column).lower()
            if any(keyword in name_lower for keyword in ID_KEYWORDS):
                return column

        for column in df.columns:
            if pd.api.types.is_object_dtype(df[column]) or pd.api.types.is_integer_dtype(df[column]):
                nunique = df[column].nunique(dropna=True)
                if len(df) > 0 and nunique > 1 and nunique / len(df) > 0.5:
                    return column

        return None
