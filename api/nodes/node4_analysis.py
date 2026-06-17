import pandas as pd

from api.modules.registry import default_registry
from api.modules.visualization import VisualizationModule


def run_analysis(cleaned_data_path: str) -> dict:
    """Node4：对清洗后数据运行所有可用分析模块，并转换图表配置。"""
    df = pd.read_parquet(cleaned_data_path)

    visualization = VisualizationModule()
    results: dict = {}
    charts: dict = {}

    for module in default_registry.get_runnable_modules(df):
        try:
            metrics = module.run(df, {})
            results[module.name] = {"category": module.category, "metrics": metrics}
            charts[module.name] = visualization.transform(module.get_chart_spec(metrics))
        except Exception as exc:
            results[module.name] = {"category": module.category, "error": str(exc), "metrics": {}}
            charts[module.name] = {}

    return {"results": results, "charts": charts}
