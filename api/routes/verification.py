"""验证假设前的"推荐方法"接口：纯计算，不经过 LangGraph resume（同
api/routes/data_append.py 的设计取舍——这一步是即时性的，不需要跨断线恢复的状态），
session 可以处于 node_hypothesis_tree 的 interrupt 等待状态中的任意时刻。
"""

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.core.graph import graph, graph_config
from api.core.paths import cleaned_data_path, merged_data_path
from api.nodes.hypothesis_tree import recommend_verification

router = APIRouter()


class VerificationRecommendRequest(BaseModel):
    node_id: str


def _active_path(session_id: str, values: dict):
    """复用 api/routes/data_append.py 同样的判断：是否存在生效中的 join 方案。"""
    join_plan = values.get("confirmed_join_plan")
    if join_plan and join_plan.get("joins"):
        return merged_data_path(session_id)
    return cleaned_data_path(session_id)


@router.post("/api/analyze/{session_id}/verification/recommend")
async def verification_recommend(session_id: str, body: VerificationRecommendRequest) -> dict:
    """根据假设文本+当前数据列，推荐最合适的验证模块+列配置，并判断数据是否真的
    能支撑该假设（体验反馈#2/#3：取代此前用户瞎猜模块、LLM被迫从不相关列里强选的问题）。"""
    config = graph_config(session_id)
    values = graph.get_state(config).values
    if not values:
        raise HTTPException(status_code=404, detail="未找到该会话")

    tree = values.get("hypothesis_tree") or []
    hypothesis_node = next((n for n in tree if n.get("id") == body.node_id), None)
    if hypothesis_node is None:
        raise HTTPException(status_code=404, detail="未找到该假设节点")

    active_path = _active_path(session_id, values)
    if not active_path.exists():
        raise HTTPException(status_code=404, detail="当前会话尚无已清洗数据")
    df = pd.read_parquet(active_path)

    return recommend_verification(hypothesis_node, values.get("problem_card") or {}, df)
