from __future__ import annotations

import re
from typing import Any, Mapping


DIRECT_EVIDENCE = "直接证据"
REFERENCE_EVIDENCE = "仅供参考"
INSUFFICIENT_EVIDENCE = "证据不足"
EVIDENCE_LEVELS = {DIRECT_EVIDENCE, REFERENCE_EVIDENCE, INSUFFICIENT_EVIDENCE}
EVIDENCE_POLICY_VERSION = "deterministic-v1"

_PENDING_OCR_MARKERS = (
    "题录（待ocr）",
    "题录(待ocr)",
    "待ocr",
    "pending ocr",
    "ocr_pending",
)
_RESULT_SECTION_TERMS = (
    "方法",
    "材料与方法",
    "试验",
    "实验",
    "结果",
    "讨论",
    "结论",
    "method",
    "material",
    "experiment",
    "result",
    "discussion",
    "conclusion",
)
_OUTCOME_TERMS = (
    "结果表明",
    "研究表明",
    "显示",
    "发现",
    "显著",
    "提高",
    "降低",
    "增加",
    "减少",
    "影响",
    "改变",
    "得率",
    "保留率",
    "showed",
    "found",
    "significant",
    "increased",
    "decreased",
    "improved",
    "reduced",
    "affected",
    "changed",
    "yield",
)
_PROCESS_TERMS = (
    "提取",
    "干燥",
    "陈化",
    "榨汁",
    "浓缩",
    "发酵",
    "杀菌",
    "灭菌",
    "包装",
    "储藏",
    "贮藏",
    "冷压",
    "蒸馏",
    "过滤",
    "离心",
    "均质",
    "酶解",
    "extraction",
    "extract",
    "drying",
    "aging",
    "fermentation",
    "pasteur",
    "steril",
    "storage",
    "distillation",
    "filtration",
    "centrifug",
    "homogen",
    "enzym",
)
_CITRUS_TERMS = (
    "柑橘",
    "柑",
    "橘",
    "橙",
    "柚",
    "柠檬",
    "陈皮",
    "广陈皮",
    "茶枝柑",
    "新会柑",
    "citrus",
    "orange",
    "mandarin",
    "tangerine",
    "lemon",
    "pomelo",
    "grapefruit",
    "chenpi",
    "citri reticulatae",
)
_BACKGROUND_TITLE_TERMS = (
    "综述",
    "研究进展",
    "review",
    "meta-analysis",
    "bibliometric",
    "成分分析",
    "含量测定",
    "检测方法",
    "chemical profiling",
)
_CONCEPT_TERMS: dict[str, tuple[str, ...]] = {
    "陈皮": ("陈皮", "广陈皮", "chenpi", "citri reticulatae", "陈化", "aging"),
    "果胶": ("果胶", "pectin", "酯化度", "galacturonic", "凝胶"),
    "精油": ("精油", "挥发油", "essential oil", "volatile oil", "柠檬烯", "limonene"),
    "果汁": ("果汁", "橙汁", "nfc", "juice", "榨汁"),
    "浓缩": ("浓缩汁", "concentrated juice", "浓缩", "concentration"),
    "发酵": ("果醋", "果酒", "发酵", "fermentation", "vinegar", "wine"),
    "干燥": ("干燥", "冻干", "烘干", "drying", "freeze-drying"),
    "种子": ("种子", "籽油", "橘核", "seed oil", "citrus seed"),
    "副产物": ("副产物", "果渣", "by-product", "byproduct", "pomace", "citrus waste"),
}


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    lowered = text.casefold()
    return any(str(term).casefold() in lowered for term in terms if str(term).strip())


def normalize_doi(value: Any) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    raw = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*[:：]?\s*)", "", raw, flags=re.I)
    match = re.search(r"10\.\d{4,9}/[^\s<>\"']+", raw, flags=re.I)
    if not match:
        return ""
    return match.group(0).rstrip(".,;，。；、)]}）】")


def source_url(item: Mapping[str, Any]) -> str:
    doi = normalize_doi(item.get("doi"))
    if doi:
        return f"https://doi.org/{doi}"
    for key in ("source_url", "url", "link"):
        value = _clean_text(item.get(key))
        if re.match(r"^https?://", value, flags=re.I):
            return value
    publication = _clean_text(item.get("publication"))
    return publication if re.match(r"^https?://", publication, flags=re.I) else ""


def compact_excerpt(value: Any, max_chars: int = 360) -> str:
    text = _clean_text(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip("，,；;。 .") + "…"


def build_applicability(
    item: Mapping[str, Any],
    intent: Mapping[str, Any] | None = None,
) -> str:
    intent = intent or {}
    subject = _clean_text(
        item.get("raw_material")
        or item.get("product")
        or item.get("topic")
        or item.get("category")
        or intent.get("raw_material")
    )
    process = _clean_text(
        item.get("process_step")
        or item.get("processing_facet")
        or item.get("retrieval_facet")
        or intent.get("primary_product")
    )
    scale = _clean_text(item.get("scale") or intent.get("scale"))
    method = _clean_text(item.get("process_method") or item.get("method"))
    conditions = compact_excerpt(item.get("conditions"), 120)
    parts: list[str] = []
    if subject:
        parts.append(f"对象/原料：{subject}")
    if process and process not in {"跨类别", "未分类"}:
        parts.append(f"工艺/主题：{process}")
    if scale and scale != "unknown":
        parts.append(f"规模：{scale}")
    if method and method != "未标明方法":
        parts.append(f"方法：{method}")
    if conditions:
        parts.append(f"原文条件：{conditions}")
    if not parts:
        parts.append("仅适用于原文所述研究对象与试验条件")
    parts.append("用于当前批次前仍需核对原料、设备和放大条件")
    return "；".join(dict.fromkeys(parts))


def determine_evidence_level(
    item: Mapping[str, Any],
    intent: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Conservatively classify a retrieved fragment without using an LLM.

    Retrieval similarity is deliberately excluded from the direct-evidence test.
    A high match score can improve ordering, but can never by itself upgrade a
    background or weakly related fragment to direct evidence.
    """
    section = _clean_text(item.get("section"))
    excerpt = _clean_text(item.get("chunk_text"))
    status_text = " ".join(
        _clean_text(item.get(key))
        for key in ("section", "ocr_status", "document_status", "status")
    ).casefold()
    if _contains_any(status_text, _PENDING_OCR_MARKERS):
        return INSUFFICIENT_EVIDENCE, "仅有题录或正文仍待 OCR，不能据题名推测研究结果。"
    if len(excerpt) < 18:
        return INSUFFICIENT_EVIDENCE, "缺少足够的可核验正文片段，不能形成文献直接结论。"

    title = _clean_text(item.get("title"))
    source_identity = bool(
        title
        and any(
            _clean_text(item.get(key))
            for key in ("year", "doi", "publication", "source", "source_file", "document_id")
        )
    )
    locator = bool(
        item.get("page") not in (None, "")
        or item.get("page_start") not in (None, "")
        or item.get("chunk_id") not in (None, "")
        or (section and section.casefold() not in {"正文", "unknown", "未标注章节", "none"})
    )
    if not source_identity or not locator:
        return REFERENCE_EVIDENCE, "正文内容可参考，但来源身份或原文定位不完整，暂不能列为直接证据。"

    source_text = " ".join(
        _clean_text(item.get(key))
        for key in ("title", "category", "product", "topic", "keywords", "chunk_text")
    )
    if _contains_any(title, _BACKGROUND_TITLE_TERMS):
        return REFERENCE_EVIDENCE, "该材料更接近综述、背景或检测分析，不能直接证明当前加工结论。"
    if item.get("context_only"):
        return REFERENCE_EVIDENCE, "该片段仅作为相邻上下文补充，不能脱离主证据独立支撑结论。"

    citrus_aligned = _contains_any(source_text, _CITRUS_TERMS)
    focus_text = " ".join(
        _clean_text(value)
        for value in (
            item.get("processing_facet"),
            item.get("retrieval_facet"),
            item.get("category"),
            item.get("product"),
            (intent or {}).get("primary_product"),
        )
    )
    concept_aligned = False
    for concept, terms in _CONCEPT_TERMS.items():
        if _contains_any(focus_text, (concept, *terms)) and _contains_any(source_text, terms):
            concept_aligned = True
            break
    # Retrieval scores describe search relevance, not scientific support.
    # A high score must never upgrade an off-focus fragment to direct evidence.
    aligned = citrus_aligned and (concept_aligned or not focus_text.strip())

    section_direct = _contains_any(section, _RESULT_SECTION_TERMS)
    outcome_signal = _contains_any(excerpt, _OUTCOME_TERMS)
    process_signal = _contains_any(excerpt, _PROCESS_TERMS)
    numeric_signal = bool(
        re.search(
            r"\d+(?:\.\d+)?\s*(?:%|℃|°\s*C|h\b|min\b|分钟|小时|天|d\b|mg\b|g\b|kg\b|mL\b|L\b|rpm\b|pH\b)",
            excerpt,
            flags=re.I,
        )
    )
    direct_content = (
        (section_direct and (outcome_signal or process_signal or numeric_signal))
        or (outcome_signal and process_signal)
        or (numeric_signal and process_signal)
    )
    if aligned and direct_content:
        return DIRECT_EVIDENCE, "正文片段有可回查定位，并直接报告相应柑橘工艺的方法、参数或结果。"
    if not aligned:
        return REFERENCE_EVIDENCE, "有可回查正文，但研究对象或工艺主题与当前结论的对应不够直接。"
    return REFERENCE_EVIDENCE, "有可回查正文，但片段未直接报告足以支撑当前结论的方法、参数或结果。"


def annotate_evidence(
    evidence: list[dict[str, Any]],
    intent: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for source in evidence:
        item = dict(source)
        level, reason = determine_evidence_level(item, intent)
        item["evidence_level"] = level
        item["evidence_level_reason"] = reason
        item["evidence_policy_version"] = EVIDENCE_POLICY_VERSION
        item["applicability"] = build_applicability(item, intent)
        item["source_url"] = source_url(item)
        item["doi_normalized"] = normalize_doi(item.get("doi"))
        adjacent = item.get("adjacent_chunks")
        if isinstance(adjacent, list):
            item["adjacent_chunks"] = annotate_evidence(
                [dict(value) for value in adjacent if isinstance(value, Mapping)],
                intent,
            )
        annotated.append(item)
    return annotated


def effective_evidence_level(item: Mapping[str, Any]) -> str:
    if (
        item.get("evidence_policy_version") == EVIDENCE_POLICY_VERSION
        and item.get("evidence_level") in EVIDENCE_LEVELS
    ):
        return str(item["evidence_level"])
    return determine_evidence_level(item)[0]


def evidence_reference(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "document_id": _clean_text(item.get("document_id") or item.get("source_file")),
        "chunk_id": _clean_text(item.get("chunk_id")),
        "title": _clean_text(item.get("title")) or "未命名文献",
        "year": _clean_text(item.get("year")) or "年份未知",
        "doi": normalize_doi(item.get("doi")),
        "url": source_url(item),
        "source": _clean_text(item.get("publication") or item.get("source") or item.get("source_file")),
        "section": _clean_text(item.get("section")) or "正文",
        "page": item.get("page") or item.get("page_start"),
        "excerpt": compact_excerpt(item.get("chunk_text"), 420),
        "applicability": _clean_text(item.get("applicability")) or build_applicability(item),
        "evidence_level": effective_evidence_level(item),
        "evidence_level_reason": _clean_text(item.get("evidence_level_reason")),
    }


def _evidence_keys(item: Mapping[str, Any]) -> set[str]:
    return {
        _clean_text(item.get(key)).casefold()
        for key in ("document_id", "source_file", "chunk_id", "title")
        if _clean_text(item.get(key))
    }


def _group_evidence(
    group: Mapping[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    exact_chunk_ids: set[str] = {
        _clean_text(value).casefold()
        for value in (group.get("source_chunk_ids") or [])
        if _clean_text(value)
    }
    wanted: set[str] = {
        _clean_text(value).casefold()
        for value in (group.get("source_ids") or [])
        if _clean_text(value)
    }
    for alternative in group.get("alternatives") or []:
        if not isinstance(alternative, Mapping):
            continue
        source_chunk_id = _clean_text(alternative.get("source_chunk_id"))
        if source_chunk_id:
            exact_chunk_ids.add(source_chunk_id.casefold())
        for key in ("source_id", "title"):
            value = _clean_text(alternative.get(key))
            if value:
                wanted.add(value.casefold())
    if not exact_chunk_ids and not wanted:
        return []
    matched: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        if exact_chunk_ids:
            if _clean_text(item.get("chunk_id")).casefold() not in exact_chunk_ids:
                continue
        elif not (_evidence_keys(item) & wanted):
            continue
        ref = evidence_reference(item)
        if not exact_chunk_ids and ref.get("evidence_level") == DIRECT_EVIDENCE:
            ref["evidence_level"] = REFERENCE_EVIDENCE
            ref["evidence_level_reason"] = (
                "仅完成文献级绑定，未精确绑定参数所在片段；"
                "不能借用同篇文献中的其他结果升级该参数。"
            )
        identity = (str(ref.get("document_id")), str(ref.get("chunk_id")))
        if identity in seen:
            continue
        seen.add(identity)
        matched.append(ref)
    matched.sort(
        key=lambda value: {
            DIRECT_EVIDENCE: 0,
            REFERENCE_EVIDENCE: 1,
            INSUFFICIENT_EVIDENCE: 2,
        }.get(str(value.get("evidence_level")), 3)
    )
    return matched[:3]


def annotate_parameter_groups(
    groups: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for source in groups:
        group = dict(source)
        refs = _group_evidence(group, evidence)
        levels = {str(ref.get("evidence_level")) for ref in refs}
        confidence = str(group.get("confidence_level") or "")
        if group.get("conflict"):
            if sum(ref.get("evidence_level") == DIRECT_EVIDENCE for ref in refs) >= 2:
                level = DIRECT_EVIDENCE
                reason = "至少两条可回查直接证据报告了不一致参数，因此直接支持“存在冲突、不可合并”的结论。"
            elif refs:
                level = REFERENCE_EVIDENCE
                reason = "存在参数差异线索，但直接证据数量或定位不足，需回查原文。"
            else:
                level = INSUFFICIENT_EVIDENCE
                reason = "未绑定到可核验原文，不能确认参数冲突。"
        elif not group.get("recommendable") or confidence == "低可信度":
            level = INSUFFICIENT_EVIDENCE
            reason = "单位、条件、一致性或可推荐性不足，不能形成生产参数结论。"
        elif DIRECT_EVIDENCE in levels:
            level = DIRECT_EVIDENCE
            reason = "推荐值可回溯到带单位、条件和原文定位的直接报告；仍需按适用条件小试。"
        elif REFERENCE_EVIDENCE in levels:
            level = REFERENCE_EVIDENCE
            reason = "存在相关文献片段，但与该参数结论的对应不够直接。"
        else:
            level = INSUFFICIENT_EVIDENCE
            reason = "未绑定到可核验的参数原文。"
        group["evidence_level"] = level
        group["evidence_level_reason"] = reason
        group["evidence_refs"] = refs
        if level != DIRECT_EVIDENCE:
            group["public_display"] = False
            group["recommendable"] = False
        annotated.append(group)
    return annotated


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _route_references(
    direction: str,
    evidence: list[dict[str, Any]],
    direction_terms: Mapping[str, list[str] | tuple[str, ...]],
) -> list[dict[str, Any]]:
    terms = direction_terms.get(direction) or []
    matched: list[dict[str, Any]] = []
    seen_documents: set[str] = set()
    for item in evidence:
        text = " ".join(
            _clean_text(item.get(key))
            for key in ("title", "category", "product", "topic", "keywords", "section", "chunk_text")
        )
        if not _contains_any(text, list(terms)):
            continue
        ref = evidence_reference(item)
        document_id = str(ref.get("document_id") or ref.get("title"))
        if document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        matched.append(ref)
    matched.sort(
        key=lambda value: {
            DIRECT_EVIDENCE: 0,
            REFERENCE_EVIDENCE: 1,
            INSUFFICIENT_EVIDENCE: 2,
        }.get(str(value.get("evidence_level")), 3)
    )
    return matched[:3]


def build_key_conclusions(
    scores: list[Any],
    evidence: list[dict[str, Any]],
    parameter_groups: list[dict[str, Any]],
    quality_risks: list[Any],
    processing_intent: Mapping[str, Any] | None,
    direction_terms: Mapping[str, list[str] | tuple[str, ...]],
    *,
    route_limit: int = 2,
    parameter_limit: int = 4,
    risk_limit: int = 2,
) -> list[dict[str, Any]]:
    # Local import avoids a module cycle and keeps every public parameter
    # surface behind the same deterministic gate.
    from .process_knowledge import is_public_parameter_group

    conclusions: list[dict[str, Any]] = []
    intent = processing_intent or {}
    current_scope = (
        f"当前原料：{_clean_text(intent.get('raw_material')) or '待确认'}；"
        f"目标产品：{_clean_text(intent.get('primary_product')) or '待确认'}；"
        f"规模：{_clean_text(intent.get('scale')) or 'unknown'}"
    )
    for index, score in enumerate(scores[:route_limit], 1):
        direction = str(_item_value(score, "direction", "待评估路线"))
        refs = _route_references(direction, evidence, direction_terms)
        levels = {str(ref.get("evidence_level")) for ref in refs}
        if DIRECT_EVIDENCE in levels:
            level = DIRECT_EVIDENCE
            reason = "直接证据仅支持相似柑橘原料下该路线的工艺可行性；当前批次排序仍综合了输入数据和固定规则。"
        elif REFERENCE_EVIDENCE in levels:
            level = REFERENCE_EVIDENCE
            reason = "检索到相关材料，但尚不足以把当前批次的路线排序表述为文献直接结论。"
        else:
            level = INSUFFICIENT_EVIDENCE
            reason = "未检索到可直接支撑该路线的可核验正文，路线只能作为规则驱动的待验证判断。"
        conclusions.append(
            {
                "conclusion_id": f"route-{index}",
                "conclusion_type": "路线判断",
                "conclusion": (
                    f"{'首选' if index == 1 else '重要备选'}路线：{direction}"
                    f"（{_item_value(score, 'match_level', '待评估')}）"
                ),
                "evidence_level": level,
                "evidence_level_reason": reason,
                "applicability": current_scope + "；进入生产前必须完成当前批次小试和质控放行。",
                "evidence": refs,
            }
        )

    public_parameter_groups = [
        group for group in parameter_groups if is_public_parameter_group(group)
    ]
    for index, group in enumerate(public_parameter_groups[:parameter_limit], 1):
        conclusions.append(
            {
                "conclusion_id": f"parameter-{index}",
                "conclusion_type": "工艺参数",
                "conclusion": (
                    f"{group.get('process_step') or '未明确步骤'}—"
                    f"{group.get('parameter_name') or '未明确参数'}："
                    f"{group.get('recommended_range') or '现有知识库证据不足'}"
                ),
                "evidence_level": group.get("evidence_level") or INSUFFICIENT_EVIDENCE,
                "evidence_level_reason": group.get("evidence_level_reason") or "参数证据未完成分级。",
                "applicability": group.get("applicability") or "需按当前原料、设备和规模开展小试。",
                "evidence": list(group.get("evidence_refs") or []),
            }
        )

    for index, risk in enumerate(quality_risks[:risk_limit], 1):
        conclusions.append(
            {
                "conclusion_id": f"risk-{index}",
                "conclusion_type": "质控边界",
                "conclusion": (
                    f"{_item_value(risk, 'item', '风险项')}："
                    f"{_item_value(risk, 'suggestion', '需人工复核')}"
                ),
                "evidence_level": INSUFFICIENT_EVIDENCE,
                "evidence_level_reason": "该项由当前批次输入和固定质控规则触发，并非文献直接结论。",
                "applicability": "仅针对当前批次资料完整性或质量状态；应以检测原件和质控审批为准。",
                "evidence": [],
            }
        )
    return conclusions


def format_key_conclusions_markdown(
    conclusions: list[dict[str, Any]],
    *,
    heading: str = "### 关键结论证据卡",
    max_items: int | None = None,
    max_references: int = 1,
    excerpt_chars: int = 240,
) -> str:
    if not conclusions:
        return ""
    selected = conclusions if max_items is None else conclusions[:max_items]
    lines = [heading, ""]
    for index, item in enumerate(selected, 1):
        lines.extend(
            [
                f"#### {index}. {_clean_text(item.get('conclusion')) or '待核验结论'}",
                f"- 证据等级：**{item.get('evidence_level') or INSUFFICIENT_EVIDENCE}**",
                f"- 判定说明：{_clean_text(item.get('evidence_level_reason')) or '未完成证据判定'}",
                f"- 适用条件：{_clean_text(item.get('applicability')) or '待确认'}",
            ]
        )
        refs = list(item.get("evidence") or [])[:max_references]
        if not refs:
            lines.append("- 可核验文献：未绑定；不得包装为文献直接结论。")
        for ref_index, ref in enumerate(refs, 1):
            title = _clean_text(ref.get("title")) or "未命名文献"
            year = _clean_text(ref.get("year")) or "年份未知"
            doi = normalize_doi(ref.get("doi"))
            url = source_url(ref) or _clean_text(ref.get("url"))
            if url:
                link_label = f"DOI {doi}" if doi else "原文链接"
                source_text = f"[{link_label}]({url})"
            else:
                source_text = "DOI/链接未收录"
            lines.append(f"- 文献 {ref_index}：{title}（{year}；{source_text}）")
            lines.append(
                f"  - 原文片段：{compact_excerpt(ref.get('excerpt'), excerpt_chars) or '未提供可核验原文片段'}"
            )
            lines.append(
                f"  - 文献适用条件：{_clean_text(ref.get('applicability')) or '需回查原文确认'}"
            )
        lines.append("")
    return "\n".join(lines).strip()
