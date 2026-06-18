import io
import uuid
from typing import List

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.core.paths import raw_data_path, session_dir

router = APIRouter()

TABLES_DIR = "tables"


@router.post("/api/upload")
async def upload_file(
    files: List[UploadFile] = File(...),
    analysis_goal: str = Form(""),
    session_id: str = Form(""),
) -> dict:
    """session_id 留空时按旧版行为新建会话；Minerva 流程在阶段一问题定义阶段
    已用 node0_clarification 的 interrupt 占住某个 session_id（见 graph.py），
    此时上传需传入该 session_id，复用同一份 raw.csv 落点，不能再新建。"""
    if not files:
        raise HTTPException(status_code=400, detail="至少上传一个文件")

    session_id = session_id or uuid.uuid4().hex
    session_dir(session_id).mkdir(parents=True, exist_ok=True)

    # 保存每个文件到 tables/ 子目录（供 join 方案使用）
    tables_dir = session_dir(session_id) / TABLES_DIR
    tables_dir.mkdir(parents=True, exist_ok=True)

    dfs = []
    for f in files:
        content = await f.read()
        try:
            df = pd.read_csv(io.BytesIO(content))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"文件 {f.filename} 解析失败：{e}")
        dfs.append(df)
        # 单独保存每个文件
        stem = f.filename.rsplit(".", 1)[0] if "." in f.filename else f.filename
        df.to_csv(tables_dir / f"{stem}.csv", index=False)

    # 多文件场景：列名完全一致时视为同口径多文件（如分月导出），纵向合并；
    # 列名不一致时视为多张不同结构的表（事实表/维度表，供 Node2 Join 方案使用），
    # 此时 Node1/Node2 的字段口径诊断只针对行数最多的表（通常是主事实表），
    # 不能对所有表的列名做 pd.concat，否则绝大多数列会因表间错位产生虚假高空值率。
    if len(dfs) > 1 and all(list(df.columns) == list(dfs[0].columns) for df in dfs):
        merged = pd.concat(dfs, axis=0, ignore_index=True)
    elif len(dfs) > 1:
        merged = max(dfs, key=len)
    else:
        merged = dfs[0]
    merged.to_csv(raw_data_path(session_id), index=False)

    if analysis_goal:
        from api.core.session_state import save_session_state
        save_session_state(session_id, {"analysis_goal": analysis_goal})

    return {"session_id": session_id, "file_count": len(dfs), "row_count": len(merged)}
