from __future__ import annotations

from typing import Any


REQUIRED_TOOL_KEYS = [
    "product_classifier",
    "memory",
    "processing_intent_analyzer",
    "literature_retriever",
    "processing_evidence_aggregator",
    "rule_scoring_engine",
    "quality_gate",
    "report_writer",
]


def check_required_tools(completed_tool_keys: list[str]) -> list[str]:
    missing = [tool_key for tool_key in REQUIRED_TOOL_KEYS if tool_key not in completed_tool_keys]
    return [f"必需工具未执行：{tool_key}" for tool_key in missing]


def check_result_boundaries(
    batch: dict[str, Any],
    evidence: list[dict[str, Any]],
    scores: list[Any],
    quality_risks: list[Any],
    compliance_issues: list[str],
) -> list[str]:
    issues: list[str] = []
    if not evidence:
        issues.append("未检索到文献证据，报告只能作为低置信度草稿。")
    if not scores:
        issues.append("未获得加工路线分级结果，不能给出推荐方向。")
    if compliance_issues:
        issues.extend(f"报告合规扫描提示：{item}" for item in compliance_issues)

    missing_tests = [
        label
        for key, label in {
            "pesticide": "农残",
            "heavy_metal": "重金属",
            "microbe": "微生物",
            "aflatoxin": "黄曲霉毒素",
        }.items()
        if not batch.get(key)
    ]
    if missing_tests:
        issues.append("缺少" + "、".join(missing_tests) + "检测，不能输出最终放行或可销售结论。")
    if quality_risks:
        issues.append("存在质控风险项，需人工复核后再进入报价、生产或对外沟通。")
    return issues


def run_fixed_guardrails(
    completed_tool_keys: list[str],
    batch: dict[str, Any],
    evidence: list[dict[str, Any]],
    scores: list[Any],
    quality_risks: list[Any],
    compliance_issues: list[str],
) -> list[str]:
    issues = check_required_tools(completed_tool_keys)
    issues.extend(check_result_boundaries(batch, evidence, scores, quality_risks, compliance_issues))
    return issues
