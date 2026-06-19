import json
import os
import sys

import httpx

ARK_URL = "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
ARK_MODEL = "ark-code-latest"

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DASHSCOPE_MODEL = "deepseek-v4-flash"


def _parse_json_content(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    return json.loads(content)


def _call(
    url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float,
    use_json_response_format: bool = True,
) -> dict | None:
    try:
        body = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if use_json_response_format:
            body["response_format"] = {"type": "json_object"}

        response = httpx.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json=body,
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return _parse_json_content(content)
    except httpx.HTTPStatusError as e:
        print(f"[llm._call] {model} HTTP {e.response.status_code}: {e.response.text[:300]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[llm._call] {model} {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        return None


def chat_json(system_prompt: str, user_prompt: str, timeout: float = 60.0) -> dict | None:
    """调用 LLM，要求模型输出结构化 JSON。

    优先使用火山方舟 Coding Plan（ARK_API_KEY），失败或未配置时降级到
    DashScope（DASHSCOPE_API_KEY）。两者均未配置或都调用失败时返回 None，
    调用方需做降级处理（不阻断主流程）。
    """
    ark_key = os.getenv("ARK_API_KEY")
    if ark_key:
        # ark-code-latest 不支持 response_format=json_object，靠 prompt 约束输出格式
        ark_system_prompt = system_prompt + "\n\n只输出合法 JSON，不要使用 markdown 代码块，不要任何额外文字。"
        result = _call(
            ARK_URL, ark_key, ARK_MODEL, ark_system_prompt, user_prompt, timeout,
            use_json_response_format=False,
        )
        if result is not None:
            return result

    dashscope_key = os.getenv("DASHSCOPE_API_KEY")
    if not dashscope_key:
        return None

    return _call(DASHSCOPE_URL, dashscope_key, DASHSCOPE_MODEL, system_prompt, user_prompt, timeout)
