from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .evidence import (
    EVIDENCE_LEVELS,
    annotate_evidence,
    annotate_parameter_groups,
    build_key_conclusions,
    effective_evidence_level,
)
from .guardrails import run_fixed_guardrails
from .memory import build_memory_snapshot, redact_sensitive
from .planner import build_controlled_plan, serialize_plan
from .process_knowledge import build_parameterized_process_plan
from .rules import DIRECTION_EVIDENCE_TERMS
from .tools import (
    TOOL_REGISTRY,
    ToolResult,
    analyze_processing_request,
    build_retrieval_specs,
    check_quality,
    classify_product,
    infer_product_filter as infer_product_filter_tool,
    retrieve_literature,
    retrieve_processing_parameters,
    score_processing,
    write_report,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "outputs" / "reports"
AUDIT_LOG = ROOT / "logs" / "audit.jsonl"
_AUDIT_WRITE_LOCK = threading.Lock()


@dataclass
class AgentStep:
    name: str
    tool: str
    status: str
    observation: str


ProgressCallback = Callable[[str], None]


def _notify(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback:
        progress_callback(message)


def infer_product_filter(origin: str, variety: str) -> str:
    return infer_product_filter_tool(origin, variety)


def _step_from_tool_result(result: ToolResult) -> AgentStep:
    return AgentStep(
        name=result.name,
        tool=result.tool,
        status=result.status,
        observation=result.observation,
    )


def _merge_evidence(
    *groups: list[dict[str, Any]],
    limit: int = 24,
    per_document_limit: int = 2,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    document_counts: dict[str, int] = {}
    for item in (item for group in groups for item in group):
        chunk_id = str(item.get("chunk_id") or f"{item.get('document_id')}:{item.get('page') or item.get('page_start')}")
        document_id = str(item.get("document_id") or item.get("source_file") or item.get("title"))
        if chunk_id in seen or document_counts.get(document_id, 0) >= per_document_limit:
            continue
        seen.add(chunk_id)
        document_counts[document_id] = document_counts.get(document_id, 0) + 1
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def _merge_retrieval_stats(*values: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    summed_keys = {
        "query_count",
        "subquery_count",
        "attempted_subquery_count",
        "fts_rows_returned",
        "database_rows_scanned",
        "database_candidates",
        "unique_candidate_count",
        "legacy_candidates",
        "ranked_candidates",
        "ocr_filtered_count",
        "product_filtered_count",
        "category_filtered_count",
        "analytical_filtered_count",
        "score_filtered_count",
        "deduplicated_count",
        "adjacent_candidate_count",
        "adjacent_added_count",
        "elapsed_ms",
    }
    for stats in values:
        if not stats:
            continue
        for key, value in stats.items():
            if key in summed_keys:
                merged[key] = float(merged.get(key) or 0) + float(value or 0)
            elif key in {
                "library_document_count",
                "library_chunk_count",
                "library_usable_document_count",
                "library_ocr_document_count",
            }:
                merged[key] = max(int(merged.get(key) or 0), int(value or 0))
            elif key == "timed_out":
                merged[key] = bool(merged.get(key)) or bool(value)
            elif key == "database_available":
                if value is False:
                    merged[key] = False
                elif merged.get(key) is None and value is True:
                    merged[key] = True
            elif key == "retrieval_complete":
                merged[key] = bool(merged.get(key, True)) and bool(value)
            elif key == "retrieval_error":
                errors = [
                    part
                    for error_value in (merged.get(key), value)
                    for part in str(error_value or "").split("；")
                    if part
                ]
                merged[key] = "；".join(dict.fromkeys(errors))
            elif key not in merged:
                merged[key] = value
    for key in summed_keys - {"elapsed_ms"}:
        if key in merged:
            merged[key] = int(merged[key])
    if "elapsed_ms" in merged:
        merged["elapsed_ms"] = round(float(merged["elapsed_ms"]), 2)
    return merged


def build_agent_brief(batch: dict[str, Any], image_observation: str, product_filter: str) -> dict[str, str]:
    test_labels = {"pesticide": "农残", "heavy_metal": "重金属", "microbe": "微生物", "aflatoxin": "黄曲霉毒素"}
    test_issues = []
    for key, label in test_labels.items():
        status = batch.get(f"{key}_status")
        if status == "failed":
            test_issues.append(f"{label}结果异常")
        elif status == "result_missing":
            test_issues.append(f"{label}结果未明确")
        elif batch.get(key) is not True:
            test_issues.append(f"{label}检测缺失")
    constraints = "、".join(test_issues) if test_issues else "关键检测资料较完整"
    return {
        "role": "受控柑橘批次加工决策 Agent",
        "goal": f"判断批次 {batch.get('batch_id') or '未命名批次'} 更适合的加工方向，并生成可复核报告。",
        "context": f"产地/品种识别为 {product_filter} 场景；目标客户为 {batch.get('customer_type') or '未指定客户'}。",
        "constraint": f"{constraints}；外观描述为：{image_observation or '未填写'}。",
    }


def build_next_actions(result: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    missing_labels = {
        "pesticide": "补齐农残检测",
        "heavy_metal": "补齐重金属检测",
        "microbe": "补齐微生物检测",
        "aflatoxin": "补齐黄曲霉毒素检测",
    }
    for key, action in missing_labels.items():
        status = result["batch"].get(f"{key}_status")
        if status == "failed":
            actions.append(action.replace("补齐", "隔离批次并复核"))
        elif status == "result_missing":
            actions.append(action.replace("补齐", "补充具体结果和原始报告："))
        elif result["batch"].get(key) is not True:
            actions.append(action)

    if result["quality_risks"]:
        actions.append("安排质控人员人工复核风险项")
    if len(result["evidence"]) < 3:
        actions.append("补充真实文献、标准或企业 SOP 作为知识依据")

    top_direction = result["scores"][0].direction if result["scores"] else "推荐方向"
    actions.append(f"围绕“{top_direction}”做小试或报价前评审")
    return actions[:6]


def run_demo_agent(
    batch: dict[str, Any],
    image_observation: str,
    progress_callback: ProgressCallback | None = None,
    analysis_question: str = "",
    retrieval_mode: str = "quick",
) -> dict[str, Any]:
    retrieval_mode = "deep" if retrieval_mode == "deep" else "quick"
    processing_top_k = 40 if retrieval_mode == "deep" else 24
    broad_top_k = 24 if retrieval_mode == "deep" else 16
    evidence_limit = 40 if retrieval_mode == "deep" else 24
    per_document_limit = 4 if retrieval_mode == "deep" else 2
    completed_tool_keys: list[str] = []
    agent_steps: list[AgentStep] = [
        AgentStep(
            name="理解任务",
            tool="Agent Planner",
            status="完成",
            observation=f"目标是为 {batch.get('batch_id') or '当前批次'} 选择加工方向，并保留质控边界。",
        )
    ]

    _notify(progress_callback, "正在识别业务场景和检索范围")
    product_result = classify_product(batch)
    product_filter = str(product_result.data)
    completed_tool_keys.append("product_classifier")
    agent_steps.append(_step_from_tool_result(product_result))

    agent_brief = build_agent_brief(batch, image_observation, product_filter)

    _notify(progress_callback, "正在制定受控执行计划")
    plan = build_controlled_plan(batch, image_observation, product_filter)
    required_count = sum(1 for step in plan if step.required)
    agent_steps.append(
        AgentStep(
            name="制定执行计划",
            tool="Controlled Planner",
            status="完成",
            observation=f"已生成 {len(plan)} 个计划步骤，其中 {required_count} 个为必需步骤。",
        )
    )

    _notify(progress_callback, "正在读取短期任务上下文和长期知识状态")
    memory_snapshot = build_memory_snapshot(batch, image_observation, product_filter)
    completed_tool_keys.append("memory")
    chunk_count = memory_snapshot.get("long_term", {}).get("literature_chunk_count", 0)
    agent_steps.append(
        AgentStep(
            name="读取受控记忆",
            tool="Memory Manager",
            status="完成",
            observation=f"结构化短期状态记录当前批次，会话层保留最近 12 条消息；长期知识使用文献切片 {chunk_count} 条，不读取演示案例作为事实。",
        )
    )

    _notify(progress_callback, "正在识别加工目标、规模、设备和参数需求")
    intent_result = analyze_processing_request(analysis_question, batch)
    processing_intent = intent_result.data
    completed_tool_keys.append("processing_intent_analyzer")
    agent_steps.append(_step_from_tool_result(intent_result))

    explicit_processing_target = processing_intent.get("primary_product") != "柑橘加工品"
    broad_evidence: list[dict[str, Any]] = []
    process_payload: dict[str, Any] = {}
    broad_retrieval_stats: dict[str, Any] = {}
    if explicit_processing_target:
        _notify(progress_callback, "正在按单元操作拆分问题并检索参数化文献证据")
        process_result = retrieve_processing_parameters(
            processing_intent,
            product_filter,
            top_k=processing_top_k,
            retrieval_mode=retrieval_mode,
        )
        process_payload = process_result.data
        evidence = list(process_payload.get("evidence") or [])
        agent_steps.append(_step_from_tool_result(process_result))
        if not evidence:
            fallback_result = retrieve_literature(
                query=build_retrieval_specs(batch, focus_query=analysis_question),
                product_filter=product_filter,
                top_k=broad_top_k,
                retrieval_mode=retrieval_mode,
            )
            broad_evidence = fallback_result.data
            broad_retrieval_stats = dict((fallback_result.metadata or {}).get("deep_retrieval_stats") or {})
            evidence = broad_evidence
            agent_steps.append(_step_from_tool_result(fallback_result))
    else:
        _notify(progress_callback, "正在检索本地文献库和语义证据")
        evidence_result = retrieve_literature(
            query=build_retrieval_specs(batch, focus_query=analysis_question),
            product_filter=product_filter,
            top_k=broad_top_k,
            retrieval_mode=retrieval_mode,
        )
        broad_evidence = evidence_result.data
        broad_retrieval_stats = dict((evidence_result.metadata or {}).get("deep_retrieval_stats") or {})
        evidence = broad_evidence
        agent_steps.append(_step_from_tool_result(evidence_result))
    completed_tool_keys.append("literature_retriever")

    # Evidence strength is assigned deterministically before any route score is
    # changed. A retrieval score alone is never allowed to count as direct support.
    evidence = annotate_evidence(evidence, processing_intent)
    if explicit_processing_target:
        process_payload["evidence"] = evidence
    else:
        broad_evidence = evidence

    _notify(progress_callback, "正在综合批次规则、文献适用性和数据完整度评估加工路线")
    score_result = score_processing(batch, image_observation, evidence)
    scores = score_result.data
    completed_tool_keys.append("rule_scoring_engine")
    agent_steps.append(_step_from_tool_result(score_result))

    if not explicit_processing_target:
        top_direction = scores[0].direction if scores else ""
        intent_result = analyze_processing_request(analysis_question, batch, top_direction)
        processing_intent = intent_result.data
        _notify(progress_callback, "正在围绕优先路线补充单元操作参数、质量和包装证据")
        process_result = retrieve_processing_parameters(
            processing_intent,
            product_filter,
            top_k=processing_top_k,
            retrieval_mode=retrieval_mode,
        )
        process_payload = process_result.data
        processing_evidence = annotate_evidence(
            list(process_payload.get("evidence") or []),
            processing_intent,
        )
        process_payload["evidence"] = processing_evidence
        broad_evidence = annotate_evidence(broad_evidence, processing_intent)
        evidence = _merge_evidence(
            processing_evidence,
            broad_evidence,
            limit=evidence_limit,
            per_document_limit=per_document_limit,
        )
        agent_steps.append(_step_from_tool_result(process_result))
        # Re-evaluate support labels after focused evidence has been added.
        score_result = score_processing(batch, image_observation, evidence)
        scores = score_result.data

    completed_tool_keys.append("processing_evidence_aggregator")
    process_parameters = list(process_payload.get("parameters") or [])
    parameter_groups = annotate_parameter_groups(
        list(process_payload.get("parameter_groups") or []),
        evidence,
    )
    parameterized_plan = build_parameterized_process_plan(
        processing_intent,
        parameter_groups,
        evidence,
    )
    process_payload["parameter_groups"] = parameter_groups
    process_payload["parameterized_plan"] = parameterized_plan
    processing_subquestions = list(process_payload.get("subquestions") or [])
    processing_evidence = list(process_payload.get("evidence") or [])
    deep_retrieval_stats = _merge_retrieval_stats(
        broad_retrieval_stats,
        process_payload.get("deep_retrieval_stats") or {},
    )
    deep_retrieval_stats["retrieval_mode"] = retrieval_mode
    deep_retrieval_stats["selected_count"] = len(evidence)
    deep_retrieval_stats["selected_document_count"] = len(
        {
            str(item.get("document_id") or item.get("source_file") or item.get("title"))
            for item in evidence
        }
    )

    _notify(progress_callback, "正在检查质控边界和风险项")
    risk_result = check_quality(batch, image_observation)
    quality_risks = risk_result.data
    completed_tool_keys.append("quality_gate")
    agent_steps.append(_step_from_tool_result(risk_result))

    key_conclusions = build_key_conclusions(
        scores,
        evidence,
        parameter_groups,
        quality_risks,
        processing_intent,
        DIRECTION_EVIDENCE_TERMS,
    )

    _notify(progress_callback, "正在生成可复核的 Markdown 报告")
    report_result = write_report(
        batch,
        image_observation,
        evidence,
        scores,
        quality_risks,
        processing_intent=processing_intent,
        process_parameters=process_parameters,
        parameter_groups=parameter_groups,
        parameterized_plan=parameterized_plan,
        key_conclusions=key_conclusions,
    )
    report_payload = report_result.data
    report = report_payload["report"]
    processing_plan = report_payload["processing_plan"]
    compliance_issues = report_payload["compliance_issues"]
    completed_tool_keys.append("report_writer")
    agent_steps.append(_step_from_tool_result(report_result))

    _notify(progress_callback, "正在执行固定质控护栏")
    guardrail_issues = run_fixed_guardrails(
        completed_tool_keys,
        batch,
        evidence,
        scores,
        quality_risks,
        compliance_issues,
    )
    agent_steps.append(
        AgentStep(
            name="执行固定质控护栏",
            tool="Controlled Guardrails",
            status="完成",
            observation=f"完成必需工具校验和风险边界检查，提示 {len(guardrail_issues)} 项。",
        )
    )

    result = {
        "batch": batch,
        "analysis_question": analysis_question,
        "agent_brief": agent_brief,
        "agent_steps": agent_steps,
        "plan": serialize_plan(plan),
        "memory": memory_snapshot,
        "tool_registry": TOOL_REGISTRY,
        "guardrail_issues": guardrail_issues,
        "image_observation": image_observation,
        "product_filter": product_filter,
        "evidence": evidence,
        "processing_evidence": processing_evidence,
        "processing_intent": processing_intent,
        "processing_subquestions": processing_subquestions,
        "retrieval_mode": retrieval_mode,
        "deep_retrieval_stats": deep_retrieval_stats,
        "process_parameters": process_parameters,
        "parameter_groups": parameter_groups,
        "parameterized_plan": parameterized_plan,
        "key_conclusions": key_conclusions,
        "scores": scores,
        "quality_risks": quality_risks,
        "processing_plan": processing_plan,
        "report": report,
        "compliance_issues": compliance_issues,
    }
    result["next_actions"] = build_next_actions(result)
    return result


def save_report(markdown: str, batch_id: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{batch_id or 'batch'}.md"
    path = REPORT_DIR / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def write_audit_event(result: dict[str, Any], report_path: Path) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    tool_result_path = report_path.with_suffix(".tools.json")
    tool_result_path.write_text(
        json.dumps(redact_sensitive(serialize_result(result)), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    result["tool_result_path"] = str(tool_result_path)
    event = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "batch_id": result["batch"].get("batch_id"),
        "product_filter": result["product_filter"],
        "retrieval_mode": result.get("retrieval_mode", "quick"),
        "deep_retrieval_stats": result.get("deep_retrieval_stats") or {},
        "top_direction": result["scores"][0].direction if result["scores"] else None,
        "top_match_level": result["scores"][0].match_level if result["scores"] else None,
        "risk_count": len(result["quality_risks"]),
        "evidence_count": len(result["evidence"]),
        "evidence_level_counts": {
            level: sum(
                effective_evidence_level(item) == level
                for item in result.get("evidence", [])
            )
            for level in sorted(EVIDENCE_LEVELS)
        },
        "key_conclusion_count": len(result.get("key_conclusions", [])),
        "processing_evidence_count": len(result.get("processing_evidence", [])),
        "parameter_count": len(result.get("process_parameters", [])),
        "parameter_ids": [
            item.get("parameter_id")
            for item in result.get("process_parameters", [])
            if item.get("parameter_id")
        ],
        "guardrail_count": len(result.get("guardrail_issues", [])),
        "next_actions": result.get("next_actions", []),
        "report_path": str(report_path),
        "tool_result_path": str(tool_result_path),
    }
    with _AUDIT_WRITE_LOCK:
        with AUDIT_LOG.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")


def serialize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Convert dataclasses to dictionaries for UI tables or JSON exports."""
    return {
        **result,
        "agent_steps": [asdict(item) for item in result["agent_steps"]],
        "scores": [asdict(item) for item in result["scores"]],
        "quality_risks": [asdict(item) for item in result["quality_risks"]],
    }
