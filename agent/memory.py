from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "cases" / "demo_cases.json"
LITERATURE_PATH = ROOT / "data" / "literature" / "chunks.jsonl"


def _safe_count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


def _load_case_summaries(limit: int = 3) -> list[dict[str, Any]]:
    if not CASES_PATH.exists():
        return []
    try:
        data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(data, dict):
        cases = data.get("cases", [])
    else:
        cases = data
    summaries: list[dict[str, Any]] = []
    for item in cases[:limit]:
        if not isinstance(item, dict):
            continue
        summaries.append(
            {
                "batch_id": item.get("batch_id") or item.get("id") or "demo",
                "origin": item.get("origin"),
                "variety": item.get("variety"),
                "customer_type": item.get("customer_type"),
            }
        )
    return summaries


def build_memory_snapshot(batch: dict[str, Any], image_observation: str, product_filter: str) -> dict[str, Any]:
    """Build controlled short-term and long-term context without changing UI state."""
    return {
        "short_term": {
            "current_batch_id": batch.get("batch_id"),
            "origin": batch.get("origin"),
            "variety": batch.get("variety"),
            "customer_type": batch.get("customer_type"),
            "image_observation": image_observation or "未填写",
            "product_filter": product_filter,
        },
        "long_term": {
            "literature_chunk_count": _safe_count_jsonl(LITERATURE_PATH),
            "demo_case_summaries": _load_case_summaries(),
            "knowledge_sources": ["data/literature/chunks.jsonl", "data/cases/demo_cases.json"],
        },
    }
