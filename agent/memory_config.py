from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        return min(max(float(os.getenv(name, str(default))), minimum), maximum)
    except (TypeError, ValueError):
        return default


MEMORY_DB_PATH = Path(
    os.getenv("CITRUS_MEMORY_DB_PATH", str(ROOT / "data" / "memory" / "memory.db"))
).expanduser()
MEMORY_RECENT_TOKEN_LIMIT = _env_int("CITRUS_MEMORY_RECENT_TOKEN_LIMIT", 2400, 256)
MEMORY_SUMMARY_TRIGGER_TOKENS = _env_int("CITRUS_MEMORY_SUMMARY_TRIGGER_TOKENS", 4200, 512)
MEMORY_SUMMARY_TOKEN_LIMIT = _env_int("CITRUS_MEMORY_SUMMARY_TOKEN_LIMIT", 1100, 256)
MEMORY_LONG_TERM_TOP_K = _env_int("CITRUS_MEMORY_LONG_TERM_TOP_K", 6, 1)
MEMORY_SAMPLE_TOP_K = _env_int("CITRUS_MEMORY_SAMPLE_TOP_K", 4, 1)
MEMORY_MIN_RELEVANCE = _env_float("CITRUS_MEMORY_MIN_RELEVANCE", 0.18)
MEMORY_TOOL_RESULT_CHARS = _env_int("CITRUS_MEMORY_TOOL_RESULT_CHARS", 1400, 200)
MEMORY_MAX_CONTENT_CHARS = _env_int("CITRUS_MEMORY_MAX_CONTENT_CHARS", 12000, 1000)
MEMORY_PROMPT_VERSION = os.getenv("CITRUS_MEMORY_PROMPT_VERSION", "citrus-memory-v1").strip()

CONTEXT_TOKEN_BUDGETS = {
    "system": _env_int("CITRUS_CONTEXT_SYSTEM_TOKENS", 1600, 256),
    "profile": _env_int("CITRUS_CONTEXT_PROFILE_TOKENS", 500, 128),
    "working_memory": _env_int("CITRUS_CONTEXT_WORKING_TOKENS", 900, 256),
    "summary": _env_int("CITRUS_CONTEXT_SUMMARY_TOKENS", 1000, 256),
    "long_term": _env_int("CITRUS_CONTEXT_LONG_TERM_TOKENS", 1100, 256),
    "samples": _env_int("CITRUS_CONTEXT_SAMPLE_TOKENS", 1000, 256),
    "literature": _env_int("CITRUS_CONTEXT_LITERATURE_TOKENS", 5200, 512),
    "recent_dialog": MEMORY_RECENT_TOKEN_LIMIT,
    "tool_results": _env_int("CITRUS_CONTEXT_TOOL_TOKENS", 1000, 256),
    "current_input": _env_int("CITRUS_CONTEXT_CURRENT_INPUT_TOKENS", 1400, 256),
}

ALLOWED_MEMORY_TYPES = {
    "user_preference",
    "project_decision",
    "task_event",
    "experiment_parameter",
    "sample_record",
    "tool_result",
    "document_reference",
    "domain_fact",
}
