from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .llm_client import DeepSeekAPIError, build_chat_messages, chat_with_deepseek
from .vision_client import VisionAPIError, recognize_citrus_image
from .workflow import run_demo_agent, save_report, write_audit_event


CUSTOMER_OPTIONS = ["陈皮经销商", "茶饮品牌", "食品加工厂"]
TEST_LABELS = {
    "pesticide": "农残",
    "heavy_metal": "重金属",
    "microbe": "微生物",
    "aflatoxin": "黄曲霉毒素",
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
]
BATCH_REFERENCE_KEYWORDS = ["这批", "一批", "当前批次", "当前", "批次", "原料", "样品", "这批货", "一批货", "当前原料"]
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
ProgressCallback = Callable[[str], None]


def _notify(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback:
        progress_callback(message)


def default_batch() -> dict[str, Any]:
    return {
        "batch_id": f"B{uuid4().hex[:8].upper()}",
        "origin": "新会",
        "variety": "茶枝柑",
        "harvest_date": str(date.today()),
        "weight_kg": "",
        "brix": "",
        "acidity": "",
        "moisture": "",
        "customer_type": "陈皮经销商",
        "pesticide": False,
        "heavy_metal": False,
        "microbe": False,
        "aflatoxin": False,
    }


def _has_any(text: str, keywords: list[str]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def should_run_tools(text: str, has_image: bool = False, has_current_batch: bool = False) -> bool:
    """Decide whether to run the batch-analysis tool chain instead of general chat."""
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


def _detect_test_state(text: str, label: str) -> bool | None:
    if label not in text:
        return None
    near = text[max(0, text.find(label) - 8) : text.find(label) + len(label) + 8]
    if any(word in near for word in ["无", "没", "未", "缺", "没有", "未做", "缺少"]):
        return False
    if any(word in near for word in ["有", "已", "完成", "通过", "合格", "报告"]):
        return True
    return None


def extract_batch_from_text(text: str, current_batch: dict[str, Any] | None = None) -> tuple[dict[str, Any], str, list[str]]:
    batch = {**default_batch(), **(current_batch or {})}
    notes: list[str] = []

    origin_match = re.search(r"(?:产地|来自|来源|原产地)[:：\s]*([\u4e00-\u9fa5A-Za-z0-9]{2,12})", text)
    if origin_match:
        batch["origin"] = origin_match.group(1)
    else:
        for origin in ["新会", "赣南", "宜昌", "秭归", "广西", "福建", "云南", "四川"]:
            if origin in text:
                batch["origin"] = origin
                break

    for variety in ["茶枝柑", "脐橙", "甜橙", "砂糖橘", "沃柑", "金桔", "金橘", "柚", "柠檬", "柑橘", "橙"]:
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

    batch["weight_kg"] = _first_number([r"(?:重量|总量|批量)[^\d]{0,6}(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)", r"(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)"], text) or batch.get("weight_kg", "")
    batch["brix"] = _first_number([r"(?:糖度|brix|Brix)[^\d]{0,6}(\d+(?:\.\d+)?)", r"(\d+(?:\.\d+)?)\s*(?:°?Brix|Bx)"], text) or batch.get("brix", "")
    batch["acidity"] = _first_number([r"(?:酸度|总酸)[^\d]{0,6}(\d+(?:\.\d+)?)"], text) or batch.get("acidity", "")
    batch["moisture"] = _first_number([r"(?:水分|含水率)[^\d]{0,6}(\d+(?:\.\d+)?)\s*%?"], text) or batch.get("moisture", "")

    for key, label in TEST_LABELS.items():
        state = _detect_test_state(text, label)
        if state is not None:
            batch[key] = state

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


def summarize_result(result: dict[str, Any], report_path: Path) -> str:
    scores = result.get("scores", [])
    top = scores[0] if scores else None
    risks = result.get("quality_risks", [])
    evidence = result.get("evidence", [])
    actions = result.get("next_actions", [])
    return f"""
### Agent 已完成批次分析

**推荐方向**：{_item_value(top, 'direction', '暂无')}  
**最高评分**：{_item_value(top, 'score', 0)}/100  
**质控风险**：{len(risks)} 项  
**文献证据**：{len(evidence)} 条  
**报告文件**：`{report_path}`

**下一步动作**：
{chr(10).join(f'- {action}' for action in actions) or '- 暂无'}

我已经调用本地文献库、规则评分、质控风险和报告生成工具。下面的工具过程和报告草稿可展开查看。
""".strip()


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
) -> dict[str, Any]:
    _notify(progress_callback, "正在理解批次信息并抽取关键字段")
    batch, extracted_observation, notes = extract_batch_from_text(user_prompt, current_batch)
    vision_result: dict[str, Any] | None = None
    vision_observation = ""

    if image_bytes:
        try:
            _notify(progress_callback, "正在调用视觉模型识别柑橘外观")
            vision_result = recognize_citrus_image(image_bytes, image_mime_type)
            vision_observation = vision_result.get("appearance_description", "")
            notes.append("已调用视觉模型识别上传图片，识别结果已进入本轮加工分析。")
        except (VisionAPIError, Exception) as error:
            notes.append(f"视觉模型识别失败：{error}")
    elif has_image:
        notes.append("已收到图片，但没有读取到图片数据；请重新上传后再分析。")

    observation_parts = [part for part in [vision_observation, manual_observation.strip(), extracted_observation] if part]
    image_observation = "；".join(dict.fromkeys(observation_parts))
    if not image_observation:
        notes.append("本轮未获得图片识别结果或人工外观描述，报告中的外观字段会留空。")

    result = run_demo_agent(batch, image_observation, progress_callback=progress_callback)
    _notify(progress_callback, "正在保存报告并写入审计记录")
    report_path = save_report(result["report"], str(batch.get("batch_id") or "batch"))
    write_audit_event(result, report_path)

    _notify(progress_callback, "正在整理结论、风险边界和下一步动作")
    summary = summarize_result(result, report_path)
    if notes:
        summary += "\n\n**补充说明**：\n" + "\n".join(f"- {note}" for note in notes)

    llm_answer = ""
    if api_key:
        try:
            _notify(progress_callback, "正在请求 DeepSeek 生成对话式总结")
            messages = build_chat_messages(
                result,
                history,
                user_prompt + "\n\n请以 Agent 的口吻总结本轮工具调用结果，先给结论，再给风险边界和下一步动作。",
            )
            llm_answer = chat_with_deepseek(api_key, messages)
        except DeepSeekAPIError as error:
            llm_answer = f"DeepSeek 总结失败：{error}"

    return {
        "batch": batch,
        "image_observation": image_observation,
        "result": result,
        "report_path": report_path,
        "summary": summary,
        "llm_answer": llm_answer,
        "vision_result": vision_result,
    }







