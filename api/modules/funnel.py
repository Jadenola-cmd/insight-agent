import pandas as pd

from api.modules.base import BaseAnalysisModule
from api.modules._metrics import find_entity_key

# 阶段名 -> 候选列名关键词（按优先级从高到低，命中第一个就停）。
# 启发式识别，不依赖用户在口径确认界面手动标注（见DEBT.md历史决策）。
STAGE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("申请", ["apply_id", "apply"]),
    ("授信", ["credit_limit", "approv", "review_result", "credit"]),
    ("放款", ["loan_id", "loan_amount", "loan"]),
]


def _candidate_stage_columns(df: pd.DataFrame, keywords: list[str], used: set[str]) -> list[str]:
    """按关键词匹配出所有候选列（保留匹配顺序）。多表join时同名列会被加上
    表名后缀（如 credit_limit_dwd_credit_apply），不同表的同名字段语义可能
    完全不同（维度表的静态属性 vs 事实表的单次记录），不能只取第一个匹配就用，
    需要在run()里结合"漏斗必须单调递减"这条业务约束挑出语义正确的那一列。"""
    columns_lower = {str(c).lower(): c for c in df.columns}
    candidates = []
    for keyword in keywords:
        for lower_name, original_name in columns_lower.items():
            if keyword in lower_name and original_name not in used and original_name not in candidates:
                candidates.append(original_name)
    return candidates


class FunnelModule(BaseAnalysisModule):
    """转化/留存类分析：按实体（默认user_id）识别业务漏斗各阶段，输出阶段人数与转化率。

    阶段判定为启发式（按列名关键词+该列是否非空），不依赖用户在口径确认界面手动标注。
    """

    name = "funnel"
    category = "转化/留存"

    def _build_stages(self, df: pd.DataFrame) -> tuple[str | None, list[dict]]:
        entity_key = find_entity_key(df)
        if not entity_key:
            return None, []

        base_count = int(df[entity_key].nunique(dropna=True))
        stages = [{"name": "曝光", "column": entity_key, "count": base_count}]

        used_columns = {entity_key}
        for stage_name, keywords in STAGE_KEYWORDS:
            prev_count = stages[-1]["count"]
            candidates = _candidate_stage_columns(df, keywords, used_columns)
            if not candidates:
                continue

            # 漏斗阶段人数必须单调不超过上一阶段（业务约束：必须先完成上一步才能进入下一步）。
            # 多表join后同名字段会被加后缀区分（如 credit_limit 与 credit_limit_dwd_credit_apply），
            # 不同表的同名字段语义可能完全不同（事实表"单次记录" vs 维度表"静态属性"，后者几乎对
            # 所有人都非空，会算出超过上一阶段的人数），按上面约束在候选列里挑出语义正确的那一列；
            # 都不满足约束时，选人数最接近且不超标的，仍找不到就跳过该阶段，不展示矛盾的数字。
            best_column, best_count = None, None
            for column in candidates:
                used_columns.add(column)
                count = int(df.loc[df[column].notna(), entity_key].nunique(dropna=True))
                if count <= prev_count and (best_count is None or count > best_count):
                    best_column, best_count = column, count

            if best_column is None:
                continue
            stages.append({"name": stage_name, "column": best_column, "count": best_count})

        return entity_key, stages

    def validate(self, df: pd.DataFrame) -> bool:
        entity_key, stages = self._build_stages(df)
        return entity_key is not None and len(stages) >= 2

    def run(self, df: pd.DataFrame, config: dict) -> dict:
        entity_key, stages = self._build_stages(df)
        base_count = stages[0]["count"]

        for i, stage in enumerate(stages):
            stage["conversion_from_first_pct"] = (
                round(stage["count"] / base_count * 100, 2) if base_count else 0.0
            )
            if i == 0:
                stage["conversion_from_prev_pct"] = 100.0
            else:
                prev_count = stages[i - 1]["count"]
                stage["conversion_from_prev_pct"] = (
                    round(stage["count"] / prev_count * 100, 2) if prev_count else 0.0
                )

        return {
            "entity_key": entity_key,
            "stages": stages,
        }

    def get_chart_spec(self, results: dict) -> dict:
        return {
            "title": {"text": "转化漏斗"},
            "tooltip": {"trigger": "item", "formatter": "{b} : {c}"},
            "series": [
                {
                    "name": "转化人数",
                    "type": "funnel",
                    "left": "10%",
                    "width": "80%",
                    "label": {"show": True, "position": "inside"},
                    "data": [{"value": s["count"], "name": s["name"]} for s in results["stages"]],
                }
            ],
        }
