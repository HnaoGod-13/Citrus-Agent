from __future__ import annotations

import os


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


PROCESS_SUBQUERY_TOP_K = _positive_int("CITRUS_PROCESS_SUBQUERY_TOP_K", 5)
PROCESS_EVIDENCE_TOP_K = _positive_int("CITRUS_PROCESS_EVIDENCE_TOP_K", 24)
PROCESS_PARAMETER_LIMIT = _positive_int("CITRUS_PROCESS_PARAMETER_LIMIT", 64)
PROCESS_CONTEXT_EVIDENCE_LIMIT = _positive_int("CITRUS_PROCESS_CONTEXT_EVIDENCE_LIMIT", 12)
PROCESS_CONTEXT_PARAMETER_LIMIT = _positive_int("CITRUS_PROCESS_CONTEXT_PARAMETER_LIMIT", 24)
PROCESS_CONTEXT_TOKEN_LIMIT = _positive_int("CITRUS_PROCESS_CONTEXT_TOKEN_LIMIT", 2800)
