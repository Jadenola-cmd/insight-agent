"""Step5 增量上传：假设验证阶段中途发现缺字段时，追加上传一个文件并合并进当前
session 的已清洗数据。preview/confirm 两步与 Node3 清洗计划、Node2 join 方案是
同一种交互模式，但本身不经过 LangGraph（不消费 node_hypothesis_tree 的
interrupt），只读写 cleaned_data_path/merged_data_path 指向的文件，session_id
对应会话可以处于 hypothesis_tree 循环中的任意时刻。
"""

import io
import uuid

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from api.core.graph import graph, graph_config
from api.core.paths import cleaned_data_path, merged_data_path, session_dir
from api.core.session_state import load_session_state, save_session_state
from api.nodes.data_append import execute_append, generate_append_plan

router = APIRouter()

APPEND_DIR_NAME = "appends"


def _active_path(session_id: str):
    """复用 graph.py `_data_path` 同样的判断：是否存在生效中的 join 方案。"""
    config = graph_config(session_id)
    values = graph.get_state(config).values
    join_plan = values.get("confirmed_join_plan") if values else None
    if join_plan and join_plan.get("joins"):
        return merged_data_path(session_id)
    return cleaned_data_path(session_id)


@router.post("/api/analyze/{session_id}/data/append/preview")
async def data_append_preview(session_id: str, file: UploadFile = File(...)) -> dict:
    """上传新文件，生成与现有数据的合并方案（不执行）。"""
    active_path = _active_path(session_id)
    if not active_path.exists():
        raise HTTPException(status_code=404, detail="当前会话尚无已清洗数据，无法追加")

    content = await file.read()
    try:
        new_df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败：{e}")

    appends_dir = session_dir(session_id) / APPEND_DIR_NAME
    appends_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    saved_path = appends_dir / f"{token}.csv"
    new_df.to_csv(saved_path, index=False)

    existing_df = pd.read_parquet(active_path)
    table_name = file.filename.rsplit(".", 1)[0] if file.filename and "." in file.filename else (file.filename or token)
    plan = generate_append_plan(list(existing_df.columns), new_df, table_name)

    session = load_session_state(session_id)
    session["pending_append"] = {"file_path": str(saved_path), "plan": plan}
    save_session_state(session_id, session)

    return {
        "token": token,
        "new_columns": [str(c) for c in new_df.columns],
        "existing_columns": [str(c) for c in existing_df.columns],
        "plan": plan,
    }


class AppendConfirmRequest(BaseModel):
    approved: bool
    plan: dict | None = None


@router.post("/api/analyze/{session_id}/data/append/confirm")
async def data_append_confirm(session_id: str, body: AppendConfirmRequest) -> dict:
    """确认（可能编辑过的）合并方案并执行，覆盖写回 cleaned_data_path/merged_data_path。"""
    session = load_session_state(session_id)
    pending = session.get("pending_append")
    if not pending:
        raise HTTPException(status_code=404, detail="未找到待确认的追加上传，请先调用 preview")

    if not body.approved:
        session.pop("pending_append", None)
        save_session_state(session_id, session)
        return {"status": "cancelled"}

    plan = body.plan or pending["plan"]
    active_path = _active_path(session_id)
    existing_df = pd.read_parquet(active_path)
    new_df = pd.read_csv(pending["file_path"])

    merged = execute_append(existing_df, new_df, plan)
    rows_before, rows_after = len(existing_df), len(merged)
    new_columns = [c for c in merged.columns if c not in existing_df.columns]

    # cleaned_data_path 与 merged_data_path 都可能是后续节点读取的路径
    # （取决于该 session 是否处于 join 生效状态），两者都同步覆盖以保持一致。
    merged.to_parquet(cleaned_data_path(session_id), index=False)
    if merged_data_path(session_id).exists():
        merged.to_parquet(merged_data_path(session_id), index=False)

    session.pop("pending_append", None)
    save_session_state(session_id, session)

    return {
        "status": "merged",
        "rows_before": rows_before,
        "rows_after": rows_after,
        "new_columns": new_columns,
    }
