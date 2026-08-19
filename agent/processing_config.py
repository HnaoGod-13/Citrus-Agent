from __future__ import annotations

import os


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _positive_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


PROCESS_SUBQUERY_TOP_K = _positive_int("CITRUS_PROCESS_SUBQUERY_TOP_K", 5)
PROCESS_EVIDENCE_TOP_K = _positive_int("CITRUS_PROCESS_EVIDENCE_TOP_K", 24)
PROCESS_PARAMETER_LIMIT = _positive_int("CITRUS_PROCESS_PARAMETER_LIMIT", 64)
PROCESS_CONTEXT_EVIDENCE_LIMIT = _positive_int("CITRUS_PROCESS_CONTEXT_EVIDENCE_LIMIT", 12)
PROCESS_CONTEXT_PARAMETER_LIMIT = _positive_int("CITRUS_PROCESS_CONTEXT_PARAMETER_LIMIT", 24)
PROCESS_CONTEXT_TOKEN_LIMIT = _positive_int("CITRUS_PROCESS_CONTEXT_TOKEN_LIMIT", 2800)

# Deep retrieval widens the bounded candidate funnel without increasing the
# amount of raw literature sent to the answer model.
PROCESS_DEEP_SUBQUERY_TOP_K = _positive_int("CITRUS_PROCESS_DEEP_SUBQUERY_TOP_K", 10)
PROCESS_DEEP_MAX_PER_QUERY = _positive_int("CITRUS_PROCESS_DEEP_MAX_PER_QUERY", 64)
PROCESS_DEEP_MAX_DATABASE_CANDIDATES = _positive_int(
    "CITRUS_PROCESS_DEEP_MAX_DATABASE_CANDIDATES", 150
)
PROCESS_DEEP_MAX_FTS_ROWS = _positive_int("CITRUS_PROCESS_DEEP_MAX_FTS_ROWS", 600)
PROCESS_DEEP_NEIGHBOR_DOCUMENT_LIMIT = _positive_int(
    "CITRUS_PROCESS_DEEP_NEIGHBOR_DOCUMENT_LIMIT", 12
)
PROCESS_DEEP_NEIGHBOR_RADIUS = _positive_int("CITRUS_PROCESS_DEEP_NEIGHBOR_RADIUS", 3)
PROCESS_DEEP_NEIGHBOR_PER_HIT = _positive_int("CITRUS_PROCESS_DEEP_NEIGHBOR_PER_HIT", 2)
PROCESS_DEEP_NEIGHBOR_LIMIT = _positive_int("CITRUS_PROCESS_DEEP_NEIGHBOR_LIMIT", 24)
PROCESS_DEEP_QUERY_CHARS = _positive_int("CITRUS_PROCESS_DEEP_QUERY_CHARS", 900)
PROCESS_DEEP_TIME_BUDGET_SECONDS = _positive_float(
    "CITRUS_PROCESS_DEEP_TIME_BUDGET_SECONDS", 75.0
)
PROCESS_DEEP_SQL_TIMEOUT_SECONDS = _positive_float(
    "CITRUS_PROCESS_DEEP_SQL_TIMEOUT_SECONDS", 15.0
)
PROCESS_UNRESOLVED_PARAMETER_LIMIT = _positive_int(
    "CITRUS_PROCESS_UNRESOLVED_PARAMETER_LIMIT", 8
)
