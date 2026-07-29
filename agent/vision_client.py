from __future__ import annotations

import base64
import importlib
import io
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
except ImportError:
    register_heif_opener = None

try:
    from . import llm_config as _llm_config
except ImportError:
    _llm_config = None


DEFAULT_VISION_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_VISION_MODEL = "qwen-vl-max"
SUPPORTED_UPLOAD_EXTENSIONS = (
    "jpg",
    "jpeg",
    "jpe",
    "jfif",
    "png",
    "webp",
    "bmp",
    "dib",
    "gif",
    "tif",
    "tiff",
    "heic",
    "heif",
    "avif",
    "jp2",
    "j2k",
    "ico",
    "ppm",
    "pgm",
    "pbm",
    "pnm",
    "tga",
    "dds",
    "pcx",
    "sgi",
)
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_SOURCE_PIXELS = 50_000_000
MAX_MODEL_PIXELS = 15_000_000
MAX_MODEL_EDGE = 4096
MAX_MODEL_IMAGE_BYTES = 7_000_000

if register_heif_opener is not None:
    register_heif_opener()


class VisionAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedVisionImage:
    data: bytes
    mime_type: str
    source_format: str
    width: int
    height: int
    frame_count: int
    notes: tuple[str, ...]


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


def _to_rgb(image: Image.Image) -> Image.Image:
    has_alpha = image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _fit_model_dimensions(image: Image.Image) -> tuple[Image.Image, bool]:
    width, height = image.size
    scale = min(
        1.0,
        MAX_MODEL_EDGE / max(width, height),
        (MAX_MODEL_PIXELS / (width * height)) ** 0.5,
    )
    if scale >= 1.0:
        return image, False
    target = (max(10, round(width * scale)), max(10, round(height * scale)))
    return image.resize(target, Image.Resampling.LANCZOS), True


def _encode_model_jpeg(image: Image.Image) -> tuple[bytes, Image.Image]:
    current = image
    while True:
        for quality in (92, 86, 80, 72, 64, 56):
            output = io.BytesIO()
            current.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
            data = output.getvalue()
            if len(data) <= MAX_MODEL_IMAGE_BYTES:
                return data, current
        width, height = current.size
        if min(width, height) <= 10:
            raise VisionAPIError("图片压缩后仍超过视觉模型的大小限制，请先缩小图片。")
        current = current.resize(
            (max(10, round(width * 0.82)), max(10, round(height * 0.82))),
            Image.Resampling.LANCZOS,
        )


def prepare_image_for_vision(
    image_bytes: bytes,
    filename: str = "",
    mime_type: str = "",
) -> PreparedVisionImage:
    if not image_bytes:
        raise VisionAPIError("上传的图片为空，请重新选择文件。")
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise VisionAPIError("图片超过 40 MB，请先压缩后再上传。")

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source_format = str(source.format or mime_type or "未知格式").upper()
            frame_count = int(getattr(source, "n_frames", 1) or 1)
            width, height = source.size
            if width < 10 or height < 10:
                raise VisionAPIError("图片的宽和高都必须至少为 10 像素。")
            if width * height > MAX_SOURCE_PIXELS:
                raise VisionAPIError("图片像素超过 5000 万，请先缩小分辨率后再上传。")
            if max(width / height, height / width) > 200:
                raise VisionAPIError("图片长宽比不能超过 200:1。")

            source.seek(0)
            first_frame = ImageOps.exif_transpose(source).copy()
    except VisionAPIError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as error:
        suffix = f"（{filename}）" if filename else ""
        raise VisionAPIError(f"无法读取该图片{suffix}，文件可能损坏或格式与扩展名不一致。") from error

    image = _to_rgb(first_frame)
    image, resized = _fit_model_dimensions(image)
    data, image = _encode_model_jpeg(image)
    notes: list[str] = []
    if source_format not in {"JPEG", "JPG"}:
        notes.append(f"{source_format} 已自动转为 JPEG")
    if frame_count > 1:
        notes.append(f"检测到 {frame_count} 帧，仅分析第一帧")
    if resized or image.size != (width, height):
        notes.append(f"已缩放至 {image.width}×{image.height}")
    if not notes:
        notes.append("已完成图片内容校验")

    return PreparedVisionImage(
        data=data,
        mime_type="image/jpeg",
        source_format=source_format,
        width=image.width,
        height=image.height,
        frame_count=frame_count,
        notes=tuple(notes),
    )


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

    normalized_mime = (mime_type or "").lower()
    is_prepared_jpeg = (
        normalized_mime in {"image/jpeg", "image/jpg"}
        and image_bytes.startswith(b"\xff\xd8")
        and len(image_bytes) <= MAX_MODEL_IMAGE_BYTES
    )
    if not is_prepared_jpeg:
        prepared = prepare_image_for_vision(image_bytes, mime_type=mime_type)
        image_bytes = prepared.data
        mime_type = prepared.mime_type

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
