from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .guardrails import run_fixed_guardrails
from .memory import build_memory_snapshot
from .planner import build_controlled_plan, serialize_plan
from .tools import (
    TOOL_REGISTRY,
    ToolResult,
    build_retrieval_query,
    check_quality,
    classify_product,
    infer_product_filter as infer_product_filter_tool,
    retrieve_literature,
    score_processing,
    write_report,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "outputs" / "reports"
AUDIT_LOG = ROOT / "logs" / "audit.jsonl"


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


def build_agent_brief(batch: dict[str, Any], image_observation: str, product_filter: str) -> dict[str, str]:
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
    constraints = "、".join(missing_tests) + "检测缺失" if missing_tests else "关键检测资料较完整"
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
        if not result["batch"].get(key):
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
) -> dict[str, Any]:
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
    case_count = len(memory_snapshot.get("long_term", {}).get("demo_case_summaries", []))
    agent_steps.append(
        AgentStep(
            name="读取受控记忆",
            tool="Memory Manager",
            status="完成",
            observation=f"短期记忆已记录当前批次；长期记忆可用文献切片 {chunk_count} 条，示例案例 {case_count} 条。",
        )
    )

    _notify(progress_callback, "正在检索本地文献库和语义证据")
    evidence_result = retrieve_literature(
        query=build_retrieval_query(batch),
        product_filter=product_filter,
        top_k=8,
    )
    evidence = evidence_result.data
    completed_tool_keys.append("literature_retriever")
    agent_steps.append(_step_from_tool_result(evidence_result))

    _notify(progress_callback, "正在评估整果、果肉、果皮、种子和副产物路线")
    score_result = score_processing(batch, image_observation)
    scores = score_result.data
    completed_tool_keys.append("rule_scoring_engine")
    agent_steps.append(_step_from_tool_result(score_result))

    _notify(progress_callback, "正在检查质控边界和风险项")
    risk_result = check_quality(batch, image_observation)
    quality_risks = risk_result.data
    completed_tool_keys.append("quality_gate")
    agent_steps.append(_step_from_tool_result(risk_result))

    _notify(progress_callback, "正在生成可复核的 Markdown 报告")
    report_result = write_report(batch, image_observation, evidence, scores, quality_risks)
    report_payload = report_result.data
    report = report_payload["report"]
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
        "agent_brief": agent_brief,
        "agent_steps": agent_steps,
        "plan": serialize_plan(plan),
        "memory": memory_snapshot,
        "tool_registry": TOOL_REGISTRY,
        "guardrail_issues": guardrail_issues,
        "image_observation": image_observation,
        "product_filter": product_filter,
        "evidence": evidence,
        "scores": scores,
        "quality_risks": quality_risks,
        "report": report,
        "compliance_issues": compliance_issues,
    }
    result["next_actions"] = build_next_actions(result)
    return result


def save_report(markdown: str, batch_id: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{batch_id or 'batch'}.md"
    path = REPORT_DIR / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def write_audit_event(result: dict[str, Any], report_path: Path) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "batch_id": result["batch"].get("batch_id"),
        "product_filter": result["product_filter"],
        "top_direction": result["scores"][0].direction if result["scores"] else None,
        "top_score": result["scores"][0].score if result["scores"] else None,
        "risk_count": len(result["quality_risks"]),
        "evidence_count": len(result["evidence"]),
        "guardrail_count": len(result.get("guardrail_issues", [])),
        "next_actions": result.get("next_actions", []),
        "report_path": str(report_path),
    }
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
