"""Connect saved batch facts to the evidence-aware literature workflow."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Callable

from agent import workflow


def input_key(source: dict[str, Any]) -> str:
    payload = {key: source.get(key) for key in ("batch", "cleaning", "task_context")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def workflow_batch(source: dict[str, Any]) -> dict[str, Any]:
    facts = dict(source.get("batch") or {})
    batch = {
        **facts,
        "batch_id": facts.get("batch_id") or facts.get("batch") or "未命名批次",
        "weight_kg": facts.get("weight_kg", facts.get("quantity_kg")),
    }
    labels = {"pesticide": "农残", "heavy_metal": "重金属", "microbe": "微生物", "aflatoxin": "黄曲霉毒素"}
    tests = facts.get("safety_tests") or []
    if isinstance(tests, str):
        tests = [tests]
    for key, label in labels.items():
        if key in facts:
            continue
        clauses = [clause for value in tests for clause in re.split(r"[，,。；;\n]", str(value)) if label in clause]
        # Negative and missing results must take precedence over words such as
        # "通过" contained in "未通过". A report's existence is not a pass.
        if any(re.search(r"不合格|未通过|超标|阳性|异常", clause) for clause in clauses):
            value, status = False, "failed"
        elif any(re.search(r"尚未|未做|未检测|待检|缺少|未提供", clause) for clause in clauses):
            value, status = None, "missing"
        elif clauses and all(re.search(r"合格|通过|符合要求|未检出", clause) for clause in clauses):
            value, status = True, "passed"
        else:
            value, status = None, "result_missing" if clauses else "missing"
        batch[key], batch[f"{key}_status"] = value, status
    return batch


def retrieval_summary(result: dict[str, Any]) -> tuple[str, bool]:
    stats = result.get("deep_retrieval_stats") or {}
    evidence = result.get("evidence") or []
    documents = {str(item.get("document_id") or item.get("source_file") or item.get("title")) for item in evidence}
    partial = (stats.get("database_available") is False or stats.get("retrieval_complete") is False
               or bool(stats.get("timed_out")) or bool(stats.get("retrieval_error")))
    if stats.get("database_available") is False:
        prefix = "完整文献库未能加载，仅返回当前可用资料"
    elif partial:
        prefix = "文献检索部分完成，可重试或调整检索方式"
    elif not evidence:
        return "已执行文献检索，未找到可用依据；当前仅有规则建议", True
    else:
        prefix = "已检索本地文献库"
    return f"{prefix} · 纳入 {len(documents)} 篇文献、{len(evidence)} 条证据", partial


def generate_batch_research(
    source: dict[str, Any], *, page: str, retrieval_mode: str = "quick",
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if page not in {"decision", "process"}:
        raise ValueError("不支持的分析页面。")
    batch = workflow_batch(source)
    target = str(batch.get("target_product") or "").strip()
    question = "比较当前批次的候选加工路线、文献支持及适用条件。" if page == "decision" else "制定当前批次的加工工艺，检索各单元操作、参数和质量控制的文献依据。"
    if target:
        question += f"目标产品：{target}。"
    # Intake records do not contain a vision observation.  Keep the second
    # workflow argument semantically correct instead of passing the quality
    # grade as if it were an image description; the grade is already part of
    # ``batch`` and is consumed by the quality and scoring tools there.
    image_observation = str(
        batch.get("image_observation")
        or batch.get("appearance_observation")
        or ""
    )
    result = workflow.serialize_result(workflow.run_demo_agent(
        batch, image_observation,
        analysis_question=question, retrieval_mode=retrieval_mode,
        progress_callback=progress_callback,
    ))
    summary, partial = retrieval_summary(result)
    result.update(
        cleaning=source.get("cleaning") or {}, task_context=source.get("task_context") or {},
        source="literature_workflow", research_status=summary, research_partial=partial,
        research_generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        research_input_key=input_key(source),
    )
    return result
