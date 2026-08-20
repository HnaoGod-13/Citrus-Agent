from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .llm_client import DeepSeekAPIError, build_chat_messages, chat_with_deepseek
from .memory import describe_model_messages
from .report import parameterized_plan_markdown
from .vision_client import VisionAPIError, recognize_citrus_image
from .workflow import run_demo_agent, save_report, write_audit_event


CUSTOMER_OPTIONS = ["陈皮经销商", "茶饮品牌", "食品加工厂"]
PROCESSING_FLOW_START = "<!-- citrus-agent-processing-flow:start -->"
PROCESSING_FLOW_END = "<!-- citrus-agent-processing-flow:end -->"
TEST_LABELS = {
    "pesticide": "农残",
    "heavy_metal": "重金属",
    "microbe": "微生物",
    "aflatoxin": "黄曲霉毒素",
}
TEST_ALIASES = {
    "pesticide": ["农残", "农药残留"],
    "heavy_metal": ["重金属"],
    "microbe": ["微生物"],
    "aflatoxin": ["黄曲霉毒素", "黄曲霉"],
}
MEASUREMENT_RANGES = {
    "weight_kg": (0.0, 10_000_000.0, "重量", "kg"),
    "brix": (0.0, 35.0, "糖度", "°Bx"),
    "acidity": (0.0, 10.0, "酸度", "%（以可滴定酸输入）"),
    "moisture": (0.0, 100.0, "水分", "%"),
}
ANALYSIS_KEYWORDS = [
    "分析",
    "判断",
    "加工",
    "报告",
    "批次",
    "陈皮",
    "柑橘",
    "茶枝柑",
    "橙",
    "果肉",
    "果皮",
    "果胶",
    "黄酮",
    "精油",
    "副产物",
    "罐头",
    "蜜饯",
    "果脯",
    "NFC",
    "糖度",
    "水分",
    "酸度",
    "农残",
    "重金属",
    "微生物",
    "黄曲霉",
]
GENERAL_KNOWLEDGE_KEYWORDS = [
    "介绍",
    "科普",
    "是什么",
    "什么是",
    "讲讲",
    "概述",
    "解释",
    "说明一下",
    "了解一下",
    "百科",
    "有哪些",
    "有什么",
    "有几种",
    "哪些",
    "种类",
    "分类",
    "特点",
    "来源",
    "历史",
    "区别",
    "用途",
]
TOOL_INTENT_KEYWORDS = [
    "分析",
    "判断",
    "评估",
    "推荐",
    "报告",
    "出报告",
    "生成报告",
    "加工",
    "方向",
    "路线",
    "方案",
    "适合",
    "打分",
    "评分",
    "质控",
    "风险",
    "检测",
    "复核",
    "小试",
    "报价",
    "客户",
    "拆开",
    "按整果",
    "按果肉",
    "按果皮",
    "还能做",
    "怎么处理",
    "文献",
    "依据",
    "来源",
]
BATCH_REFERENCE_KEYWORDS = ["这批", "一批", "当前批次", "当前", "批次", "原料", "样品", "这批货", "一批货", "当前原料"]
CURRENT_BATCH_REFERENCE_KEYWORDS = [
    "这批",
    "当前批次",
    "当前原料",
    "该批次",
    "刚才那批",
    "刚才的批次",
    "上一批",
    "上一个批次",
    "上面那批",
    "根据上面",
    "按刚才",
    "沿用刚才",
    "继续分析",
    "继续评估",
]
BATCH_DATA_KEYWORDS = [
    "糖度",
    "brix",
    "酸度",
    "水分",
    "含水率",
    "农残",
    "重金属",
    "微生物",
    "黄曲霉",
    "重量",
    "公斤",
    "kg",
    "采收",
    "外观",
]
WEAK_BATCH_DATA_KEYWORDS = ["产地", "品种", "客户", "来源"]
IMAGE_INTENT_KEYWORDS = ["图片", "照片", "图像", "这张图", "这张图片", "外观", "识别", "看图", "看一下", "颜色", "霉", "腐烂", "破损"]
DIRECT_VISION_QUESTION_KEYWORDS = [
    "图片",
    "照片",
    "图像",
    "这张图",
    "图中",
    "上传",
    "识别",
    "看图",
    "看看",
    "看一下",
    "是什么",
    "属于什么",
    "品种",
    "种类",
    "外观",
    "颜色",
    "成熟度",
    "霉",
    "腐烂",
    "破损",
    "病斑",
    "机械伤",
]
EXPLICIT_PROCESSING_DECISION_KEYWORDS = [
    "加工",
    "工艺",
    "生产流程",
    "加工流程",
    "路线",
    "加工方向",
    "产品方向",
    "决策",
    "方案",
    "出报告",
    "生成报告",
    "打分",
    "评分",
    "小试",
    "报价",
    "客户需求",
    "质控方案",
    "怎么处理",
    "副产物利用",
    "果胶",
    "精油",
    "nfc",
    "果汁",
    "陈皮",
]
DOMAIN_KEYWORDS = [
    "陈皮",
    "柑橘",
    "茶枝柑",
    "脐橙",
    "橙",
    "果肉",
    "果皮",
    "整果",
    "种子",
    "副产物",
    "果胶",
    "黄酮",
    "精油",
    "NFC",
    "果汁",
]
OBSERVATION_KEYWORDS = ["霉", "腐烂", "破损", "裂果", "压伤", "机械伤", "异味", "发黑", "完整", "成熟", "颜色"]
KNOWN_ORIGINS = ["新会", "赣南", "宜昌", "秭归", "广西", "福建", "云南", "四川"]
KNOWN_VARIETIES = ["茶枝柑", "脐橙", "甜橙", "砂糖橘", "沃柑", "金桔", "金橘", "柚", "柠檬", "柑橘", "橙"]
VISION_VARIETY_TERMS = [
    "纽荷尔脐橙",
    "普通甜橙",
    "纽荷尔橙",
    "冰糖橙",
    "血橙",
    "脐橙",
    "甜橙",
    "砂糖橘",
    "沙糖橘",
    "沃柑",
    "茶枝柑",
    "椪柑",
    "贡柑",
    "茂谷柑",
    "金桔",
    "金橘",
    "柚子",
    "柚",
    "柠檬",
]
VISION_ENTITY_REFERENCES = [
    "这个品种",
    "这种品种",
    "该品种",
    "这个柑橘",
    "这种柑橘",
    "这类柑橘",
    "这个橙子",
    "这种橙子",
    "这个果实",
    "这种果实",
    "该果实",
    "上一张图",
    "刚才图片",
]
ProgressCallback = Callable[[str], None]


def _notify(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback:
        progress_callback(message)


def default_batch() -> dict[str, Any]:
    batch = {
        "batch_id": f"B{uuid4().hex[:8].upper()}",
        "origin": "",
        "variety": "",
        "harvest_date": "",
        "weight_kg": "",
        "brix": "",
        "acidity": "",
        "moisture": "",
        "customer_type": "",
        "pesticide": None,
        "heavy_metal": None,
        "microbe": None,
        "aflatoxin": None,
    }
    for key in TEST_LABELS:
        batch[f"{key}_status"] = None
    return batch


def _has_any(text: str, keywords: list[str]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def should_answer_with_vision_only(text: str, has_image: bool = False) -> bool:
    """Route an attached-image question to vision unless processing work is explicit."""
    if not has_image:
        return False
    normalized = re.sub(r"\s+", "", text.lower())
    if _has_any(normalized, EXPLICIT_PROCESSING_DECISION_KEYWORDS):
        return False
    return not normalized or _has_any(normalized, DIRECT_VISION_QUESTION_KEYWORDS)


def references_current_batch(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.lower())
    if _has_any(normalized, CURRENT_BATCH_REFERENCE_KEYWORDS):
        return True
    if normalized in {"继续", "接着", "出报告", "生成报告", "做质控", "重新评分", "再评估"}:
        return True
    if references_previous_evidence(normalized):
        return True
    return bool(
        len(normalized) <= 80
        and re.search(
            r"(?:产地|品种|糖度|brix|酸度|水分|重量|客户|农残|重金属|微生物|黄曲霉)"
            r".{0,12}(?:改成|调整为|更正为|更新为|补充|改为)",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def references_previous_evidence(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.lower())
    if not any(term in normalized for term in ["文献", "论文", "依据", "来源", "参考资料"]):
        return False
    return bool(
        len(normalized) <= 80
        and (
            any(term in normalized for term in ["单独", "列出", "整理", "给我", "发我", "上面", "刚才", "引用", "用到"])
            or normalized in {"文献", "依据", "来源", "参考文献"}
        )
    )


def references_previous_vision_entity(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text.lower())
    if _has_any(normalized, ["忽略上文", "不要参考上文", "不是上一张", "另一张图", "新图片"]):
        return False
    if _has_any(normalized, VISION_ENTITY_REFERENCES):
        return True
    return len(normalized) <= 50 and bool(
        re.search(r"(?:^|那)(?:它|这个|这种)(?:适合|能|可以|怎么|如何|有什么|为什么|是)", normalized)
    )


def infer_vision_variety_candidate(vision_result: dict[str, Any] | None) -> str:
    if not vision_result:
        return ""
    structured = vision_result.get("structured_observation") or {}
    candidate = str(
        vision_result.get("variety_candidate")
        or structured.get("品种候选")
        or structured.get("variety_candidate")
        or ""
    ).strip()
    candidate = re.sub(r"^(?:疑似|可能为|可能是|候选为)\s*", "", candidate)
    if candidate and not any(marker in candidate for marker in ["无法", "未知", "未判断", "不确定", "/"]):
        return candidate[:30]

    combined = " ".join(
        str(value or "")
        for value in [
            vision_result.get("answer"),
            vision_result.get("appearance_description"),
            structured.get("针对用户问题的回答"),
        ]
    )
    for variety in VISION_VARIETY_TERMS:
        if variety in combined:
            return variety
    return ""


def build_vision_memory(payload: dict[str, Any] | None) -> dict[str, str]:
    payload = payload or {}
    vision_result = payload.get("vision_result") or payload
    if not isinstance(vision_result, dict):
        return {}
    candidate = infer_vision_variety_candidate(vision_result)
    structured = vision_result.get("structured_observation") or {}
    confidence = str(
        vision_result.get("variety_confidence")
        or structured.get("品种判断置信度")
        or structured.get("variety_confidence")
        or ("低" if candidate else "")
    ).strip()
    return {
        "variety_candidate": candidate,
        "variety_confidence": confidence,
        "vision_answer": str(vision_result.get("answer") or "").strip(),
        "appearance_description": str(vision_result.get("appearance_description") or "").strip(),
        "source": "上一轮上传图片的视觉识别",
    }


def recover_vision_memory_from_messages(messages: list[dict[str, Any]]) -> dict[str, str]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") != "user" or not message.get("image_bytes"):
            continue
        for reply in messages[index + 1:]:
            if reply.get("role") != "assistant":
                continue
            if reply.get("kind") == "analysis":
                memory = build_vision_memory(reply.get("payload") or {})
            else:
                memory = build_vision_memory(
                    reply.get("vision_result")
                    or {"answer": str(reply.get("content") or "")}
                )
            if memory.get("variety_candidate"):
                return memory
            break
        break
    return {}


def resolve_vision_follow_up(text: str, vision_memory: dict[str, Any] | None) -> str:
    if not vision_memory or not references_previous_vision_entity(text):
        return text
    candidate = str(vision_memory.get("variety_candidate") or "").strip()
    if not candidate:
        return text
    confidence = str(vision_memory.get("variety_confidence") or "低").strip()
    previous_answer = str(vision_memory.get("vision_answer") or "").strip()
    appearance = str(vision_memory.get("appearance_description") or "").strip()
    remembered_details = ""
    if previous_answer:
        remembered_details += f"上一轮视觉答复：{previous_answer[:500].rstrip('。！？； ')}。"
    if appearance and appearance not in previous_answer:
        remembered_details += f"上一轮可见外观：{appearance[:300].rstrip('。！？； ')}。"
    return (
        f"{text}\n\n"
        "【会话指代解析（由系统提供）】"
        f"本轮“这个品种/它”指上一轮上传图片的视觉识别候选“{candidate}”；"
        f"视觉判断置信度为“{confidence}”，具体品系尚未通过产地、标签或来源资料确认。"
        f"{remembered_details}"
        "请直接承接该候选回答，不要再次要求用户重复品种名称；同时保留视觉初筛的不确定性。"
    )


_FORGOTTEN_VARIETY_PATTERN = re.compile(
    r"[^。！？\n]*(?:请|需要|需)(?:先)?(?:提供|明确|确认|告诉)"
    r"[^。！？\n]{0,40}(?:品种|是哪一种|是什么柑橘)[^。！？\n]*[。！？]?"
)


def ensure_vision_follow_up_answer(
    answer: str,
    original_prompt: str,
    vision_memory: dict[str, Any] | None,
) -> str:
    text = str(answer or "").strip()
    if not vision_memory or not references_previous_vision_entity(original_prompt):
        return text
    candidate = str(vision_memory.get("variety_candidate") or "").strip()
    if not candidate:
        return text
    cleaned = _FORGOTTEN_VARIETY_PATTERN.sub("", text).strip()
    if not cleaned:
        cleaned = (
            "目前可以先按该候选类别讨论品种层面的加工方向；"
            "若要形成当前批次的路线分级、工艺参数或放行结论，仍需补充产地、糖酸、水分和检测状态。"
        )
    confidence = str(vision_memory.get("variety_confidence") or "低").strip()
    prefix = (
        f"本轮已承接上一轮图片识别结果：“这个品种”指候选“{candidate}”"
        f"（视觉判断置信度：{confidence}，具体品系仍需来源资料确认）。"
    )
    if prefix in cleaned:
        return cleaned
    return f"{prefix}\n\n{cleaned}"


def _batch_has_identity(text: str, current_batch: dict[str, Any] | None) -> bool:
    if current_batch and (current_batch.get("origin") or current_batch.get("variety")):
        return True
    if re.search(r"(?:产地|来自|来源|原产地|品种)[:：\s]*[\u4e00-\u9fa5A-Za-z0-9]{2,12}", text):
        return True
    return _has_any(text, KNOWN_ORIGINS + KNOWN_VARIETIES)


def _batch_has_decision_data(
    text: str,
    current_batch: dict[str, Any] | None,
    manual_observation: str,
    has_image: bool,
) -> bool:
    if has_image or manual_observation.strip():
        return True
    if _has_any(text, BATCH_DATA_KEYWORDS + WEAK_BATCH_DATA_KEYWORDS + OBSERVATION_KEYWORDS):
        return True
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|kg|公斤|千克|brix|bx|°brix)", text, flags=re.IGNORECASE):
        return True
    if not current_batch:
        return False
    measured_fields = ("weight_kg", "brix", "acidity", "moisture", "customer_type")
    if any(current_batch.get(key) not in ("", None) for key in measured_fields):
        return True
    return any(current_batch.get(key) is not None for key in TEST_LABELS)


def missing_batch_inputs(
    text: str,
    current_batch: dict[str, Any] | None = None,
    manual_observation: str = "",
    has_image: bool = False,
) -> list[str]:
    missing: list[str] = []
    if not _batch_has_identity(text, current_batch):
        missing.append("产地或品种（陈皮方向最好同时提供两项）")
    if not _batch_has_decision_data(text, current_batch, manual_observation, has_image):
        missing.append("至少一项真实批次信息，如糖度、酸度、水分、客户类型、检测状态或外观记录")
    return missing


def should_request_batch_data(
    text: str,
    current_batch: dict[str, Any] | None = None,
    manual_observation: str = "",
    has_image: bool = False,
) -> bool:
    if should_answer_with_vision_only(text, has_image=has_image):
        return False
    normalized = text.lower()
    has_general_knowledge_intent = _has_any(normalized, GENERAL_KNOWLEDGE_KEYWORDS)
    has_analysis_intent = _has_any(normalized, TOOL_INTENT_KEYWORDS)
    has_batch_topic = _has_any(normalized, BATCH_REFERENCE_KEYWORDS + DOMAIN_KEYWORDS + IMAGE_INTENT_KEYWORDS)
    if has_general_knowledge_intent and not references_current_batch(text):
        return False
    if not (has_analysis_intent and (has_batch_topic or has_image)):
        return False
    return bool(missing_batch_inputs(text, current_batch, manual_observation, has_image))


def build_batch_data_request(missing: list[str]) -> str:
    missing_text = "；".join(missing)
    return (
        "目前不能得出加工方向或质控结论，因为本轮没有足够的真实批次数据。"
        "我不会用演示模板、默认值或上一轮内容替你补齐事实。\n\n"
        f"请补充：{missing_text}。\n"
        "可以直接按“产地、品种、糖度、酸度、水分、客户类型、检测状态、外观”一行填写；"
        "资料不全时我只会列出缺口，不会生成推荐分数或报告。"
    )


def should_run_tools(
    text: str,
    has_image: bool = False,
    has_current_batch: bool = False,
    has_minimum_batch_data: bool = True,
) -> bool:
    """Decide whether to run the batch-analysis tool chain instead of general chat."""
    if should_answer_with_vision_only(text, has_image=has_image):
        return False
    if not has_minimum_batch_data:
        return False
    normalized = text.lower()
    has_general_knowledge_intent = _has_any(normalized, GENERAL_KNOWLEDGE_KEYWORDS)
    has_tool_intent = _has_any(normalized, TOOL_INTENT_KEYWORDS)
    has_batch_reference = _has_any(normalized, BATCH_REFERENCE_KEYWORDS)
    has_strong_batch_data = _has_any(normalized, BATCH_DATA_KEYWORDS) or bool(
        re.search(r"\d+(?:\.\d+)?\s*(?:%|kg|公斤|千克|brix|bx|°brix)", normalized, flags=re.IGNORECASE)
    )
    has_weak_batch_data = _has_any(normalized, WEAK_BATCH_DATA_KEYWORDS)
    has_domain = _has_any(normalized, DOMAIN_KEYWORDS)
    has_image_intent = _has_any(normalized, IMAGE_INTENT_KEYWORDS)

    if has_general_knowledge_intent and not (has_batch_reference or has_strong_batch_data):
        return False
    if has_image and (has_image_intent or has_batch_reference or has_strong_batch_data):
        return True
    if has_strong_batch_data and (has_domain or has_tool_intent or has_batch_reference):
        return True
    if has_batch_reference and (has_tool_intent or has_domain or has_weak_batch_data):
        return True
    if has_current_batch and has_tool_intent and not has_general_knowledge_intent:
        return True
    if has_current_batch and any(keyword.lower() in normalized for keyword in ["出报告", "生成报告", "质控", "评分", "小试"]):
        return True
    return False


def _first_number(patterns: list[str], text: str) -> float | str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return ""


def _validated_measurement(
    field: str,
    value: float | str,
    previous: Any,
    notes: list[str],
) -> Any:
    if value == "":
        return previous
    minimum, maximum, label, unit = MEASUREMENT_RANGES[field]
    numeric = float(value)
    if not minimum <= numeric <= maximum or (field == "weight_kg" and numeric <= 0):
        notes.append(
            f"{label} {numeric:g} 超出系统可接受范围 {minimum:g}–{maximum:g} {unit}，"
            "本轮未采用该值，请核对单位或原始记录。"
        )
        return previous
    return numeric


def _detect_test_state(text: str, label: str) -> tuple[bool | None, str | None]:
    if label not in text:
        return None, None
    clauses = [clause for clause in re.split(r"[，,。；;\n]", text) if label in clause]
    near = re.sub(r"\s+", "", clauses[0] if clauses else text)
    if re.search(r"(?:未检出|未超标|没有超标|无超标|结果合格|检测合格|通过|符合(?:要求|标准))", near):
        return True, "passed"
    if re.search(r"(?:不合格|未通过|超过限量|超标|阳性|异常)", near):
        return False, "failed"
    if re.search(r"(?:尚未|未做|未检测|没有做|没有检测|无检测|缺少|未提供|待检|待检测)", near):
        return False, "missing"
    if re.search(r"(?:已检测|完成检测|报告已出|已有报告|有报告)", near):
        return False, "result_missing"
    return None, None


def extract_batch_from_text(text: str, current_batch: dict[str, Any] | None = None) -> tuple[dict[str, Any], str, list[str]]:
    batch = {**default_batch(), **(current_batch or {})}
    notes: list[str] = []

    origin_match = re.search(r"(?:产地|来自|来源|原产地)[:：\s]*([\u4e00-\u9fa5A-Za-z0-9]{2,12})", text)
    if origin_match:
        batch["origin"] = origin_match.group(1)
    else:
        for origin in KNOWN_ORIGINS:
            if origin in text:
                batch["origin"] = origin
                break

    for variety in KNOWN_VARIETIES:
        if variety in text:
            batch["variety"] = variety
            break

    for customer in CUSTOMER_OPTIONS:
        if customer in text:
            batch["customer_type"] = customer
            break
    if "茶饮" in text:
        batch["customer_type"] = "茶饮品牌"
    elif "食品加工" in text or "加工厂" in text:
        batch["customer_type"] = "食品加工厂"
    elif "经销" in text:
        batch["customer_type"] = "陈皮经销商"

    date_match = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})", text)
    if date_match:
        batch["harvest_date"] = date_match.group(1).replace("年", "-").replace("月", "-").replace("/", "-").replace(".", "-").rstrip("日")

    measurement_patterns = {
        "weight_kg": [r"(?:重量|总量|批量)[^\d+\-]{0,6}([+\-]?\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)", r"([+\-]?\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)"],
        "brix": [r"(?:糖度|brix)[^\d+\-]{0,6}([+\-]?\d+(?:\.\d+)?)", r"([+\-]?\d+(?:\.\d+)?)\s*(?:°?brix|bx)"],
        "acidity": [r"(?:酸度|总酸)[^\d+\-]{0,6}([+\-]?\d+(?:\.\d+)?)"],
        "moisture": [r"(?:水分|含水率)[^\d+\-]{0,6}([+\-]?\d+(?:\.\d+)?)\s*%?"],
    }
    for field, patterns in measurement_patterns.items():
        parsed = _first_number(patterns, text)
        batch[field] = _validated_measurement(field, parsed, batch.get(field, ""), notes)

    for key, label in TEST_LABELS.items():
        for alias in TEST_ALIASES[key]:
            state, status = _detect_test_state(text, alias)
            if state is not None:
                batch[key] = state
                batch[f"{key}_status"] = status
                break

    observation_parts = []
    for sentence in re.split(r"[。；;\n]", text):
        if any(keyword in sentence for keyword in OBSERVATION_KEYWORDS):
            observation_parts.append(sentence.strip())
    observation = "；".join(part for part in observation_parts if part)

    return batch, observation, notes


def _item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def summarize_processing_plan(plan: dict[str, Any]) -> str:
    if not plan:
        return ""

    lines = [
        "### 完整加工流程（方案）",
        "",
        f"**目标产品**：{plan.get('product_form') or '待确认'}  ",
        f"**方案状态**：{plan.get('status') or '待小试复核'}",
        "",
        "**全流程**：",
        "",
        " → ".join(str(step) for step in plan.get("flow", [])),
        "",
    ]
    for stage in plan.get("stages", []):
        lines.extend(
            [
                f"#### {stage.get('name') or '加工阶段'}",
                "",
                f"- **对应工序**：{' → '.join(str(step) for step in stage.get('steps', []))}",
                f"- **操作要点**：{stage.get('operation') or '待确认'}",
                f"- **质控要求**：{stage.get('control') or '待确认'}",
                f"- **必留记录**：{stage.get('record') or '待确认'}",
                "",
            ]
        )

    lines.extend(
        [
            "#### 小试与放行清单",
            "",
            f"- **待小试定参**：{'；'.join(str(item) for item in plan.get('pilot_parameters', [])) or '待确认'}。",
            f"- **成品放行复核**：{'；'.join(str(item) for item in plan.get('release_checks', [])) or '待确认'}。",
            f"- **当前待补**：{'；'.join(str(item) for item in plan.get('missing_data', [])) or '无'}。",
            f"- **风险边界**：{'；'.join(str(item) for item in plan.get('risk_controls', [])) or '仍需人工复核'}",
        ]
    )
    return "\n".join(lines)


def build_primary_processing_flow(result: dict[str, Any]) -> str:
    """Build the deterministic processing block that must precede model prose.

    The processing route and evidence table are generated from structured tool
    output instead of trusting the summarization model to reproduce them.  The
    HTML comments let the Streamlit renderer replace this text block with the
    richer structured cards without losing it from persisted chat history.
    """
    plan = result.get("processing_plan") or {}
    if not plan:
        return ""
    plan_text = summarize_processing_plan(plan)
    parameterized_text = parameterized_plan_markdown(
        result.get("parameterized_plan") or {},
        result.get("parameter_groups") or [],
        result.get("processing_intent") or {},
    )
    return "\n\n".join(
        part
        for part in (
            PROCESSING_FLOW_START,
            plan_text,
            parameterized_text,
            PROCESSING_FLOW_END,
        )
        if part
    )


def ensure_primary_processing_flow(result: dict[str, Any], answer: str) -> str:
    """Guarantee that a complete route follows the recommendation.

    Checking for a natural-language heading is insufficient because a model can
    mention "完整加工流程" without actually returning the route.  Only the
    deterministic marker counts as a complete injected processing block.
    """
    normalized_answer = str(answer or "").strip()
    if PROCESSING_FLOW_START in normalized_answer:
        return normalized_answer
    processing_flow = build_primary_processing_flow(result)
    if not processing_flow:
        return normalized_answer
    if not normalized_answer:
        return processing_flow
    if re.match(r"^\s*#{1,6}\s+", normalized_answer):
        return processing_flow + "\n\n" + normalized_answer
    return processing_flow + "\n\n### 简明结论\n\n" + normalized_answer


def strip_primary_processing_flow(answer: str) -> str:
    """Remove the deterministic text block when the UI renders structured cards."""
    text = str(answer or "")
    start = text.find(PROCESSING_FLOW_START)
    if start < 0:
        return text.strip()
    end = text.find(PROCESSING_FLOW_END, start)
    if end < 0:
        return text.strip()
    remaining = text[:start] + text[end + len(PROCESSING_FLOW_END) :]
    return remaining.strip()


_REFERENCE_SECTION_LABELS = (
    "本次引用文献",
    "参考文献",
    "文献证据",
    "原文证据",
    "证据来源",
    "来源与页码",
)
_INLINE_CITATION_PATTERN = re.compile(
    r"\s*[\[【（(]\s*文献\s*\d+(?:\s*[,，、-]\s*(?:文献\s*)?\d+)*\s*[\]】）)]",
    flags=re.IGNORECASE,
)


def _compact_answer_text(value: str, max_chars: int) -> str:
    """Remove bibliography UI data and cap unexpectedly long model prose."""
    output: list[str] = []
    skipping_reference_section = False
    for line in str(value or "").splitlines():
        heading_match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        label_source = heading_match.group(1) if heading_match else line
        normalized_label = re.sub(r"[*_`~：:\s]", "", label_source)
        is_reference_heading = any(
            normalized_label == label
            or (
                normalized_label.startswith(label)
                and (heading_match is not None or len(normalized_label) <= 18)
            )
            for label in _REFERENCE_SECTION_LABELS
        )
        if is_reference_heading:
            skipping_reference_section = True
            continue
        if skipping_reference_section:
            if not heading_match:
                continue
            skipping_reference_section = False

        # A model can emit a bibliography without a heading. Drop metadata-like
        # citation rows while retaining ordinary evidence-grounded conclusions.
        if re.match(r"^\s*(?:[-*+]\s*)?\[?文献\s*\d+", line, flags=re.IGNORECASE) and re.search(
            r"(?:第\s*\d+\s*页|页码|DOI\b|来源[：:])",
            line,
            flags=re.IGNORECASE,
        ):
            continue
        cleaned_line = _INLINE_CITATION_PATTERN.sub("", line)
        cleaned_line = re.sub(r"[ \t]+([，。！？；：])", r"\1", cleaned_line)
        output.append(cleaned_line.rstrip())

    compact = re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()
    if len(compact) <= max_chars:
        return compact

    if max_chars <= 1:
        return "…"[:max_chars]
    content_limit = max_chars - 1
    candidate = compact[:content_limit]
    minimum_boundary = content_limit * 3 // 5
    boundaries = [
        candidate.rfind(mark)
        for mark in ("。", "！", "？", "；", "\n")
    ]
    boundary = max((index for index in boundaries if index >= minimum_boundary), default=-1)
    if boundary >= 0:
        candidate = candidate[: boundary + 1]
    return candidate.rstrip(" \n，、；：") + "…"


def compact_primary_answer(answer: str, max_chars: int = 600) -> str:
    """Keep the visible narrative concise while preserving structured flow data."""
    text = str(answer or "")
    start = text.find(PROCESSING_FLOW_START)
    if start < 0:
        return _compact_answer_text(text, max_chars)
    end = text.find(PROCESSING_FLOW_END, start)
    if end < 0:
        return _compact_answer_text(text, max_chars)
    end += len(PROCESSING_FLOW_END)
    structured_flow = text[start:end].strip()
    leading_narrative = _compact_answer_text(text[:start], max_chars)
    remaining_chars = max_chars - len(leading_narrative)
    trailing_narrative = (
        _compact_answer_text(text[end:], remaining_chars)
        if remaining_chars > 0
        else ""
    )
    return "\n\n".join(
        part for part in (leading_narrative, structured_flow, trailing_narrative) if part
    )


def summarize_result(result: dict[str, Any], report_path: Path) -> str:
    return build_evidence_grounded_fallback(result, report_path)


def _short_evidence_text(text: str, limit: int = 420) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return normalized if len(normalized) <= limit else normalized[:limit].rstrip() + "…"


def build_evidence_grounded_fallback(
    result: dict[str, Any],
    report_path: Path,
    notes: list[str] | None = None,
) -> str:
    """Build a concise local answer while evidence remains in ``result`` for the UI."""
    _ = report_path
    scores = result.get("scores", [])
    top = scores[0] if scores else None
    risks = result.get("quality_risks", [])
    primary_processing_flow = build_primary_processing_flow(result)
    actions = result.get("next_actions", [])
    top_reasons = [str(item).strip() for item in _item_value(top, "reasons", []) if str(item).strip()]
    reason_text = _short_evidence_text("；".join(top_reasons[:2]), limit=180)
    action_lines = [f"- {str(action).strip()}" for action in actions[:3] if str(action).strip()]
    risk_lines = [
        f"- [{_item_value(item, 'level', '提示')}] {_item_value(item, 'item', '风险项')}："
        f"{_item_value(item, 'suggestion', '需人工复核')}"
        for item in risks[:2]
    ]

    sections = [
        "### 结论",
        "",
        f"**推荐方向**：{_item_value(top, 'direction', '暂无')}"
        f"（{_item_value(top, 'match_level', '待评估')}）。",
        reason_text or "当前信息不足，先补齐关键数据再确认路线。",
        "",
        primary_processing_flow,
        "",
        "**下一步动作**：",
        *(action_lines or ["- 补齐关键数据后开展小试。"]),
        "",
        "**质控风险**：",
        *(risk_lines or ["- 暂未触发额外风险项；成品仍须人工放行。"]),
    ]
    return compact_primary_answer("\n".join(str(item) for item in sections))


def append_used_reference_index(answer: str, evidence: list[dict[str, Any]]) -> str:
    """Compatibility shim: references are rendered from ``evidence`` in the UI."""
    _ = evidence
    return compact_primary_answer(answer)


def build_previous_evidence_answer(result: dict[str, Any]) -> str:
    """Return the exact evidence used by the previous batch turn without a new model guess."""
    evidence = list(result.get("evidence") or [])
    if not evidence:
        return "上一轮批次分析没有检索到可回查的文献证据。"
    prior_answer = str(result.get("answer") or "")
    used_numbers = sorted(
        {
            int(number)
            for number in re.findall(r"文献\s*(\d+)", prior_answer)
            if 1 <= int(number) <= len(evidence)
        }
    ) or list(range(1, len(evidence) + 1))
    lines = ["以下是上一轮回答实际引用的文献；若上一轮未形成正文引用，则列出当轮全部检索证据：", ""]
    for number in used_numbers:
        item = evidence[number - 1]
        page = item.get("page") or item.get("page_start")
        locator = f"第{page}页" if page else "页码未标注"
        category = item.get("category") or item.get("product") or "未分类"
        source = item.get("doi") or item.get("publication") or item.get("source_file") or "本地文献"
        excerpt = _short_evidence_text(item.get("chunk_text") or "", limit=260)
        lines.extend(
            [
                f"[文献{number}] {item.get('title') or '未命名文献'}",
                f"年份：{item.get('year') or '未知'}；类别：{category}；定位：{locator}；来源：{source}",
                f"上一轮使用的证据片段：{excerpt}",
                "",
            ]
        )
    lines.append("以上为数据库原文切片，正式采用前仍应回查完整原文、实验条件和适用边界。")
    return "\n".join(lines).strip()


_FALSE_IMAGE_STATE_PATTERN = re.compile(
    r"(?:没有|没|未)(?:收到|检测到|读取到|获得|拿到)"
    r"[^，。！？；\n]{0,40}(?:图片|照片|图像|视觉|识别|调用结果)"
    r"|(?:图片|照片|图像)[^，。！？；\n]{0,24}(?:未|没有|没)(?:收到|上传|读取|识别)"
)


def ensure_vision_status_consistency(answer: str, vision_result: dict[str, Any] | None) -> str:
    """Remove false image-missing claims after a successful vision response."""
    text = str(answer or "").strip()
    if not vision_result:
        return text

    parts = re.split(r"(?<=[。！？])", text)
    cleaned = "".join(part for part in parts if not _FALSE_IMAGE_STATE_PATTERN.search(part)).strip()
    if not cleaned:
        cleaned = str(
            vision_result.get("answer")
            or vision_result.get("appearance_description")
            or "视觉模型已完成分析，但没有返回可展示的文字结论。"
        ).strip()

    status_line = "图片接收状态：已接收，并已由视觉模型完成本轮分析。"
    if status_line in cleaned:
        return cleaned
    return f"{status_line}\n\n{cleaned}".strip()


def append_critical_input_notes(answer: str, notes: list[str] | None) -> str:
    """Expose only actionable input/model failures; routine telemetry stays in payload data."""
    concise_notes: list[str] = []
    for raw_note in notes or []:
        note = str(raw_note or "").strip()
        if not note or note.startswith(("已调用视觉模型", "本轮未获得图片识别结果")):
            continue
        if note.startswith("DeepSeek 文献综合失败"):
            note = "语言模型总结暂不可用，当前显示本地分析结果。"
        if note in answer or note in concise_notes:
            continue
        concise_notes.append(note)
        if len(concise_notes) == 2:
            break
    if not concise_notes:
        return answer
    return answer.rstrip() + "\n\n需处理：" + "；".join(
        note.rstrip("。； ") for note in concise_notes
    ) + "。"


def run_vision_turn(
    user_prompt: str,
    image_bytes: bytes,
    image_mime_type: str = "image/jpeg",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    _notify(progress_callback, "正在调用视觉模型分析上传图片")
    vision_result = recognize_citrus_image(
        image_bytes,
        image_mime_type,
        user_prompt=user_prompt,
    )
    answer = str(vision_result.get("answer") or "").strip()
    appearance = str(vision_result.get("appearance_description") or "").strip()
    if appearance and appearance not in answer:
        answer = f"{answer}\n\n图片中可见外观：{appearance}".strip()
    if not answer:
        answer = "视觉模型没有返回可用的图片分析结果，请更换图片后重试。"
    answer = ensure_vision_status_consistency(answer, vision_result)
    return {
        "answer": answer,
        "vision_result": vision_result,
        "image_observation": appearance,
        "vision_status": "success",
    }


def run_analysis_turn(
    user_prompt: str,
    api_key: str,
    history: list[dict[str, str]],
    current_batch: dict[str, Any] | None = None,
    manual_observation: str = "",
    has_image: bool = False,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/jpeg",
    progress_callback: ProgressCallback | None = None,
    memory_context: dict[str, Any] | None = None,
    retrieval_mode: str = "quick",
) -> dict[str, Any]:
    _notify(progress_callback, "正在理解批次信息并抽取关键字段")
    batch, extracted_observation, notes = extract_batch_from_text(user_prompt, current_batch)
    vision_result: dict[str, Any] | None = None
    vision_observation = ""
    vision_status = "not_requested"
    vision_error = ""

    if image_bytes:
        try:
            _notify(progress_callback, "正在调用视觉模型识别柑橘外观")
            vision_result = recognize_citrus_image(
                image_bytes,
                image_mime_type,
                user_prompt=user_prompt,
            )
            vision_observation = vision_result.get("appearance_description", "")
            vision_status = "success"
            notes.append("已调用视觉模型识别上传图片，识别结果已进入本轮加工分析。")
        except Exception as error:
            vision_status = "failed"
            vision_error = str(error)
            notes.append(f"视觉模型识别失败：{error}")
    elif has_image:
        vision_status = "missing_bytes"
        notes.append("已收到图片，但没有读取到图片数据；请重新上传后再分析。")

    observation_parts = [part for part in [vision_observation, manual_observation.strip(), extracted_observation] if part]
    image_observation = "；".join(dict.fromkeys(observation_parts))
    if not image_observation:
        notes.append("本轮未获得图片识别结果或人工外观描述，报告中的外观字段会留空。")

    result = run_demo_agent(
        batch,
        image_observation,
        progress_callback=progress_callback,
        analysis_question=user_prompt,
        retrieval_mode=retrieval_mode,
    )
    result["vision_status"] = vision_status
    result["vision_answer"] = str((vision_result or {}).get("answer") or "")
    result["vision_error"] = vision_error
    _notify(progress_callback, "正在保存报告并写入审计记录")
    report_path = save_report(result["report"], str(batch.get("batch_id") or "batch"))
    write_audit_event(result, report_path)

    _notify(progress_callback, "正在整理批次事实、文献证据和完整决策链")
    summary = build_evidence_grounded_fallback(result, report_path, notes)

    llm_answer = ""
    model_context_manifest: dict[str, Any] = {}
    if api_key:
        try:
            _notify(progress_callback, "正在请求 DeepSeek 综合批次数据与文献证据")
            messages = build_chat_messages(
                result,
                history,
                user_prompt
                + "\n\n"
                + """
请输出本轮可以直接展示给用户的简明主回答：
1. 首句直接给出首选方向和适用性判断，不复述整批输入。
2. 只列最多 3 个最优先行动；必要时再用 1 句说明人工复核边界。
3. 文献用于内部校验，不在正文显示引用编号、题名、年份、页码、DOI、证据片段或参考文献清单；这些内容由下方折叠区展示。
4. 完整加工流程、参数表、设备清单、备选路线和报告已在结构化区域展示，正文不要重复。
5. 若视觉模型状态为“已接收图片，并已完成视觉模型分析”，直接使用视觉结论，不得声称未收到图片。
6. 正文控制在 280～500 个中文字，句子短，结论和风险不重复。
""".strip(),
                memory_context=memory_context,
            )
            model_context_manifest = describe_model_messages(messages)
            llm_answer = chat_with_deepseek(api_key, messages)
        except DeepSeekAPIError as error:
            notes.append(f"DeepSeek 文献综合失败，当前展示本地可回查版本：{error}")
            summary = build_evidence_grounded_fallback(result, report_path, notes)

    narrative_answer = compact_primary_answer(llm_answer or summary)
    answer = ensure_primary_processing_flow(result, narrative_answer)
    answer = append_used_reference_index(answer, result.get("evidence", []))
    answer = ensure_vision_status_consistency(answer, vision_result)
    answer = append_critical_input_notes(answer, notes)
    result["input_notes"] = list(notes)
    result["answer"] = answer

    return {
        "batch": batch,
        "image_observation": image_observation,
        "result": result,
        "report_path": report_path,
        "summary": summary,
        "llm_answer": llm_answer,
        "answer": answer,
        "vision_result": vision_result,
        "model_context_manifest": model_context_manifest,
        "memory_context_manifest": (memory_context or {}).get("manifest", {}),
        "retrieval_mode": result.get("retrieval_mode") or retrieval_mode,
        "deep_retrieval_stats": result.get("deep_retrieval_stats") or {},
    }







