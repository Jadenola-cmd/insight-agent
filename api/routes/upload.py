import io
import uuid
from typing import List

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.core.paths import raw_data_path, session_dir
from api.core.session_state import save_session_state

router = APIRouter()


@router.post("/api/upload")
async def upload_file(
    files: List[UploadFile] = File(...),
    analysis_goal: str = Form(""),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="至少上传一个文件")

    session_id = uuid.uuid4().hex
    session_dir(session_id).mkdir(parents=True, exist_ok=True)

    dfs = []
    for f in files:
        content = await f.read()
        try:
            df = pd.read_csv(io.BytesIO(content))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"文件 {f.filename} 解析失败：{e}")
        dfs.append(df)

    # 多文件按列名纵向合并（列不同时用 NaN 填充）
    merged = pd.concat(dfs, axis=0, ignore_index=True) if len(dfs) > 1 else dfs[0]
    merged.to_csv(raw_data_path(session_id), index=False)

    if analysis_goal:
        save_session_state(session_id, {"analysis_goal": analysis_goal})

    return {"session_id": session_id, "file_count": len(dfs), "row_count": len(merged)}
