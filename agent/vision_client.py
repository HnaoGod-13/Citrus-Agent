from __future__ import annotations

import base64
import importlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

try:
    from . import llm_config as _llm_config
except ImportError:
    _llm_config = None


DEFAULT_VISION_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_VISION_MODEL = "qwen-vl-max"


class VisionAPIError(RuntimeError):
    pass


def _config_value(name: str, default: str = "") -> str:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value

    if _llm_config is not None:
        try:
            module = importlib.reload(_llm_config)
        except Exception:
            module = _llm_config
        value = getattr(module, name, "")
        if value:
            return str(value).strip()
    return default.strip()


def get_vision_api_key() -> str:
    return _config_value("VISION_API_KEY")


def get_vision_model() -> str:
    return _config_value("VISION_MODEL", DEFAULT_VISION_MODEL) or DEFAULT_VISION_MODEL


def get_vision_api_url() -> str:
    return _config_value("VISION_API_URL", DEFAULT_VISION_API_URL) or DEFAULT_VISION_API_URL


def _image_data_url(image_bytes: bytes, mime_type: str) -> str:
    mime_type = mime_type or "image/jpeg"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise VisionAPIError("视觉模型返回为空。")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise VisionAPIError(f"视觉模型未返回 JSON：{text}")
        return json.loads(match.group(0))


def normalize_vision_result(data: dict[str, Any]) -> dict[str, Any]:
    appearance_description = str(data.get("外观描述") or data.get("appearance_description") or "").strip()
    if not appearance_description:
        color = data.get("颜色成熟度") or data.get("color_maturity") or "未判断"
        integrity = data.get("果皮完整度") or data.get("peel_integrity") or "未判断"
        mold = data.get("疑似霉斑") or data.get("suspected_mold")
        decay = data.get("疑似腐烂") or data.get("suspected_decay")
        appearance_description = f"颜色成熟度：{color}；果皮完整度：{integrity}；疑似霉斑：{mold}；疑似腐烂：{decay}。"

    risk_notes = data.get("风险提示") or data.get("risk_notes") or []
    if isinstance(risk_notes, str):
        risk_notes = [risk_notes]
    risk_notes.append("图片识别仅用于外观初筛，不能替代农残、重金属、微生物和黄曲霉毒素检测。")

    return {
        "appearance_description": appearance_description,
        "structured_observation": data,
        "risk_notes": risk_notes,
    }


def recognize_citrus_image(image_bytes: bytes, mime_type: str = "image/jpeg", timeout: int = 90) -> dict[str, Any]:
    api_key = get_vision_api_key()
    if not api_key:
        raise VisionAPIError("请先在 agent/llm_config.py 中配置 VISION_API_KEY。")

    prompt = """
你是柑橘/陈皮加工质控助手。请只根据图片中可见外观做初步识别，不要推断不可见检测结果。
请返回严格 JSON，不要输出 Markdown，不要输出解释性前后缀。
字段必须包含：
{
  "颜色成熟度": "偏青/偏成熟/过熟/无法判断",
  "果皮完整度": "完整/轻微破损/明显破损/无法判断",
  "疑似霉斑": true或false,
  "疑似腐烂": true或false,
  "机械伤": "未见明显机械伤/轻微/明显/无法判断",
  "表面状态": "干爽/潮湿/皱缩/有污渍/无法判断",
  "外观描述": "一句适合写入批次分析报告的中文描述",
  "风险提示": ["仅基于图片外观判断，不能替代实验室检测"]
}
如果图片不是柑橘或无法判断，也请如实说明，不要编造。
""".strip()

    payload = {
        "model": get_vision_model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_bytes, mime_type)}},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 1000,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        get_vision_api_url(),
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise VisionAPIError(f"视觉模型请求失败：HTTP {error.code}，{detail}") from error
    except urllib.error.URLError as error:
        raise VisionAPIError(f"无法连接视觉模型 API：{error.reason}") from error
    except TimeoutError as error:
        raise VisionAPIError("视觉模型请求超时，请稍后重试。") from error

    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise VisionAPIError(f"视觉模型返回格式异常：{response_data}") from error

    return normalize_vision_result(_extract_json(content))
