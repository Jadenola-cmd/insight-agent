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
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="至少上传一个文件")

    session_id = uuid.uuid4().hex
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

    # 多文件按列名纵向合并，存为 raw.csv（向后兼容单表分析流程）
    merged = pd.concat(dfs, axis=0, ignore_index=True) if len(dfs) > 1 else dfs[0]
    merged.to_csv(raw_data_path(session_id), index=False)

    if analysis_goal:
        from api.core.session_state import save_session_state
        save_session_state(session_id, {"analysis_goal": analysis_goal})

    return {"session_id": session_id, "file_count": len(dfs), "row_count": len(merged)}
