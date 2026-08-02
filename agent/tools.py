from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .process_knowledge import (
    aggregate_parameter_evidence,
    analyze_processing_intent,
    build_parameterized_process_plan,
    extract_processing_parameters,
    retrieve_processing_evidence,
)
from .rag import comprehensive_search_knowledge
from .report import build_processing_plan, check_compliance, generate_report
from .rules import ALL_DIRECTIONS, check_quality_risks, score_processing_options


@dataclass
class ToolResult:
    name: str
    tool: str
    status: str
    observation: str
    data: Any


def infer_product_filter(origin: str, variety: str) -> str:
    text = f"{origin} {variety}"
    if any(keyword in text for keyword in ["柑", "橘", "橙", "柚", "柠檬", "新会", "茶枝柑", "赣南", "陈皮"]):
        return "柑橘"
    return "不限"


def build_retrieval_query(batch: dict[str, Any]) -> str:
    query_terms = [
        str(batch.get("origin", "")),
        str(batch.get("variety", "")),
        str(batch.get("customer_type", "")),
        "柑橘加工树",
        "整果",
        "果肉",
        "果皮",
        "种子",
        "副产物",
        "果汁",
        "NFC",
        "浓缩汁",
        "果醋",
        "果酒",
        "橘瓣罐头",
        "砂囊",
        "陈皮",
        "陈皮丝",
        "果胶",
        "黄酮",
        "精油",
        "籽油",
        "饲料",
        "有机肥",
        "质控",
        "工艺",
        "销售",
        *ALL_DIRECTIONS,
    ]
    return " ".join(query_terms)


def build_retrieval_queries(batch: dict[str, Any]) -> list[str]:
    """Build focused subqueries so one broad batch request does not collapse to one literature topic."""
    identity = " ".join(
        value
        for value in [str(batch.get("origin", "")).strip(), str(batch.get("variety", "")).strip()]
        if value
    ) or "柑橘"
    customer = str(batch.get("customer_type", "")).strip()
    common = f"{identity} {customer} 质量控制 工艺参数 结果 结论".strip()
    return [
        f"{common} 原料品质 成分 鉴别 农残 重金属 微生物 储藏",
        "柑橘 整果 加工 干燥 果脯 蜜饯 品质 稳定性",
        "柑橘 果肉 橙汁 NFC 浓缩汁 果粒 发酵 工艺 品质",
        f"{identity} 果皮 陈皮 陈化 干燥 黄酮 质量评价",
        "柑橘 果皮 精油 柠檬烯 蒸馏 冷压 提取 挥发性成分",
        "柑橘 果皮 果胶 提取 改性 酯化度 得率 应用",
        "柑橘 种子 籽油 橘核 成分 提取 高值利用",
        "柑橘 副产物 果渣 饲料 有机肥 发酵 综合利用 安全",
    ]


def _focus_category(query: str) -> str | None:
    category_terms = {
        "陈皮": ["陈皮", "广陈皮", "陈化"],
        "橙汁": ["橙汁", "果汁", "NFC", "浓缩汁", "果肉", "果粒"],
        "果胶": ["果胶", "pectin"],
        "精油": ["精油", "挥发油", "柠檬烯", "essential oil"],
        "种子": ["种子", "籽油", "橘核", "seed oil"],
        "副产物": ["副产物", "果渣", "饲料", "有机肥", "综合利用"],
    }
    normalized = query.lower()
    matched = [
        category
        for category, terms in category_terms.items()
        if any(term.lower() in normalized for term in terms)
    ]
    return matched[0] if len(matched) == 1 else None


def build_retrieval_specs(
    batch: dict[str, Any], focus_query: str = ""
) -> list[dict[str, str | None]]:
    """Attach authoritative folder facets to broad route queries for guaranteed coverage."""
    queries = build_retrieval_queries(batch)
    specs: list[dict[str, str | None]] = [
        {"query": queries[0], "category": None},
        {"query": queries[1], "category": None},
        {"query": queries[2], "category": "橙汁"},
        {"query": queries[3], "category": "陈皮"},
        {"query": queries[4], "category": "精油"},
        {"query": queries[5], "category": "果胶"},
        {"query": queries[6], "category": "种子"},
        {"query": queries[7], "category": "副产物"},
    ]
    if focus_query.strip():
        identity = " ".join(
            value
            for value in [str(batch.get("origin", "")).strip(), str(batch.get("variety", "")).strip()]
            if value
        ) or "柑橘"
        specs.insert(
            0,
            {
                "query": f"{focus_query.strip()} {identity} 研究结果 工艺条件 质量指标 适用边界",
                "category": _focus_category(focus_query),
            },
        )
    return specs


def classify_product(batch: dict[str, Any]) -> ToolResult:
    product_filter = infer_product_filter(str(batch.get("origin", "")), str(batch.get("variety", "")))
    return ToolResult(
        name="识别业务场景",
        tool="Product Classifier",
        status="完成",
        observation=f"根据产地和品种，将检索范围设为：{product_filter}。",
        data=product_filter,
    )


def analyze_processing_request(
    query: str,
    batch: dict[str, Any],
    direction: str = "",
) -> ToolResult:
    intent = analyze_processing_intent(query, batch, direction)
    return ToolResult(
        name="识别加工意图并拆分问题",
        tool="Processing Intent Analyzer",
        status="完成",
        observation=(
            f"识别目标产品：{intent.get('primary_product')}；规模：{intent.get('scale')}；"
            f"已有设备：{'、'.join(intent.get('equipment') or []) or '未提供'}。"
        ),
        data=intent,
    )


def _retrieve_faceted_literature(
    specs: list[dict[str, str | None]], product_filter: str, top_k: int
) -> list[dict[str, Any]]:
    per_facet: list[list[dict[str, Any]]] = []
    citrus_title_terms = (
        "citrus", "orange", "mandarin", "tangerine", "lemon", "pomelo", "grapefruit",
        "chenpi", "citri reticulatae", "柑橘", "陈皮", "橙", "柚", "柠檬",
    )
    for spec in specs:
        items = comprehensive_search_knowledge(
            query=str(spec.get("query") or ""),
            product_filter=product_filter,
            category_filter=spec.get("category"),
            top_k=5,
        )
        if spec.get("category"):
            primary = [
                item
                for item in items
                if any(term in str(item.get("title") or "").lower() for term in citrus_title_terms)
            ]
            if primary:
                primary_ids = {str(item.get("chunk_id")) for item in primary}
                items = [*primary, *(item for item in items if str(item.get("chunk_id")) not in primary_ids)]
        for item in items:
            item["retrieval_facet"] = spec.get("category") or "跨类别"
            item["retrieval_method"] = "faceted_" + str(item.get("retrieval_method") or "hybrid")
        per_facet.append(items)

    selected: list[dict[str, Any]] = []
    selected_chunks: set[str] = set()
    document_counts: dict[str, int] = {}

    def add(item: dict[str, Any]) -> bool:
        chunk_id = str(item.get("chunk_id") or f"{item.get('document_id')}:{item.get('page')}")
        document_id = str(item.get("document_id") or item.get("source_file") or item.get("title"))
        if chunk_id in selected_chunks or document_counts.get(document_id, 0) >= 2:
            return False
        selected.append(item)
        selected_chunks.add(chunk_id)
        document_counts[document_id] = document_counts.get(document_id, 0) + 1
        return True

    # First reserve one result for each route/category, then fill by relevance.
    for items in per_facet:
        for item in items:
            if add(item):
                break
        if len(selected) >= top_k:
            return selected[:top_k]
    pool = sorted(
        (item for items in per_facet for item in items),
        key=lambda item: float(item.get("match_score") or 0),
        reverse=True,
    )
    for item in pool:
        add(item)
        if len(selected) >= top_k:
            break
    return selected


def retrieve_literature(
    query: str | list[str] | list[dict[str, str | None]], product_filter: str, top_k: int = 12
) -> ToolResult:
    if isinstance(query, list) and query and isinstance(query[0], dict):
        evidence = _retrieve_faceted_literature(query, product_filter, top_k)
    else:
        evidence = comprehensive_search_knowledge(query=query, product_filter=product_filter, top_k=top_k)
    document_count = len(
        {
            str(item.get("document_id") or item.get("source_file") or item.get("title"))
            for item in evidence
        }
    )
    categories = sorted(
        {
            category
            for item in evidence
            for category in str(item.get("category") or item.get("product") or "未分类").split("、")
            if category
        }
    )
    return ToolResult(
        name="检索知识依据",
        tool="Comprehensive Literature Retriever",
        status="完成",
        observation=(
            f"通过多查询、SQLite 全文召回、双语概念扩展、混合重排与来源去重，"
            f"检索到 {len(evidence)} 条证据，来自 {document_count} 篇文献；"
            f"覆盖类别：{'、'.join(categories) or '暂无'}。"
        ),
        data=evidence,
    )


def retrieve_processing_parameters(
    intent: dict[str, Any],
    product_filter: str,
    top_k: int = 24,
) -> ToolResult:
    evidence, subquestions = retrieve_processing_evidence(
        intent,
        product_filter=product_filter,
        top_k=top_k,
    )
    parameters = extract_processing_parameters(evidence, intent)
    parameter_groups = aggregate_parameter_evidence(parameters)
    parameterized_plan = build_parameterized_process_plan(intent, parameter_groups, evidence)
    usable = sum(
        1
        for item in parameter_groups
        if item.get("confidence_level") in {"高可信度", "中可信度"}
        and not item.get("conflict")
    )
    return ToolResult(
        name="检索并聚合加工参数证据",
        tool="Processing Evidence Aggregator",
        status="完成",
        observation=(
            f"按 {len(subquestions)} 个加工子问题完成混合检索，保留 {len(evidence)} 条证据，"
            f"提取 {len(parameters)} 条带来源参数；其中 {usable} 组可作为有条件的小试依据。"
        ),
        data={
            "evidence": evidence,
            "subquestions": subquestions,
            "parameters": parameters,
            "parameter_groups": parameter_groups,
            "parameterized_plan": parameterized_plan,
        },
    )
def score_processing(
    batch: dict[str, Any], image_observation: str, evidence: list[dict[str, Any]]
) -> ToolResult:
    scores = score_processing_options(batch, image_observation, evidence=evidence)
    top_score = scores[0] if scores else None
    return ToolResult(
        name="评估加工路线",
        tool="Evidence-aware Route Ranker",
        status="完成",
        observation=(
            f"当前优先方向是 {top_score.direction}（{top_score.match_level}；"
            f"文献支持：{top_score.evidence_support}；数据置信度：{top_score.data_confidence}）。"
            if top_score else "未得到可用路线排序。"
        ),
        data=scores,
    )


def check_quality(batch: dict[str, Any], image_observation: str) -> ToolResult:
    quality_risks = check_quality_risks(batch, image_observation)
    return ToolResult(
        name="检查质控风险",
        tool="Quality Gate",
        status="完成",
        observation=f"发现 {len(quality_risks)} 个需复核风险项。",
        data=quality_risks,
    )


def write_report(
    batch: dict[str, Any],
    image_observation: str,
    evidence: list[dict[str, Any]],
    scores: list[Any],
    quality_risks: list[Any],
    processing_intent: dict[str, Any] | None = None,
    process_parameters: list[dict[str, Any]] | None = None,
    parameter_groups: list[dict[str, Any]] | None = None,
    parameterized_plan: dict[str, Any] | None = None,
) -> ToolResult:
    top_direction = scores[0].direction
    processing_plan = build_processing_plan(
        batch,
        top_direction,
        quality_risks,
        image_observation,
        evidence,
    )
    report = generate_report(
        batch,
        image_observation,
        evidence,
        scores,
        quality_risks,
        processing_plan=processing_plan,
        processing_intent=processing_intent,
        process_parameters=process_parameters,
        parameter_groups=parameter_groups,
        parameterized_plan=parameterized_plan,
    )
    compliance_issues = check_compliance(report)
    return ToolResult(
        name="生成报告并做合规扫描",
        tool="Report Writer + Compliance Checker",
        status="完成",
        observation=f"生成 Markdown 报告；合规扫描提示 {len(compliance_issues)} 项。",
        data={
            "report": report,
            "processing_plan": processing_plan,
            "compliance_issues": compliance_issues,
        },
    )


TOOL_REGISTRY = {
    "product_classifier": {
        "name": "Product Classifier",
        "description": "识别批次所属的柑橘/陈皮/果肉/果皮等业务检索范围。",
    },
    "literature_retriever": {
        "name": "Comprehensive Literature Retriever",
        "description": "基于本地 SQLite 文献库执行多查询全文召回、双语概念扩展、混合重排与跨文献去重。",
    },
    "processing_intent_analyzer": {
        "name": "Processing Intent Analyzer",
        "description": "识别原料、目标产品、单元操作、参数、规模、现有设备和质量目标，并拆分加工子问题。",
    },
    "processing_evidence_aggregator": {
        "name": "Processing Evidence Aggregator",
        "description": "执行面向单元操作的混合检索和重排序，结构化提取参数，保留条件、单位、来源并处理冲突。",
    },
    "rule_scoring_engine": {
        "name": "Evidence-aware Route Ranker",
        "description": "综合批次规则、直接相关文献数量与数据完整度，输出分级路线排序而非伪精确百分制。",
    },
    "quality_gate": {
        "name": "Quality Gate",
        "description": "检查检测资料、外观风险、仓储风险和不能越界的质控事项。",
    },
    "report_writer": {
        "name": "Report Writer + Compliance Checker",
        "description": "生成 Markdown 决策报告并扫描高风险宣传或合规表达。",
    },
}
