import json
import os

import httpx

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "deepseek-v4-flash"


def chat_json(system_prompt: str, user_prompt: str, timeout: float = 60.0) -> dict | None:
    """调用 DashScope，要求模型输出结构化 JSON。

    未配置 DASHSCOPE_API_KEY、请求失败或返回内容无法解析为 JSON 时返回 None，
    调用方需做降级处理（不阻断主流程）。
    """
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        return None

    try:
        response = httpx.post(
            DASHSCOPE_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": MODEL,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        return None
