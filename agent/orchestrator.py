from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .evidence import format_key_conclusions_markdown
from .llm_client import DeepSeekAPIError, build_chat_messages, chat_with_deepseek
from .memory import describe_model_messages
from .report import parameterized_plan_markdown
from .vision_client import VisionAPIError, recognize_citrus_image
from .workflow import run_demo_agent, save_report, write_audit_event


CUSTOMER_OPTIONS = ["陈皮经销商", "茶饮品牌", "食品加工厂"]
PROCESSING_FLOW_START = "<!-- citrus-agent-processing-flow:start -->"
PROCESSING_FLOW_END = "<!-- citrus-agent-processing-flow:end -->"
KEY_CONCLUSION_EVIDENCE_START = "<!-- citrus-agent-key-conclusion-evidence:start -->"
KEY_CONCLUSION_EVIDENCE_END = "<!-- citrus-agent-key-conclusion-evidence:end -->"
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
LITERATURE_SOURCE_KEYWORDS = [
    "文献",
    "论文",
    "研究",
    "参考资料",
    "学术资料",
    "literature",
    "paper",
]
LITERATURE_SYNTHESIS_KEYWORDS = [
    "总结",
    "摘要",
    "归纳",
    "整理",
    "汇总",
    "综述",
    "梳理",
    "概括",
    "提炼",
    "解读",
    "研究进展",
    "主要结论",
    "summarize",
    "summary",
    "review",
]
ACTIONABLE_PROCESSING_KEYWORDS = [
    "推荐",
    "建议",
    "设定",
    "设置",
    "定为",
    "取值",
    "最佳",
    "最优",
    "应该",
    "应当",
    "制定",
    "加工方案",
    "加工路线",
    "生产流程",
    "加工流程",
    "完整流程",
    "生产参数",
    "工艺参数",
    "质控方案",
    "小试方案",
    "出报告",
    "生成报告",
]
PROCESSING_PARAMETER_TOPICS = [
    "杀菌",
    "巴氏",
    "灭菌",
    "干燥",
    "烘干",
    "提取",
    "酶解",
    "澄清",
    "过滤",
    "均质",
    "脱气",
    "灌装",
    "浓缩",
    "发酵",
    "温度",
    "时间",
    "压力",
    "流量",
    "浓度",
    "料液比",
    "ph",
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


def _is_literature_synthesis_request(text: str) -> bool:
    """Identify requests to explain reported literature rather than make a batch decision."""
    normalized = re.sub(r"\s+", "", text.lower())
    return _has_any(normalized, LITERATURE_SOURCE_KEYWORDS) and _has_any(
        normalized,
        LITERATURE_SYNTHESIS_KEYWORDS,
    )


def _has_actionable_processing_intent(text: str) -> bool:
    """Keep parameter recommendations on the controlled batch-analysis route."""
    normalized = re.sub(r"\s+", "", text.lower())
    return _has_any(normalized, ACTIONABLE_PROCESSING_KEYWORDS)


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
    if _is_literature_synthesis_request(normalized):
        return False
    if len(normalized) > 80:
        return False
    if any(
        term in normalized
        for term in ["上面", "刚才", "上一轮", "前面", "之前", "引用", "用到", "采用", "检索到"]
    ):
        return True
    if normalized in {"文献", "论文", "依据", "来源", "参考文献", "参考资料"}:
        return True

    # A short source-only request ("单独把文献给我") is an ellipsis.  A topical
    # request ("列出橙汁杀菌文献") leaves subject words behind and starts a new
    # literature question instead of silently inheriting the current batch.
    residual = normalized
    request_fillers = [
        "参考文献",
        "参考资料",
        "单独",
        "这些",
        "相关",
        "文献",
        "论文",
        "依据",
        "来源",
        "请",
        "麻烦",
        "能否",
        "可以",
        "把",
        "将",
        "给我",
        "发我",
        "列出来",
        "列出",
        "展开",
        "一下",
        "呢",
        "吗",
    ]
    for filler in request_fillers:
        residual = residual.replace(filler, "")
    return not residual


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
    literature_synthesis = _is_literature_synthesis_request(normalized)
    actionable_processing = _has_actionable_processing_intent(normalized)
    if literature_synthesis and not actionable_processing:
        return False
    has_general_knowledge_intent = _has_any(normalized, GENERAL_KNOWLEDGE_KEYWORDS)
    has_analysis_intent = _has_any(normalized, TOOL_INTENT_KEYWORDS) or actionable_processing
    has_batch_topic = _has_any(
        normalized,
        BATCH_REFERENCE_KEYWORDS + DOMAIN_KEYWORDS + IMAGE_INTENT_KEYWORDS,
    ) or (actionable_processing and _has_any(normalized, PROCESSING_PARAMETER_TOPICS))
    if has_general_knowledge_intent and not actionable_processing and not references_current_batch(text):
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
    literature_synthesis = _is_literature_synthesis_request(normalized)
    actionable_processing = _has_actionable_processing_intent(normalized)
    if literature_synthesis and not actionable_processing:
        return False
    has_general_knowledge_intent = _has_any(normalized, GENERAL_KNOWLEDGE_KEYWORDS)
    has_tool_intent = _has_any(normalized, TOOL_INTENT_KEYWORDS) or actionable_processing
    has_batch_reference = _has_any(normalized, BATCH_REFERENCE_KEYWORDS)
    has_strong_batch_data = _has_any(normalized, BATCH_DATA_KEYWORDS) or bool(
        re.search(r"\d+(?:\.\d+)?\s*(?:%|kg|公斤|千克|brix|bx|°brix)", normalized, flags=re.IGNORECASE)
    )
    has_weak_batch_data = _has_any(normalized, WEAK_BATCH_DATA_KEYWORDS)
    has_domain = _has_any(normalized, DOMAIN_KEYWORDS)
    has_image_intent = _has_any(normalized, IMAGE_INTENT_KEYWORDS)

    if (
        has_general_knowledge_intent
        and not actionable_processing
        and not (has_batch_reference or has_strong_batch_data)
    ):
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
    return processing_flow + "\n\n### 综合判断\n\n" + normalized_answer


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
    "引用文献",
    "参考资料",
    "文献证据",
    "原文证据",
    "证据来源",
    "来源与页码",
    "参考文献及来源",
)
_INLINE_CITATION_PATTERN = re.compile(
    r"\s*[\[【（(]\s*文献\s*\d+(?:\s*[,，、-]\s*(?:文献\s*)?\d+)*\s*[\]】）)]",
    flags=re.IGNORECASE,
)


def _deduplicate_repeated_sentences(value: str) -> str:
    """Drop exact sentence repeats while leaving distinct reasoning intact."""
    parts = re.split(r"(?<=[。！？])", value)
    if len(parts) <= 1:
        return value
    output: list[str] = []
    seen: set[str] = set()
    for part in parts:
        comparable = re.sub(r"[*_`~\s]", "", part).strip()
        if comparable and comparable in seen:
            continue
        if comparable:
            seen.add(comparable)
        output.append(part)
    return "".join(output)


def _compact_answer_text(value: str, max_chars: int | None = None) -> str:
    """Remove repeated lines and reference metadata without shortening the answer."""
    _ = max_chars  # Retained for compatibility with already-running UI modules.
    output: list[str] = []
    seen_content: set[str] = set()
    skipping_reference_section = False
    for line in str(value or "").splitlines():
        heading_match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        label_source = heading_match.group(1) if heading_match else line
        normalized_label = re.sub(r"[*_`~：:\s]", "", label_source)
        base_label = re.sub(
            r"[（(][^）)]*[）)]$",
            "",
            normalized_label,
        )
        is_reference_heading = base_label in _REFERENCE_SECTION_LABELS
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
        cleaned_line = _deduplicate_repeated_sentences(cleaned_line)
        comparable = re.sub(
            r"[*_`~\s]",
            "",
            re.sub(r"^\s*(?:[-*+]\s*|\d+[.、]\s*)", "", cleaned_line),
        )
        if cleaned_line.strip() and not heading_match:
            if comparable in seen_content:
                continue
            seen_content.add(comparable)
        output.append(cleaned_line.rstrip())

    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


def compact_primary_answer(answer: str, max_chars: int | None = None) -> str:
    """Clean the visible narrative while preserving all substantive content."""
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
    trailing_narrative = _compact_answer_text(text[end:], max_chars)
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
    """Build a complete local answer while source metadata remains in the UI."""
    _ = report_path

    def unique_text(items: Iterable[Any]) -> list[str]:
        return list(
            dict.fromkeys(
                str(item).strip().rstrip("。；; ")
                for item in items
                if str(item).strip()
            )
        )

    def substantive_reasons(item: Any) -> list[str]:
        return [
            reason
            for reason in unique_text(_item_value(item, "reasons", []))
            if not re.search(
                r"(?:本轮)?检索到\s*\d+\s*篇|已纳入路线排序|"
                r"(?:原文|页码|DOI|来源)复核",
                reason,
                flags=re.IGNORECASE,
            )
        ]

    def concise_evidence_support(item: Any) -> str:
        support = str(_item_value(item, "evidence_support", "未评估"))
        return re.sub(r"[（(][^）)]*(?:篇|条)[^）)]*[）)]", "", support).strip()

    scores = result.get("scores", [])
    top = scores[0] if scores else None
    risks = result.get("quality_risks", [])
    primary_processing_flow = build_primary_processing_flow(result)
    actions = result.get("next_actions", [])
    top_reasons = substantive_reasons(top)
    top_risk_notes = unique_text(_item_value(top, "risk_notes", []))
    alternatives = list(
        {
            str(_item_value(item, "direction", "备选方向")): item
            for item in scores[1:]
        }.values()
    )[:3]
    alternative_lines: list[str] = []
    used_reasons = set(top_reasons)
    has_shared_alternative_basis = False
    for item in alternatives:
        reasons = [reason for reason in substantive_reasons(item) if reason not in used_reasons]
        used_reasons.update(reasons)
        if not reasons:
            has_shared_alternative_basis = True
        reason_text = f"{'；'.join(reasons)}。" if reasons else ""
        alternative_lines.append(
            f"- **{_item_value(item, 'direction', '备选方向')}**："
            f"{_item_value(item, 'match_level', '待评估')}；"
            f"文献支持为{concise_evidence_support(item)}，"
            f"数据置信度为{_item_value(item, 'data_confidence', '低')}。"
            f"{reason_text}"
        )
    if has_shared_alternative_basis:
        alternative_lines.append(
            "- 以上未单列理由的备选与首选共享当前原料基础，"
            "需按目标产品、设备能力和小试结果比较取舍。"
        )
    action_lines = [f"- {action}" for action in unique_text(actions)]
    risk_lines = list(
        dict.fromkeys(
            f"- [{_item_value(item, 'level', '提示')}] {_item_value(item, 'item', '风险项')}："
            f"{_item_value(item, 'suggestion', '需人工复核')}"
            for item in risks
        )
    )
    risk_lines.extend(f"- {item}" for item in top_risk_notes)

    sections = [
        "### 综合判断",
        "",
        f"**推荐方向**：{_item_value(top, 'direction', '暂无')}；适配等级为"
        f" **{_item_value(top, 'match_level', '待评估')}**，文献支持为"
        f" **{concise_evidence_support(top)}**，数据置信度为"
        f" **{_item_value(top, 'data_confidence', '低')}**。"
        "该方向仍应以当前批次检测和小试结果作为最终定案依据。",
        "",
        primary_processing_flow,
        "",
        "### 推荐理由与重要备选",
        "",
        f"**首选依据**：{'；'.join(top_reasons) or '当前结构化信息有限，需补充数据后复核'}。",
        *(alternative_lines or ["- 当前没有形成需要优先比较的备选方向。"]),
        "",
        "### 关键风险",
        "",
        *(risk_lines or ["- 暂未触发额外风险项，成品仍须按批次人工复核和放行。"]),
        "",
        "### 下一步行动",
        "",
        *(action_lines or ["- 补齐关键数据，并围绕首选方向开展小试验证。"]),
    ]
    return compact_primary_answer("\n".join(str(item) for item in sections))


def append_used_reference_index(answer: str, evidence: list[dict[str, Any]]) -> str:
    """Compatibility shim: references are rendered from ``evidence`` in the UI."""
    _ = evidence
    return compact_primary_answer(answer)


def strip_key_conclusion_evidence(answer: str) -> str:
    """Remove deterministic evidence cards before reusing an answer as model context."""
    text = str(answer or "")
    start = text.find(KEY_CONCLUSION_EVIDENCE_START)
    if start < 0:
        return text.strip()
    end = text.find(KEY_CONCLUSION_EVIDENCE_END, start)
    if end < 0:
        return text[:start].strip()
    return (text[:start] + text[end + len(KEY_CONCLUSION_EVIDENCE_END) :]).strip()


def append_key_conclusion_evidence(
    answer: str,
    conclusions: list[dict[str, Any]],
) -> str:
    """Attach concise, traceable cards without another model call."""
    narrative = strip_key_conclusion_evidence(answer)
    cards = format_key_conclusions_markdown(
        conclusions,
        heading="### 关键结论证据卡",
        max_items=8,
        max_references=1,
        excerpt_chars=240,
    )
    if not cards:
        return narrative
    block = f"{KEY_CONCLUSION_EVIDENCE_START}\n{cards}\n{KEY_CONCLUSION_EVIDENCE_END}"
    return "\n\n".join(part for part in (narrative, block) if part)


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
请输出本轮可以直接展示给用户的完整主回答，而不是几句简略提示：
1. 先给出首选方向、适用性判断及成立条件，不逐字段复述整批输入。
2. 解释首选方向的关键理由，并比较重要备选方向的适用条件、取舍和不优先原因。
3. 把文献中的研究结论、条件和局限真正用于分析，但正文不得显示引用编号、题名、年份、页码、DOI、匹配分、原文片段或参考文献清单；这些来源信息由下方“参考依据”展示。
4. 完整加工流程、分阶段操作、参数表和设备信息已在结构化方案中完整展示，正文不要重复抄写，也不要说明检索过程、候选片段数、采用文献数或证据目录；不得以去重为由省略判断、理由、备选、风险或行动。
5. 单列关键质控风险、结论边界和有先后顺序的下一步行动。行动数量按问题实际需要决定，不设固定上限。
6. 回答要具体、有条件、有证据、可执行，避免“加强管理、注意质量”一类空泛表述；同一事实、结论或风险只表达一次。
7. 任何药典、法规、标准、行业共识、具体参数或研究结论必须由本轮证据明确支持；证据未覆盖时说明缺口及其影响，不要凭模型记忆补充。
8. 若分析上下文显示视觉模型状态为“已接收图片，并已完成视觉模型分析”，直接使用视觉结论，不得声称未收到图片或识别调用结果，只说明无法仅凭外观确定的边界。
9. 使用“综合判断”“推荐理由与重要备选”“关键风险”“下一步行动”等清晰小标题组织答案，不设置固定字数或条目上限。
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
    answer = append_key_conclusion_evidence(answer, result.get("key_conclusions", []))
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







