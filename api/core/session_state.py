"""v0.3 新增字段（Node0/Node3预览/Node6）的会话级持久化（JSON 文件）。

api/core/graph.py 的 MemorySaver 只覆盖 Node1-5 主流程的 AnalysisState；
Node0/Node3预览/Node6 的路由（api/routes/v03.py）不经过 graph，
其新增字段（clarification_history/analysis_goal/transform_plan/
followup_history 等）单独存于
api/data/<session_id>/session_state.json，与 graph 的 checkpoint 互不影响。
"""
import json

from api.core.paths import session_dir


def _state_path(session_id: str):
    return session_dir(session_id) / "session_state.json"


def load_session_state(session_id: str) -> dict:
    """读取会话级 JSON 状态；不存在时返回空 dict。"""
    path = _state_path(session_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_session_state(session_id: str, data: dict) -> None:
    path = _state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
