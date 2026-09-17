"""Deterministic intake cleaning and batch decision pipeline.

The UI accepts optional fields, while route decisions need a smaller set of
well defined facts.  This module is the single server side policy for
normalisation, weighted data quality, route ranking and task context.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5


FIELD_POLICY: dict[str, dict[str, Any]] = {
    "organization": {"label": "主体名称", "weight": 4},
    "origin": {"label": "产地", "weight": 10, "required": True},
    "variety": {"label": "品种", "weight": 12, "required": True},
    "batch": {"label": "批次号", "weight": 10, "required": True},
    "harvest_date": {"label": "采收日期", "weight": 6},
    "quantity_kg": {"label": "批次数量", "weight": 8, "required": True},
    "brix": {"label": "糖度", "weight": 10},
    "acidity": {"label": "酸度", "weight": 6},
    "moisture": {"label": "水分", "weight": 5},
    "quality_grade": {"label": "外观/等级", "weight": 6},
    "target_product": {"label": "目标产品", "weight": 7},
    "safety_tests": {"label": "安全检测", "weight": 16, "required": True},
}

_EMPTY = {"", None, "未提供", "待补充", "待填写", "待上传", "未知", "N/A", "n/a", "暂无"}
_NUMBER_FIELDS = {"quantity_kg", "brix", "acidity", "moisture"}


def _text(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _missing(value: Any) -> bool:
    return _text(value) in {str(x) for x in _EMPTY}


def _number(value: Any) -> float | None:
    if _missing(value):
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", _text(value).replace(",", ""))
    try:
        number = float(match.group(0)) if match else float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _date(value: Any) -> str:
    value = _text(value)
    if _missing(value):
        return ""
    value = value.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return value


def flatten_intake(document: dict[str, Any]) -> dict[str, Any]:
    """Map either a saved intake document or the compact demo form to facts."""
    fields = document.get("fields") if isinstance(document.get("fields"), dict) else document
    rows = document.get("rows") if isinstance(document.get("rows"), dict) else {}
    def get(*keys: str) -> Any:
        for key in keys:
            if key in fields and not _missing(fields[key]):
                return fields[key]
        return ""
    material = (rows.get("materials") or [{}])[0] if isinstance(rows.get("materials"), list) else {}
    tests = rows.get("tests") if isinstance(rows.get("tests"), list) else []
    safety_values = [get("quality.testStatus", "inspectionReport", "safety_tests")]
    safety_values += [r.get("conclusion") or r.get("result") for r in tests if isinstance(r, dict)]
    safety = [str(x).strip() for x in safety_values if not _missing(x)]
    return {
        "organization": get("profile.organization", "organization", "supplier"),
        "origin": get("base.origin", "origin") or material.get("origin", ""),
        "variety": get("base.variety", "variety", "material") or material.get("name", ""),
        "batch": get("harvest.batch", "product.batch", "batch") or material.get("batch", ""),
        "harvest_date": get("harvest.date", "harvestDate", "date") or material.get("harvestDate", ""),
        "quantity_kg": get("harvest.quantity", "plannedQuantity", "quantity") or material.get("quantity", ""),
        "unit": get("harvest.unit", "unit") or material.get("unit", "kg"),
        "brix": get("quality.brix", "brix") or material.get("brix", ""),
        "acidity": get("quality.acidity", "acidity") or material.get("acidity", ""),
        "moisture": get("quality.moisture", "moisture"),
        "quality_grade": get("quality.grade", "grade", "specification") or material.get("specification", ""),
        "target_product": get("product.name", "processingProduct", "target_product"),
        "safety_tests": safety,
        "side": document.get("side", "") if isinstance(document, dict) else "",
    }


def clean_intake_record(document: dict[str, Any]) -> dict[str, Any]:
    """Return normalised facts, field level decisions and a weighted score."""
    raw = flatten_intake(document or {})
    normalized = dict(raw)
    normalized["origin"] = _text(raw["origin"])
    normalized["variety"] = _text(raw["variety"])
    normalized["batch"] = re.sub(r"\s+", "-", _text(raw["batch"]).upper())
    normalized["harvest_date"] = _date(raw["harvest_date"])
    quantity = _number(raw["quantity_kg"])
    if _text(raw.get("unit")) in {"吨", "t", "ton", "tons"} and quantity is not None:
        quantity *= 1000
    normalized["quantity_kg"] = round(quantity, 3) if quantity is not None else None
    for key in ("brix", "acidity", "moisture"):
        number = _number(raw[key])
        normalized[key] = round(number, 4) if number is not None else None
    normalized["quality_grade"] = _text(raw["quality_grade"])
    normalized["target_product"] = _text(raw["target_product"])
    normalized["safety_tests"] = list(raw["safety_tests"] or [])

    invalid: list[dict[str, str]] = []
    ranges = {"brix": (0, 40), "acidity": (0, 100), "moisture": (0, 100), "quantity_kg": (0.001, 1e12)}
    for key, (low, high) in ranges.items():
        value = normalized.get(key)
        if value is not None and not low <= value <= high:
            invalid.append({"field": key, "label": FIELD_POLICY[key]["label"], "reason": f"应在 {low:g}—{high:g} 范围内"})
            normalized[key] = None
    if normalized["harvest_date"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized["harvest_date"]):
        invalid.append({"field": "harvest_date", "label": "采收日期", "reason": "日期格式无法识别"})
        normalized["harvest_date"] = ""
    if normalized["batch"] and not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,39}", normalized["batch"]):
        invalid.append({"field": "batch", "label": "批次号", "reason": "仅允许字母、数字、短横线和下划线"})
    missing = [key for key, rule in FIELD_POLICY.items() if rule.get("required") and (not normalized.get(key) or (key == "safety_tests" and not normalized[key]))]
    fields = []
    total_weight = sum(int(rule["weight"]) for rule in FIELD_POLICY.values())
    valid_weight = 0
    for key, rule in FIELD_POLICY.items():
        value = normalized.get(key)
        present = bool(value) and not (key == "safety_tests" and not value)
        bad = any(item["field"] == key for item in invalid)
        status = "有效" if present and not bad else "缺失" if not present else "异常"
        if status == "有效":
            valid_weight += int(rule["weight"])
        fields.append({"field": key, "label": rule["label"], "weight": rule["weight"], "status": status, "value": value})
    ignored = [key for key, value in raw.items() if key not in FIELD_POLICY and not _missing(value)]
    score = round(valid_weight / total_weight * 100)
    return {
        "normalized": normalized,
        "fields": fields,
        "missing": missing,
        "invalid": invalid,
        "ignored": ignored,
        "weighted_score": score,
        "decision_ready": not missing and not invalid,
        "policy_version": "2026.09",
    }


ROUTES = {
    "juice": {"label": "果汁/原汁", "keywords": ("汁", "果汁", "饮料", "NFC"), "base": 58, "process": ["原料验收", "分选清洗", "破碎榨汁", "过滤与脱气", "杀菌灌装", "成品检测与放行"]},
    "peel": {"label": "果皮/陈皮制品", "keywords": ("陈皮", "果皮", "皮", "精油"), "base": 54, "process": ["原料验收", "分选清洗", "剥皮与去杂", "干燥/陈化小试", "分级包装", "成品检测与放行"]},
    "pectin": {"label": "果胶/黄酮提取", "keywords": ("果胶", "黄酮", "提取"), "base": 45, "process": ["原料验收", "预处理", "提取", "固液分离", "浓缩干燥", "指标检测与放行"]},
    "whole_fruit": {"label": "整果/果干", "keywords": ("整果", "果干", "果脯"), "base": 48, "process": ["原料验收", "分级清洗", "切分/预处理", "干燥或糖渍小试", "包装储藏", "成品检测与放行"]},
    "byproduct": {"label": "果渣/副产物综合利用", "keywords": ("副产", "果渣", "饲料", "有机肥"), "base": 38, "process": ["分类收集", "去杂", "干燥或发酵小试", "质量检测", "包装储运", "去向确认"]},
}


def decide_routes(cleaned: dict[str, Any]) -> list[dict[str, Any]]:
    facts = cleaned.get("normalized", cleaned)
    text = " ".join(str(facts.get(k) or "") for k in ("target_product", "variety", "quality_grade"))
    scores = []
    for key, route in ROUTES.items():
        score = route["base"]
        reasons = []
        if any(word.lower() in text.lower() for word in route["keywords"]):
            score += 25; reasons.append("目标产品或用途匹配")
        if key == "juice" and facts.get("brix") is not None:
            score += min(12, max(0, (facts["brix"] - 10) * 2)); reasons.append("糖度已提供")
        if key in {"peel", "pectin"} and facts.get("moisture") is not None:
            score += 8; reasons.append("有果皮水分数据")
        if not facts.get("safety_tests"):
            score -= 12; reasons.append("安全检测资料缺失")
        scores.append({"route": key, "label": route["label"], "score": max(0, min(100, round(score))), "reasons": reasons or ["通用候选路线"], "process": route["process"]})
    scores.sort(key=lambda item: item["score"], reverse=True)
    for index, item in enumerate(scores, 1):
        item["rank"] = index
        item["tier"] = "首选" if index == 1 else "备选" if index <= 3 else "观察"
    return scores


def build_task_context(record_id: str, revision: Any = 1, task_id: str | None = None) -> dict[str, str]:
    record_id = str(record_id or "unpersisted-record")
    # The task belongs to the business batch, not a particular edit.  Revision
    # records change history while task_id stays stable across resubmissions.
    task_id = task_id or "task_" + uuid5(NAMESPACE_URL, f"citrus:{record_id}").hex[:24]
    return {"task_id": task_id, "record_id": record_id, "revision": str(revision or 1)}


def run_intake_pipeline(document: dict[str, Any], record_id: str = "", revision: Any = 1, task_id: str | None = None) -> dict[str, Any]:
    cleaned = clean_intake_record(document)
    routes = decide_routes(cleaned)
    context = build_task_context(
        record_id or str(document.get("id") or "draft"),
        revision,
        task_id or document.get("task_id") or None,
    )
    selected = routes[0] if routes else None
    facts = cleaned["normalized"]
    return {
        "task_context": context,
        "cleaning": cleaned,
        "routes": routes,
        "recommended_route": selected,
        "processing_plan": {"route": selected["label"] if selected else "待补充", "stages": selected["process"] if selected else [], "status": "待补资料/小试复核" if not cleaned["decision_ready"] else "可进入路线评审"},
        "batch_summary": {key: facts.get(key) for key in ("batch", "origin", "variety", "quantity_kg", "brix", "acidity", "moisture", "target_product")},
        "pipeline_version": "2026.09",
    }


__all__ = ["FIELD_POLICY", "clean_intake_record", "decide_routes", "run_intake_pipeline", "build_task_context", "flatten_intake"]
