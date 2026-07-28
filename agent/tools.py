from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rag import hybrid_search_knowledge
from .report import check_compliance, generate_report
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


def classify_product(batch: dict[str, Any]) -> ToolResult:
    product_filter = infer_product_filter(str(batch.get("origin", "")), str(batch.get("variety", "")))
    return ToolResult(
        name="识别业务场景",
        tool="Product Classifier",
        status="完成",
        observation=f"根据产地和品种，将检索范围设为：{product_filter}。",
        data=product_filter,
    )


def retrieve_literature(query: str, product_filter: str, top_k: int = 8) -> ToolResult:
    evidence = hybrid_search_knowledge(query=query, product_filter=product_filter, top_k=top_k)
    return ToolResult(
        name="检索知识依据",
        tool="Hybrid Literature Retriever",
        status="完成",
        observation=f"通过关键词、语义相关性和产品元数据混合检索到 {len(evidence)} 条文献片段。",
        data=evidence,
    )


def score_processing(batch: dict[str, Any], image_observation: str) -> ToolResult:
    scores = score_processing_options(batch, image_observation)
    top_score = scores[0] if scores else None
    return ToolResult(
        name="评估加工路线",
        tool="Rule Scoring Engine",
        status="完成",
        observation=f"当前最高分方向是 {top_score.direction}（{top_score.score} 分）。" if top_score else "未得到可用评分。",
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
) -> ToolResult:
    report = generate_report(batch, image_observation, evidence, scores, quality_risks)
    compliance_issues = check_compliance(report)
    return ToolResult(
        name="生成报告并做合规扫描",
        tool="Report Writer + Compliance Checker",
        status="完成",
        observation=f"生成 Markdown 报告；合规扫描提示 {len(compliance_issues)} 项。",
        data={"report": report, "compliance_issues": compliance_issues},
    )


TOOL_REGISTRY = {
    "product_classifier": {
        "name": "Product Classifier",
        "description": "识别批次所属的柑橘/陈皮/果肉/果皮等业务检索范围。",
    },
    "literature_retriever": {
        "name": "Hybrid Literature Retriever",
        "description": "基于本地文献切片执行关键词、语义相关性和元数据混合检索。",
    },
    "rule_scoring_engine": {
        "name": "Rule Scoring Engine",
        "description": "按整果、果肉、果皮、种子和副产物方向执行可审计规则评分。",
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
