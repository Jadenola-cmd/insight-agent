import numpy as np
import pandas as pd

from api.modules.base import BaseAnalysisModule
from api.modules._metrics import select_numeric_metric


class TrendInsightModule(BaseAnalysisModule):
    """趋势/时序类分析：按时间聚合数值列，输出趋势走向与异常点。"""

    name = "trend_insight"
    category = "趋势/时序"

    def validate(self, df: pd.DataFrame) -> bool:
        return self._find_date_column(df) is not None and len(self._numeric_columns(df)) > 0

    def run(self, df: pd.DataFrame, config: dict) -> dict:
        date_column = config.get("date_column") or self._find_date_column(df)
        value_column, agg = select_numeric_metric(df, config.get("value_column"))

        series = df[[date_column, value_column]].dropna()
        series[date_column] = pd.to_datetime(series[date_column], errors="coerce")
        series = series.dropna(subset=[date_column]).sort_values(date_column)

        granularity = self._infer_granularity(series[date_column])
        period = series[date_column].dt.to_period(granularity)
        grouped = series.groupby(period)[value_column].agg(agg)

        periods = [str(p) for p in grouped.index]
        values = [round(float(v), 4) for v in grouped.to_numpy()]

        anomalies = self._detect_anomalies(periods, values)
        trend_direction, trend_change_pct = self._trend_summary(values)

        return {
            "date_column": date_column,
            "value_column": value_column,
            "agg": agg,
            "granularity": granularity,
            "periods": periods,
            "values": values,
            "trend_direction": trend_direction,
            "trend_change_pct": trend_change_pct,
            "anomalies": anomalies,
        }

    def get_chart_spec(self, results: dict) -> dict:
        anomaly_points = [
            {"name": "异常点", "coord": [a["period"], a["value"]]} for a in results["anomalies"]
        ]
        agg_label = "均值" if results.get("agg") == "mean" else "总量"
        return {
            "title": {"text": f"{results['value_column']} {agg_label}趋势（{results['granularity']}）"},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": results["periods"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "name": results["value_column"],
                    "type": "line",
                    "data": results["values"],
                    "markPoint": {"data": anomaly_points} if anomaly_points else {},
                }
            ],
        }

    @staticmethod
    def _numeric_columns(df: pd.DataFrame) -> list[str]:
        return list(df.select_dtypes(include="number").columns)

    @staticmethod
    def _find_date_column(df: pd.DataFrame) -> str | None:
        for column in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[column]):
                return column

        for column in df.select_dtypes(include="object").columns:
            sample = df[column].dropna()
            if sample.empty:
                continue
            parsed = pd.to_datetime(sample, errors="coerce")
            if parsed.notna().mean() >= 0.8:
                return column

        return None

    @staticmethod
    def _infer_granularity(dates: pd.Series) -> str:
        span_days = (dates.max() - dates.min()).days
        if span_days <= 60:
            return "D"
        if span_days <= 730:
            return "W"
        return "M"

    @staticmethod
    def _detect_anomalies(periods: list[str], values: list[float]) -> list[dict]:
        if len(values) < 3:
            return []

        arr = np.array(values)
        mean = arr.mean()
        std = arr.std()
        if std == 0:
            return []

        anomalies = []
        for period, value in zip(periods, values):
            z_score = (value - mean) / std
            if abs(z_score) > 2:
                anomalies.append({"period": period, "value": value, "z_score": round(float(z_score), 2)})
        return anomalies

    @staticmethod
    def _trend_summary(values: list[float]) -> tuple[str, float | None]:
        if len(values) < 2:
            return "数据不足", None

        first, last = values[0], values[-1]
        change_pct = round((last - first) / first * 100, 2) if first != 0 else None

        slope = np.polyfit(range(len(values)), values, 1)[0]
        if change_pct is not None and abs(change_pct) < 1:
            direction = "平稳"
        elif slope > 0:
            direction = "上升"
        elif slope < 0:
            direction = "下降"
        else:
            direction = "平稳"

        return direction, change_pct
