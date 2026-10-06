"""Small model provider used by the standalone project report service."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class ReportModelError(RuntimeError):
    """The configured model provider could not return report content."""


def get_report_model_api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def chat_with_report_model(
    api_key: str,
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    timeout: int = 90,
) -> str:
    if not api_key.strip():
        raise ReportModelError("未配置 DEEPSEEK_API_KEY")
    endpoint = os.getenv("REPORT_MODEL_URL", "https://api.deepseek.com/chat/completions").strip()
    selected_model = model or os.getenv("REPORT_MODEL", "deepseek-v4-pro").strip()
    payload: dict[str, Any] = {
        "model": selected_model,
        "messages": messages,
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 8000,
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }

    def request_completion(request_payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ReportModelError(f"模型服务请求失败：HTTP {error.code}，{detail}") from error
        except urllib.error.URLError as error:
            raise ReportModelError(f"无法连接模型服务：{error.reason}") from error
        except TimeoutError as error:
            raise ReportModelError("模型服务请求超时，请稍后重试") from error
        if not isinstance(data, dict):
            raise ReportModelError("模型服务返回格式异常")
        return data

    def final_content(data: dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ReportModelError("模型服务返回格式异常：缺少回答字段") from error
        return str(content or "").strip()

    answer = final_content(request_completion(payload))
    if answer:
        return answer

    retry_payload = dict(payload)
    retry_payload["thinking"] = {"type": "disabled"}
    retry_payload["max_tokens"] = 4800
    retry_payload.pop("reasoning_effort", None)
    answer = final_content(request_completion(retry_payload))
    if answer:
        return answer
    raise ReportModelError("模型服务未返回可用的报告正文")


__all__ = ["ReportModelError", "chat_with_report_model", "get_report_model_api_key"]
