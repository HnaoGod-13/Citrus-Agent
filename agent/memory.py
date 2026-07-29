from __future__ import annotations

from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LITERATURE_PATH = ROOT / "data" / "literature" / "chunks.jsonl"


def _safe_count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


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
            "knowledge_sources": ["data/literature/chunks.jsonl"],
        },
    }
