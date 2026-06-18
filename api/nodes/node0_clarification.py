"""Node0：对话式问题澄清（PRD Step0，设计阶段实现，未接入 api/core/graph.py）。

流程入口，在用户上传数据之前执行：用户用文字描述初步分析需求，LLM 以追问形式
最多对话 3 轮，收敛为一段描述完整的 analysis_goal（业务问题/决策背景/所需数据/
预计分析模块）。

对应路由（实现见 api/routes/v03.py）：
  POST /api/clarify/{session_id}/message  body: {"message": "..."}
      -> 调用 run_clarification()，推进一轮对话；
         返回 {"clarification_history", "round", "analysis_goal", "done"}；
         done=true 时前端结束澄清、进入上传环节。
  GET  /api/clarify/{session_id}/stream   SSE 推送澄清对话过程
      -> 实现时将 run_clarification() 的返回值包装为
         {"node": "node0_clarification", "status": "done", "data": {...}} SSE事件。
"""
import json
from pathlib import Path

import pandas as pd

from api.services.llm import chat_json

MAX_ROUNDS = 3


def _read_table_summaries(raw_data_paths: list[str]) -> list[dict]:
    """读取已上传表的字段摘要（列名/类型/样例值），供 LLM 在澄清对话中参考。

    澄清通常发生在上传之前，raw_data_paths 为空列表时返回空摘要，
    LLM 仅基于用户的文字描述对话。
    """
    summaries = []
    for path_str in raw_data_paths:
        path = Path(path_str)
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, nrows=20)
        except Exception:
            continue
        summaries.append({
            "table": path.name,
            "columns": [
                {
                    "name": str(col),
                    "dtype": str(df[col].dtype),
                    "sample_values": [str(v) for v in df[col].dropna().unique()[:3]],
                }
                for col in df.columns
            ],
        })
    return summaries


def run_clarification(state: dict) -> dict:
    """执行一轮问题澄清对话，最多 3 轮（第3轮强制收敛输出 analysis_goal）。

    输入 state 需包含：
      - user_message: str，本轮用户输入
      - clarification_history: list[dict]，既有对话记录
        （[{"role": "user"/"assistant", "content": "..."}]）
      - round: int，已完成的轮数（首次调用为0）
      - raw_data_paths: list[str]，可选，用户已上传表的路径

    返回更新后的片段：
      - clarification_history: 追加本轮 user+assistant 消息
      - round: 本轮轮数
      - analysis_goal: 收敛后的分析目标字符串；未收敛时为 ""
      - done: bool，是否已产出 analysis_goal（True 时前端应停止追问，进入上传环节）
    """
    history = state.get("clarification_history", [])
    round_no = state.get("round", 0) + 1
    user_message = state["user_message"]
    table_summaries = _read_table_summaries(state.get("raw_data_paths", []))

    force_conclude = round_no >= MAX_ROUNDS

    system_prompt = (
        "你是商业分析需求澄清助手。通过最多3轮对话，把用户模糊的分析需求收敛为"
        "明确的分析目标（analysis_goal）。追问聚焦三个方向：①基准问题（这个指标"
        "正常水位是多少）②定义问题（这个指标背后代表什么业务现实）③范围问题"
        "（是独立问题还是更深层问题的症状）。"
        "如果信息仍不充分且未到第3轮，输出一个简短的追问问题（done=false，"
        "analysis_goal/question/baseline/business_meaning均为空字符串）；如果信息"
        "已充分，或已到第3轮（必须收敛），输出最终结果（done=true）：analysis_goal"
        "用一段话描述业务问题/决策背景/需要的数据/预计运行的分析模块（趋势/对比/"
        "人群/归因中的若干）；question为校验后的问题描述；baseline为指标正常范围"
        "或历史水位；business_meaning为这个指标真正代表的业务现实。"
        "严格按JSON格式输出，不要输出任何多余文字、不要使用Markdown代码块。"
    )
    user_prompt = f"""对话历史（JSON数组）：
{json.dumps(history, ensure_ascii=False)}

本轮用户输入：{user_message}

已上传表的字段摘要（可能为空，为空表示用户尚未上传数据）：
{json.dumps(table_summaries, ensure_ascii=False)}

当前轮次：{round_no}/{MAX_ROUNDS}{"（已达最大轮次，必须输出analysis_goal）" if force_conclude else ""}

请输出以下JSON结构：
{{"reply": "追问问题或对analysis_goal的简短说明", "analysis_goal": "已收敛时的分析目标描述，未收敛为空字符串", "question": "...", "baseline": "...", "business_meaning": "...", "done": true/false}}
"""

    result = chat_json(system_prompt, user_prompt)

    if not result:
        # LLM 不可用：降级，第3轮强制用用户原话作为 analysis_goal
        if force_conclude:
            reply = "AI澄清暂不可用，已使用你的描述作为分析目标。"
            analysis_goal = user_message
            done = True
        else:
            reply = "AI澄清暂不可用，请直接描述你的分析目标和关注的数据范围。"
            analysis_goal = ""
            done = False
        question, baseline, business_meaning = analysis_goal, "", ""
    else:
        reply = result.get("reply", "")
        analysis_goal = result.get("analysis_goal", "") or ""
        done = bool(result.get("done", False)) or force_conclude
        if done and not analysis_goal:
            analysis_goal = user_message
        question = result.get("question", "") or analysis_goal
        baseline = result.get("baseline", "") or ""
        business_meaning = result.get("business_meaning", "") or ""

    new_history = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": reply},
    ]

    return {
        "clarification_history": new_history,
        "round": round_no,
        "analysis_goal": analysis_goal,
        "question": question,
        "baseline": baseline,
        "business_meaning": business_meaning,
        "done": done,
    }
