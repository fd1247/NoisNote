"""LLM 总结模块，支持 OpenAI 兼容 API 和 Anthropic API。"""
from __future__ import annotations

import threading
from typing import Any

import httpx

from ..app.config import ANTHROPIC_API_VERSION, ANTHROPIC_DEFAULT_BASE_URL, ANTHROPIC_DEFAULT_MODEL


class Summarizer:
    """LLM 总结引擎"""

    SYSTEM_PROMPT = "你是一个专业的录音内容总结助手，请根据用户提供的录音转录文稿生成简洁准确的总结。"
    USER_PROMPT_TEMPLATE = "请总结以下录音转录文稿：\n\n{text}"

    def __init__(self):
        self.client = None

    def _get_client(self):
        """获取 HTTP 客户端"""
        if not self.client:
            self.client = httpx.Client(timeout=60.0)
        return self.client

    def summarize(self, text, config, on_progress=None):
        """调用 LLM API 总结文字"""
        if not text or not text.strip():
            return ""

        llm_config = config.get("llm", {})
        provider = llm_config.get("provider", "openai")
        api_key = llm_config.get("api_key", "")
        model = llm_config.get("model", "")
        base_url = llm_config.get("base_url", "")

        if not api_key:
            raise ValueError("未配置 LLM API Key，请在设置中配置")

        # 根据 provider 选择默认值并构建请求
        user_prompt = self.USER_PROMPT_TEMPLATE.format(text=text)
        if provider == "anthropic":
            model = model or ANTHROPIC_DEFAULT_MODEL
            base_url = base_url or ANTHROPIC_DEFAULT_BASE_URL
            url, headers, payload = _build_anthropic_request(
                api_key, model, base_url, self.SYSTEM_PROMPT, user_prompt,
            )
            parse_response = _parse_anthropic_response
        else:
            model = model or "gpt-4o-mini"
            base_url = base_url or "https://api.openai.com/v1"
            url, headers, payload = _build_openai_request(
                api_key, model, base_url, self.SYSTEM_PROMPT, user_prompt,
            )
            parse_response = _parse_openai_response

        if on_progress:
            on_progress("正在调用 LLM 总结")

        client = self._get_client()

        try:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()

            summary = parse_response(response.json())

            if on_progress:
                on_progress("总结完成")

            return summary

        except httpx.TimeoutException:
            if on_progress:
                on_progress("LLM API 请求超时")
            raise
        except httpx.HTTPStatusError as e:
            if on_progress:
                on_progress(f"LLM API 错误: {e.response.status_code}")
            raise
        except Exception as e:
            if on_progress:
                on_progress(f"总结失败: {e}")
            raise

    def summarize_async(self, text, config, on_complete=None, on_progress=None):
        """异步总结"""
        def _do_summarize():
            try:
                summary = self.summarize(text, config, on_progress)
                if on_complete:
                    on_complete(summary, None)
            except Exception as e:
                if on_complete:
                    on_complete(None, e)

        thread = threading.Thread(target=_do_summarize, daemon=True)
        thread.start()
        return thread

    def cleanup(self):
        """清理资源"""
        if self.client:
            self.client.close()
            self.client = None


# ---- OpenAI 兼容 API ----

def _build_openai_request(
    api_key: str,
    model: str,
    base_url: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """构建 OpenAI 兼容 API 的请求。返回 (url, headers, payload)。"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }
    return url, headers, payload


def _parse_openai_response(result: dict) -> str:
    """从 OpenAI 兼容响应中提取总结文本。"""
    return result["choices"][0]["message"]["content"]


# ---- Anthropic API ----

def _build_anthropic_request(
    api_key: str,
    model: str,
    base_url: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """构建 Anthropic Messages API 的请求。返回 (url, headers, payload)。"""
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": 0.3,
    }
    return url, headers, payload


def _parse_anthropic_response(result: dict) -> str:
    """从 Anthropic Messages API 响应中提取总结文本。"""
    return result["content"][0]["text"]
