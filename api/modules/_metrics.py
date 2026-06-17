import pandas as pd

# 实体主键候选列名：多表 join 后，这些列上 groupby 才能判断某数值列是否为
# "维度静态属性"（如 credit_score 来自用户画像表，join 后在同一用户的多条
# 事件行上被重复写入，sum 聚合会把它按事件行数虚假放大，而不是反映真实业务量）。
ENTITY_KEY_CANDIDATES = ["user_id", "apply_id", "loan_id"]


def find_entity_key(df: pd.DataFrame) -> str | None:
    for c in ENTITY_KEY_CANDIDATES:
        if c in df.columns:
            return c
    return None


def is_dimension_like(df: pd.DataFrame, column: str, entity_key: str | None, sample_size: int = 5000) -> bool:
    """判断 column 是否是"按 entity_key 重复但取值不变"的维度属性列（而非逐行变化的事件级指标）。"""
    if not entity_key or entity_key == column or entity_key not in df.columns:
        return False
    sample = df[[entity_key, column]].dropna()
    if sample.empty:
        return False
    if len(sample) > sample_size:
        sample = sample.sample(sample_size, random_state=0)

    group_sizes = sample.groupby(entity_key).size()
    multi_row_keys = group_sizes[group_sizes > 1].index
    if len(multi_row_keys) == 0:
        return False

    nunique_within = sample[sample[entity_key].isin(multi_row_keys)].groupby(entity_key)[column].nunique()
    return (nunique_within <= 1).mean() >= 0.95


def select_numeric_metric(df: pd.DataFrame, configured_column: str | None = None) -> tuple[str | None, str]:
    """返回 (value_column, default_agg)。

    维度静态属性列（如 join 进来的用户属性）用 sum 聚合没有业务意义（会随重复行数虚假放大），
    优先选择逐行变化的事件级数值列并用 sum；若只有维度类列可用，则改用 mean，避免产出
    "总额"语义但实际是重复计数放大的错误结论。
    """
    numeric_columns = list(df.select_dtypes(include="number").columns)
    if not numeric_columns:
        return None, "sum"

    entity_key = find_entity_key(df)

    if configured_column:
        agg = "mean" if is_dimension_like(df, configured_column, entity_key) else "sum"
        return configured_column, agg

    event_level = [c for c in numeric_columns if not is_dimension_like(df, c, entity_key)]
    if event_level:
        return event_level[0], "sum"
    return numeric_columns[0], "mean"
