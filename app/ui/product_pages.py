"""Product pages used by the Citrus AI Streamlit application.

Stored-record queries are always scoped by both ``memory_user_id`` and
``memory_project_id``. Settings exposes explicit, confirmed export and deletion
controls for that exact scope. If identity is unavailable, pages render a safe
empty state rather than falling back to an unscoped query.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import html
import importlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator

import streamlit as st

from agent import memory as agent_memory
from app import knowledge_catalog as catalog_index
from app.ui import components as ui_components
from app.ui import industry_pages as ui_industry_pages


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_DB_PATH = PROJECT_ROOT / "data" / "memory" / "memory.db"
DEFAULT_LITERATURE_DB_PATH = PROJECT_ROOT / "data" / "literature" / "literature.db"
DEFAULT_KNOWLEDGE_CATALOG_PATH = PROJECT_ROOT / "data" / "literature" / "knowledge_catalog.db"

WORKSPACE_LIMIT = 16
KNOWLEDGE_LIMIT = 200
KNOWLEDGE_PAGE_SIZE = 30
ANALYTICS_RECENT_LIMIT = 24
ANALYTICS_DAY_LIMIT = 30
ANALYTICS_TREND_DAYS = 14
BEIJING_TIMEZONE = timezone(timedelta(hours=8))
SAMPLE_REVIEW_STATUSES = frozenset({"暂不可放行", "检测待补", "质量复核"})
DIRECT_CITRUS_TITLE_MARKERS = catalog_index.DIRECT_CITRUS_TITLE_MARKERS
OFF_DOMAIN_TITLE_MARKERS = catalog_index.OFF_DOMAIN_TITLE_MARKERS
OFF_DOMAIN_TITLE_PATTERN = catalog_index.OFF_DOMAIN_TITLE_PATTERN


@dataclass(frozen=True)
class _Scope:
    user_id: str
    project_id: str
    session_id: str = ""


def _current_scope() -> _Scope | None:
    """Return the initialized memory scope without inventing a fallback user."""
    try:
        user_id = str(st.session_state.get("memory_user_id") or "").strip()
        project_id = str(st.session_state.get("memory_project_id") or "").strip()
        session_id = str(st.session_state.get("memory_session_id") or "").strip()
    except Exception:
        return None
    if not user_id or not project_id:
        return None
    return _Scope(user_id=user_id, project_id=project_id, session_id=session_id)


def _memory_db_path() -> Path:
    try:
        from agent import memory_config

        return Path(memory_config.MEMORY_DB_PATH)
    except (AttributeError, ImportError, TypeError):
        return DEFAULT_MEMORY_DB_PATH


def _literature_db_path() -> Path:
    try:
        from agent import rag

        return Path(rag.LITERATURE_DB_PATH)
    except (AttributeError, ImportError, TypeError):
        return DEFAULT_LITERATURE_DB_PATH


def _knowledge_browse_db_path() -> Path:
    """Prefer the metadata-only browser catalog over the full RAG database."""
    try:
        if DEFAULT_KNOWLEDGE_CATALOG_PATH.is_file() and DEFAULT_KNOWLEDGE_CATALOG_PATH.stat().st_size > 0:
            return DEFAULT_KNOWLEDGE_CATALOG_PATH
    except OSError:
        pass
    return _literature_db_path()


def _prepare_literature_database(path: Path) -> bool:
    """Materialize the configured packaged index without mutating source data."""
    candidate = Path(path).expanduser()
    if candidate.is_file() and candidate.stat().st_size > 0:
        return True
    try:
        from agent import rag

        configured = Path(rag.LITERATURE_DB_PATH).expanduser()
        if candidate.resolve() != configured.resolve():
            return False
        return bool(rag.ensure_literature_database(candidate))
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return False


@contextmanager
def _readonly_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a SQLite database in URI read-only and query-only modes."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved.name)

    connection = sqlite3.connect(
        resolved.as_uri() + "?mode=ro",
        uri=True,
        timeout=3,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 3000")
        yield connection
    finally:
        connection.close()


def _row_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _compact_text(value: Any, limit: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text or "—"
    return text[: max(limit - 1, 1)].rstrip() + "…"


def _plain_summary(value: Any, limit: int = 120) -> str:
    """Return the first useful paragraph without Markdown presentation syntax."""
    raw = html.unescape(str(value or "")).strip()
    if not raw:
        return "—"

    raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.DOTALL)
    raw = re.sub(r"```(?:[^\n]*)\n?(.*?)```", r"\1", raw, flags=re.DOTALL)
    for paragraph in re.split(r"\n\s*\n", raw):
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and re.match(r"^#{1,6}\s+", lines[0]):
            continue

        cleaned_lines: list[str] = []
        for line in lines:
            if re.fullmatch(r"\|?(?:\s*:?-{3,}:?\s*\|)+", line):
                continue
            line = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", line)
            line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", line)
            line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
            line = re.sub(r"[*_~`]", "", line)
            line = line.strip(" |")
            if line:
                cleaned_lines.append(line)
        if cleaned_lines:
            return _compact_text(" ".join(cleaned_lines), limit)
    return "—"


def _task_summary(value: Any, limit: int = 92) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    concise = re.split(
        r"请完整运行\s*(?:Agent\s*)?工作流程\s*[:：]?",
        raw,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].rstrip(" ,，。;；:：")
    return _plain_summary(concise or raw, limit)


def _tool_result_summary(tool_calls: Any, tool_name: str) -> str:
    wanted = tool_name.casefold()
    for item in _json_list(tool_calls):
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or item.get("name") or "").casefold()
        if wanted not in name:
            continue
        summary = (
            item.get("result_summary")
            or item.get("observation")
            or item.get("summary")
        )
        if str(summary or "").strip():
            return str(summary).strip()
    return ""


def _evidence_count(value: Any) -> int:
    return len(
        {
            str(item).strip()
            for item in _json_list(value)
            if str(item).strip()
        }
    )


def _evidence_label(value: Any) -> str:
    count = _evidence_count(value)
    return f"{count} 条证据" if count else "暂无证据"


def _workspace_session_row(row: dict[str, Any]) -> dict[str, Any]:
    question = row.get("last_user_message") or row.get("last_run_input")
    last_user_message_id = int(row.get("last_user_message_id") or 0)
    last_assistant_message_id = int(row.get("last_assistant_message_id") or 0)
    ordering_known = (
        "last_user_message_id" in row or "last_assistant_message_id" in row
    )
    answer_is_current = (
        not ordering_known
        or not last_user_message_id
        or last_assistant_message_id > last_user_message_id
    )
    conclusion = (
        row.get("last_assistant_message") or row.get("last_run_output")
        if answer_is_current
        else None
    )
    turns = int(row.get("user_turn_count") or 0)
    if answer_is_current and str(row.get("last_run_error") or "").strip():
        progress = "需要重试"
    elif str(conclusion or "").strip():
        progress = f"已回复 · {turns} 轮" if turns else "已回复"
    elif answer_is_current and int(row.get("run_count") or 0):
        progress = "分析中"
    else:
        progress = "待回复"
    return {
        "主题": _task_summary(question, 72),
        "最新结论": _plain_summary(conclusion, 116),
        "进度": progress,
        "最近时间": _display_time(row.get("activity_at") or row.get("updated_at")),
    }


def _workspace_run_row(row: dict[str, Any]) -> dict[str, Any]:
    route_result = _tool_result_summary(
        row.get("tool_calls_json"), "Evidence-aware Route Ranker"
    )
    quality_result = _tool_result_summary(row.get("tool_calls_json"), "Quality Gate")
    error = str(row.get("error") or "").strip()
    if error:
        status = "异常"
    else:
        risk_match = re.search(r"发现\s*(\d+)\s*个需复核风险项", quality_result)
        status = "完成 · 待复核" if risk_match and int(risk_match.group(1)) else "完成"

    result = route_result or row.get("final_output") or error
    return {
        "分析任务": _task_summary(row.get("original_input"), 82),
        "主要结果": _plain_summary(result, 116),
        "状态": status,
        "证据": _evidence_label(row.get("retrieved_literature_ids_json")),
        "时间": _display_time(row.get("created_at")),
    }


def _format_metric_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "").strip()
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}".rstrip("0").rstrip(".")


def _sample_metrics_summary(value: Any) -> str:
    metrics = _json_object(value)
    fields = (
        ("weight_kg", "重量", " kg"),
        ("brix", "糖度", " °Brix"),
        ("acidity", "酸度", "%"),
        ("moisture", "水分", "%"),
    )
    parts = []
    for key, label, suffix in fields:
        if metrics.get(key) in (None, ""):
            continue
        formatted = _format_metric_number(metrics[key])
        if formatted:
            parts.append(f"{label} {formatted}{suffix}")
    return " · ".join(parts) or "指标待补"


def _sample_direction(row: dict[str, Any]) -> str:
    solution = str(row.get("solution") or "").strip()
    direction = re.split(r"[；;\n]", solution, maxsplit=1)[0].strip()
    if direction:
        return _plain_summary(direction, 64)
    return _plain_summary(row.get("processing_goal"), 64)


def _sample_quality_status(row: dict[str, Any]) -> str:
    quality = str(row.get("disease_or_quality") or "").strip()
    metrics = _json_object(row.get("metrics_json"))
    blocking_terms = (
        "不能输出最终放行",
        "不可放行",
        "不得进入",
        "疑似霉变",
        "腐烂",
        "高风险",
    )
    if any(term in quality for term in blocking_terms):
        return "暂不可放行"
    if any(str(value).strip().lower() == "missing" for value in metrics.values()):
        return "检测待补"
    return "质量复核" if quality else "检测待补"


def _sample_needs_review(row: dict[str, Any]) -> bool:
    return _sample_quality_status(row) in SAMPLE_REVIEW_STATUSES


def _workspace_sample_row(row: dict[str, Any]) -> dict[str, Any]:
    variety = str(row.get("variety") or "").strip() or "品种待补"
    origin = str(row.get("origin") or "").strip() or "产地待补"
    return {
        "批次概况": _compact_text(f"{variety} · {origin}", 56),
        "关键指标": _sample_metrics_summary(row.get("metrics_json")),
        "建议方向": _sample_direction(row),
        "质控状态": _sample_quality_status(row),
        "更新时间": _display_time(row.get("updated_at")),
    }


def _display_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        fallback = text.replace("T", " ")
        return fallback[:16] if len(fallback) >= 16 else fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BEIJING_TIMEZONE).strftime("%Y-%m-%d %H:%M")


def _short_id(value: Any, left: int = 8, right: int = 4) -> str:
    text = str(value or "").strip()
    if len(text) <= left + right + 1:
        return text or "—"
    return f"{text[:left]}…{text[-right:]}"


def _source_name(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1] if text else "—"


def _is_off_domain_knowledge_title(value: Any) -> bool:
    return catalog_index.is_off_domain_title(value)


def _knowledge_relevance_label(value: Any) -> str:
    if catalog_index.relevance_rank(value) == 0:
        return "柑橘直接证据"
    return "工艺参考"


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _title_contains_any_sql(markers: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    clause = " OR ".join(
        "COALESCE(d.title, '') LIKE ? ESCAPE char(92) COLLATE NOCASE"
        for _ in markers
    )
    parameters = tuple(f"%{_escape_like_literal(marker)}%" for marker in markers)
    return f"({clause})", parameters


def _database_signature(path: Path) -> tuple[str, int, int]:
    resolved = Path(path).expanduser().resolve()
    stat = resolved.stat()
    return str(resolved), int(stat.st_mtime_ns), int(stat.st_size)


def _is_knowledge_catalog(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'catalog_meta'"
    ).fetchone() is not None


def _set_knowledge_page(page: int) -> None:
    st.session_state.citrus_product_knowledge_page = max(int(page), 1)


def _render_page_header(eyebrow: str, title: str, subtitle: str, english: str) -> None:
    st.markdown(
        f"""
        <header class="product-page-header">
            <div class="product-page-eyebrow">{html.escape(eyebrow)}</div>
            <h1 class="product-page-title">{html.escape(title)}</h1>
            <p class="product-page-subtitle">{html.escape(subtitle)}</p>
            <p class="product-page-subtitle-en">{html.escape(english)}</p>
        </header>
        """,
        unsafe_allow_html=True,
    )


def _render_scope_empty() -> None:
    st.info("当前会话身份尚未初始化。请先进入对话页完成会话初始化，再查看当前用户的数据。")


def _render_data_unavailable(label: str) -> None:
    st.info(f"{label}暂不可用，或当前存储中还没有可展示的数据。")


def _render_table(
    rows: list[dict[str, Any]],
    empty_message: str,
    *,
    height: int = 360,
    variant: str = "data",
) -> None:
    ui_components.render_light_table(
        rows,
        empty_message,
        height=height,
        variant=variant,
    )


def _load_workspace(path: Path, scope: _Scope) -> dict[str, Any]:
    with _readonly_database(path) as connection:
        counts = dict(
            connection.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*) FROM (
                            SELECT session_id
                            FROM conversation_messages
                            WHERE user_id = ? AND project_id = ?
                              AND role IN ('user', 'assistant')
                            UNION
                            SELECT session_id
                            FROM agent_runs
                            WHERE user_id = ? AND project_id = ?
                        ) scoped_sessions
                    ) AS sessions,
                    (
                        SELECT COUNT(*)
                        FROM conversation_messages
                        WHERE user_id = ? AND project_id = ?
                          AND role IN ('user', 'assistant')
                    ) AS messages,
                    (
                        SELECT COUNT(*)
                        FROM agent_runs
                        WHERE user_id = ? AND project_id = ?
                    ) AS runs,
                    (
                        SELECT COUNT(*)
                        FROM agent_runs
                        WHERE user_id = ? AND project_id = ?
                          AND TRIM(COALESCE(error, '')) = ''
                    ) AS completed_runs,
                    (
                        SELECT COUNT(*)
                        FROM agent_runs
                        WHERE user_id = ? AND project_id = ?
                          AND TRIM(COALESCE(error, '')) <> ''
                    ) AS failed_runs,
                    (
                        SELECT COUNT(*)
                        FROM citrus_samples
                        WHERE user_id = ? AND project_id = ? AND status = 'active'
                    ) AS samples
                """,
                (
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                ),
            ).fetchone()
        )
        review_sample_rows = _row_dicts(
            connection.execute(
                """
                SELECT disease_or_quality, metrics_json
                FROM citrus_samples
                WHERE user_id = ? AND project_id = ? AND status = 'active'
                """,
                (scope.user_id, scope.project_id),
            )
        )
        counts["review_samples"] = sum(
            _sample_needs_review(row) for row in review_sample_rows
        )

        sessions = _row_dicts(
            connection.execute(
                """
                WITH scoped_messages AS (
                    SELECT id, session_id, role, content, created_at
                    FROM conversation_messages
                    WHERE user_id = ? AND project_id = ?
                      AND role IN ('user', 'assistant')
                ),
                message_summary AS (
                    SELECT session_id, COUNT(*) AS message_count,
                           SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS user_turn_count,
                           MAX(CASE WHEN role = 'user' THEN id END) AS last_user_message_id,
                           MAX(CASE WHEN role = 'assistant' THEN id END) AS last_assistant_message_id,
                           MAX(created_at) AS last_message_at
                    FROM scoped_messages
                    GROUP BY session_id
                ),
                last_user_messages AS (
                    SELECT message_summary.session_id, scoped_messages.content
                    FROM message_summary
                    JOIN scoped_messages
                      ON scoped_messages.id = message_summary.last_user_message_id
                ),
                last_assistant_messages AS (
                    SELECT message_summary.session_id, scoped_messages.content
                    FROM message_summary
                    JOIN scoped_messages
                      ON scoped_messages.id = message_summary.last_assistant_message_id
                ),
                scoped_runs AS (
                    SELECT session_id, original_input, final_output, error, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY session_id
                               ORDER BY created_at DESC, run_id DESC
                           ) AS recency_rank
                    FROM agent_runs
                    WHERE user_id = ? AND project_id = ?
                ),
                run_summary AS (
                    SELECT session_id, COUNT(*) AS run_count,
                           MAX(created_at) AS last_run_at
                    FROM scoped_runs
                    GROUP BY session_id
                ),
                last_runs AS (
                    SELECT session_id, original_input, final_output, error
                    FROM scoped_runs
                    WHERE recency_rank = 1
                )
                SELECT s.session_id, s.status, s.created_at, s.updated_at,
                       COALESCE(message_summary.message_count, 0) AS message_count,
                       COALESCE(message_summary.user_turn_count, 0) AS user_turn_count,
                       COALESCE(run_summary.run_count, 0) AS run_count,
                       message_summary.last_user_message_id AS last_user_message_id,
                       message_summary.last_assistant_message_id AS last_assistant_message_id,
                       last_user_messages.content AS last_user_message,
                       last_assistant_messages.content AS last_assistant_message,
                       last_runs.original_input AS last_run_input,
                       last_runs.final_output AS last_run_output,
                       last_runs.error AS last_run_error,
                       MAX(
                           COALESCE(message_summary.last_message_at, ''),
                           COALESCE(run_summary.last_run_at, '')
                       ) AS activity_at
                FROM sessions s
                LEFT JOIN message_summary ON message_summary.session_id = s.session_id
                LEFT JOIN last_user_messages ON last_user_messages.session_id = s.session_id
                LEFT JOIN last_assistant_messages ON last_assistant_messages.session_id = s.session_id
                LEFT JOIN run_summary ON run_summary.session_id = s.session_id
                LEFT JOIN last_runs ON last_runs.session_id = s.session_id
                WHERE s.user_id = ? AND s.project_id = ?
                  AND (
                      COALESCE(message_summary.message_count, 0) > 0
                      OR COALESCE(run_summary.run_count, 0) > 0
                  )
                ORDER BY activity_at DESC
                LIMIT ?
                """,
                (
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    WORKSPACE_LIMIT,
                ),
            )
        )

        runs = _row_dicts(
            connection.execute(
                """
                SELECT run_id, session_id, original_input, tool_calls_json,
                       retrieved_literature_ids_json, final_output, error, created_at
                FROM agent_runs
                WHERE user_id = ? AND project_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (scope.user_id, scope.project_id, WORKSPACE_LIMIT),
            )
        )

        samples = _row_dicts(
            connection.execute(
                """
                SELECT sample_id, session_id, variety, origin, processing_goal,
                       metrics_json, solution, disease_or_quality, status, updated_at
                FROM citrus_samples
                WHERE user_id = ? AND project_id = ? AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (scope.user_id, scope.project_id, WORKSPACE_LIMIT),
            )
        )

    return {"counts": counts, "sessions": sessions, "runs": runs, "samples": samples}


def render_workspace_page() -> None:
    ui_industry_pages.render_industry_workspace()


def current_industry_view() -> str:
    """Expose the workspace section selected by the original sidebar."""
    global ui_industry_pages
    resolver = getattr(ui_industry_pages, "current_industry_view", None)
    if not callable(resolver):
        importlib.invalidate_caches()
        ui_industry_pages = importlib.reload(ui_industry_pages)
        resolver = ui_industry_pages.current_industry_view
    return resolver()


def _query_knowledge_facets(path: Path) -> dict[str, Any]:
    with _readonly_database(path) as connection:
        if _is_knowledge_catalog(connection):
            meta = {
                str(row["key"]): str(row["value"])
                for row in connection.execute(
                    """
                    SELECT key, value
                    FROM catalog_meta
                    WHERE key IN ('visible_documents', 'visible_chunks')
                    """
                )
            }
            category_counts = Counter(
                {
                    str(row["category"]): int(row["document_count"])
                    for row in connection.execute(
                        "SELECT category, document_count FROM category_counts ORDER BY category"
                    )
                }
            )
            return {
                "stats": {
                    "documents": int(meta.get("visible_documents") or 0),
                    "chunks": int(meta.get("visible_chunks") or 0),
                },
                "categories": category_counts,
            }

        off_domain_sql, off_domain_parameters = _title_contains_any_sql(
            OFF_DOMAIN_TITLE_MARKERS
        )
        stats = dict(
            connection.execute(
                f"""
                WITH eligible_documents AS (
                    SELECT d.document_id
                    FROM documents d
                    WHERE NOT {off_domain_sql}
                )
                SELECT
                    (SELECT COUNT(*) FROM eligible_documents) AS documents,
                    (
                        SELECT COUNT(*)
                        FROM chunks c
                        WHERE c.document_id IN (
                            SELECT document_id FROM eligible_documents
                        )
                    ) AS chunks
                """,
                off_domain_parameters,
            ).fetchone()
        )
        category_rows = _row_dicts(
            connection.execute(
                f"SELECT d.categories FROM documents d WHERE NOT {off_domain_sql}",
                off_domain_parameters,
            )
        )

    category_counts: Counter[str] = Counter()
    for row in category_rows:
        for item in _json_list(row.get("categories")):
            category = str(item or "").strip()
            if category:
                category_counts[category] += 1
    return {"stats": stats, "categories": category_counts}


@st.cache_data(show_spinner=False, max_entries=8)
def _load_knowledge_facets_cached(
    path_text: str,
    modified_ns: int,
    size: int,
) -> dict[str, Any]:
    del modified_ns, size
    return _query_knowledge_facets(Path(path_text))


def _load_knowledge_facets(path: Path) -> dict[str, Any]:
    return _load_knowledge_facets_cached(*_database_signature(path))


def _query_knowledge_documents(
    path: Path,
    *,
    search: str = "",
    category: str = "",
    limit: int = KNOWLEDGE_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    clean_search = " ".join(search.split())
    search_pattern = f"%{clean_search}%"
    category_pattern = f"%{category}%"
    fallback_parameters = (
        clean_search,
        search_pattern,
        search_pattern,
        search_pattern,
        search_pattern,
        search_pattern,
        category,
        category_pattern,
    )
    with _readonly_database(path) as connection:
        if _is_knowledge_catalog(connection):
            catalog_parameters = (
                clean_search,
                search_pattern,
                search_pattern,
                search_pattern,
                search_pattern,
                search_pattern,
                category,
                category,
            )
            catalog_where = """
                d.is_off_domain = 0
                AND (
                    ? = ''
                    OR COALESCE(d.title, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.authors, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.doi, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.publication, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.source_file, '') LIKE ? COLLATE NOCASE
                )
                AND (
                    ? = ''
                    OR EXISTS (
                        SELECT 1
                        FROM document_categories dc
                        WHERE dc.document_id = d.document_id AND dc.category = ?
                    )
                )
            """
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM documents d WHERE {catalog_where}",
                    catalog_parameters,
                ).fetchone()[0]
            )
            rows = _row_dicts(
                connection.execute(
                    f"""
                    SELECT d.document_id, d.title, d.authors, d.year, d.categories,
                           d.publication, d.doi, d.source_file, d.chunk_count,
                           d.text_quality
                    FROM documents d
                    WHERE {catalog_where}
                    ORDER BY d.relevance_rank, d.year_sort DESC, d.title COLLATE NOCASE
                    LIMIT ? OFFSET ?
                    """,
                    (
                        *catalog_parameters,
                        max(1, min(int(limit), KNOWLEDGE_LIMIT)),
                        max(int(offset), 0),
                    ),
                )
            )
            return {"total": total, "rows": rows}

        off_domain_sql, off_domain_parameters = _title_contains_any_sql(
            OFF_DOMAIN_TITLE_MARKERS
        )
        direct_citrus_sql, direct_citrus_parameters = _title_contains_any_sql(
            DIRECT_CITRUS_TITLE_MARKERS
        )
        where_parameters = (*fallback_parameters, *off_domain_parameters)
        total = int(
            connection.execute(
                f"""
                SELECT COUNT(*)
                FROM documents d
                WHERE (
                    ? = ''
                    OR COALESCE(d.title, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.authors, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.doi, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.publication, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.source_file, '') LIKE ? COLLATE NOCASE
                )
                AND (? = '' OR COALESCE(d.categories, '') LIKE ?)
                AND NOT {off_domain_sql}
                """,
                where_parameters,
            ).fetchone()[0]
        )
        rows = _row_dicts(
            connection.execute(
                f"""
                SELECT d.document_id, d.title, d.authors, d.year, d.categories,
                       d.publication, d.doi, d.source_file, d.chunk_count,
                       d.text_quality
                FROM documents d
                WHERE (
                    ? = ''
                    OR COALESCE(d.title, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.authors, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.doi, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.publication, '') LIKE ? COLLATE NOCASE
                    OR COALESCE(d.source_file, '') LIKE ? COLLATE NOCASE
                )
                AND (? = '' OR COALESCE(d.categories, '') LIKE ?)
                AND NOT {off_domain_sql}
                ORDER BY
                    CASE WHEN {direct_citrus_sql} THEN 0 ELSE 1 END,
                    CASE
                        WHEN TRIM(COALESCE(d.year, '')) GLOB '[0-9][0-9][0-9][0-9]'
                        THEN CAST(d.year AS INTEGER)
                        ELSE 0
                    END DESC,
                    d.title COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                (
                    *where_parameters,
                    *direct_citrus_parameters,
                    max(1, min(int(limit), KNOWLEDGE_LIMIT)),
                    max(int(offset), 0),
                ),
            )
        )
    return {"total": total, "rows": rows}


@st.cache_data(show_spinner=False, max_entries=64)
def _load_knowledge_documents_cached(
    path_text: str,
    modified_ns: int,
    size: int,
    search: str,
    category: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    del modified_ns, size
    return _query_knowledge_documents(
        Path(path_text),
        search=search,
        category=category,
        limit=limit,
        offset=offset,
    )


def _load_knowledge_documents(
    path: Path,
    *,
    search: str = "",
    category: str = "",
    limit: int = KNOWLEDGE_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    path_text, modified_ns, size = _database_signature(path)
    return _load_knowledge_documents_cached(
        path_text,
        modified_ns,
        size,
        search,
        category,
        limit,
        offset,
    )


def _list_text(
    value: Any,
    *,
    limit: int = 4,
    allow_plain_text: bool = False,
) -> str:
    items = [str(item).strip() for item in _json_list(value) if str(item).strip()]
    if not items and allow_plain_text:
        raw = str(value or "").strip()
        if raw:
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded = raw
            if isinstance(decoded, str) and decoded.strip():
                items = [decoded.strip()]
    if not items:
        return "—"
    shown = items[:limit]
    return "、".join(shown) + ("…" if len(items) > limit else "")


def _knowledge_quality_label(value: Any) -> str:
    labels = {
        "good": "已索引",
        "fair": "可用",
        "limited": "内容有限",
        "poor": "待复核",
        "ocr_required": "待 OCR",
    }
    return labels.get(str(value or "").strip().lower(), "状态未知")


def render_knowledge_page() -> None:
    _render_page_header(
        "CITRUS AI · KNOWLEDGE",
        "知识与标准",
        "检索已入库的柑橘直接证据与可迁移工艺参考。",
        "Search direct citrus evidence and transferable processing references",
    )
    path = _knowledge_browse_db_path()
    if not path.is_file():
        with st.spinner("正在准备文献索引…"):
            full_database_path = _literature_db_path()
            _prepare_literature_database(full_database_path)
            path = full_database_path
    try:
        facets = _load_knowledge_facets(path)
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
        _render_data_unavailable("知识库")
        return

    categories: Counter[str] = facets["categories"]
    options = ["全部", *[item for item, _ in categories.most_common()]]
    search_column, category_column = st.columns([2.2, 1])
    with search_column:
        search = st.text_input(
            "搜索文献",
            placeholder="搜索题名、作者、DOI 或来源",
            key="citrus_product_knowledge_search",
        )
    with category_column:
        selected_category = st.selectbox(
            "分类",
            options,
            key="citrus_product_knowledge_category",
        )

    category = "" if selected_category == "全部" else selected_category
    filter_signature = json.dumps([search, category], ensure_ascii=False)
    if st.session_state.get("citrus_product_knowledge_filter") != filter_signature:
        st.session_state.citrus_product_knowledge_filter = filter_signature
        st.session_state.citrus_product_knowledge_page = 1
    requested_page = max(
        int(st.session_state.get("citrus_product_knowledge_page", 1)),
        1,
    )
    try:
        listing = _load_knowledge_documents(
            path,
            search=search,
            category=category,
            limit=KNOWLEDGE_PAGE_SIZE,
            offset=(requested_page - 1) * KNOWLEDGE_PAGE_SIZE,
        )
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
        _render_data_unavailable("知识库检索")
        return

    total = int(listing["total"])
    page_count = max((total + KNOWLEDGE_PAGE_SIZE - 1) // KNOWLEDGE_PAGE_SIZE, 1)
    page = min(requested_page, page_count)
    if page != requested_page:
        st.session_state.citrus_product_knowledge_page = page
        listing = _load_knowledge_documents(
            path,
            search=search,
            category=category,
            limit=KNOWLEDGE_PAGE_SIZE,
            offset=(page - 1) * KNOWLEDGE_PAGE_SIZE,
        )

    stats = facets["stats"]
    ui_components.render_metric_cards([
        ("参考文献", int(stats.get("documents") or 0), ""),
        ("证据片段", int(stats.get("chunks") or 0), ""),
        ("分类", len(categories), ""),
    ], columns=3)

    st.caption(f"找到 {total} 篇参考文献")
    if page_count > 1:
        previous_column, page_column, next_column = st.columns([1, 2.4, 1])
        previous_column.button(
            "←",
            help="上一页",
            disabled=page <= 1,
            key="citrus_product_knowledge_previous_page",
            on_click=_set_knowledge_page,
            args=(page - 1,),
        )
        page_column.caption(f"第 {page} / {page_count} 页")
        next_column.button(
            "→",
            help="下一页",
            disabled=page >= page_count,
            key="citrus_product_knowledge_next_page",
            on_click=_set_knowledge_page,
            args=(page + 1,),
        )
    rows = [
        {
            "题名": _compact_text(row.get("title"), 112),
            "作者": _compact_text(
                _list_text(row.get("authors"), allow_plain_text=True),
                58,
            ),
            "年份": str(row.get("year") or "—"),
            "分类": _compact_text(_list_text(row.get("categories")), 42),
            "来源": _compact_text(row.get("publication") or _source_name(row.get("source_file")), 58),
            "用途": _knowledge_relevance_label(row.get("title")),
            "片段": int(row.get("chunk_count") or 0),
            "状态": _knowledge_quality_label(row.get("text_quality")),
        }
        for row in listing["rows"]
    ]
    _render_table(
        rows,
        "没有符合当前搜索和分类条件的文献。",
        height=520,
        variant="knowledge",
    )


def _load_analytics(path: Path, scope: _Scope) -> dict[str, Any]:
    with _readonly_database(path) as connection:
        counts = dict(
            connection.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*) FROM (
                            SELECT session_id
                            FROM conversation_messages
                            WHERE user_id = ? AND project_id = ?
                              AND role IN ('user', 'assistant')
                            UNION
                            SELECT session_id
                            FROM agent_runs
                            WHERE user_id = ? AND project_id = ?
                        ) scoped_sessions
                    ) AS sessions,
                    (SELECT COUNT(*) FROM conversation_messages
                     WHERE user_id = ? AND project_id = ?
                       AND role IN ('user', 'assistant')) AS messages,
                    (SELECT COUNT(*) FROM agent_runs
                     WHERE user_id = ? AND project_id = ?) AS runs,
                    (SELECT COUNT(*) FROM agent_runs
                     WHERE user_id = ? AND project_id = ?
                       AND TRIM(COALESCE(error, '')) = '') AS successful_runs,
                    (SELECT COUNT(*) FROM agent_runs
                     WHERE user_id = ? AND project_id = ?
                       AND TRIM(COALESCE(error, '')) <> '') AS failed_runs,
                    (SELECT COUNT(*) FROM citrus_samples
                     WHERE user_id = ? AND project_id = ? AND status = 'active') AS samples
                """,
                (
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                ),
            ).fetchone()
        )

        daily = _row_dicts(
            connection.execute(
                """
                SELECT DATE(datetime(created_at), '+8 hours') AS day,
                       COUNT(*) AS runs,
                       SUM(CASE WHEN TRIM(COALESCE(error, '')) = '' THEN 1 ELSE 0 END)
                           AS successful_runs,
                       SUM(CASE WHEN TRIM(COALESCE(error, '')) <> '' THEN 1 ELSE 0 END)
                           AS failed_runs
                FROM agent_runs
                WHERE user_id = ? AND project_id = ?
                  AND TRIM(COALESCE(created_at, '')) <> ''
                  AND datetime(created_at) IS NOT NULL
                GROUP BY DATE(datetime(created_at), '+8 hours')
                ORDER BY day DESC
                LIMIT ?
                """,
                (scope.user_id, scope.project_id, ANALYTICS_DAY_LIMIT),
            )
        )

        models = _row_dicts(
            connection.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(model_name), ''), 'controlled-local') AS model_name,
                       COUNT(*) AS runs,
                       SUM(CASE WHEN TRIM(COALESCE(error, '')) <> '' THEN 1 ELSE 0 END)
                           AS failed_runs
                FROM agent_runs
                WHERE user_id = ? AND project_id = ?
                GROUP BY COALESCE(NULLIF(TRIM(model_name), ''), 'controlled-local')
                ORDER BY runs DESC, model_name
                """,
                (scope.user_id, scope.project_id),
            )
        )

        recent_runs = _row_dicts(
            connection.execute(
                """
                SELECT run_id, original_input, model_name, tool_calls_json,
                       retrieved_literature_ids_json, error, created_at
                FROM agent_runs
                WHERE user_id = ? AND project_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (scope.user_id, scope.project_id, ANALYTICS_RECENT_LIMIT),
            )
        )

    return {
        "counts": counts,
        "daily": list(reversed(daily)),
        "models": models,
        "recent_runs": recent_runs,
    }


def _analytics_day(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _trend_activity_label(activity_day: date | None, today: date) -> str:
    if activity_day is None:
        return "—"
    days_ago = (today - activity_day).days
    if days_ago == 0:
        return "今天"
    if days_ago == 1:
        return "昨天"
    if 1 < days_ago < 7:
        return f"{days_ago} 天前"
    return f"{activity_day.month}月{activity_day.day}日"


def _build_run_trend(
    daily_rows: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    reference_day = today or datetime.now(BEIJING_TIMEZONE).date()
    by_day: dict[date, dict[str, int]] = {}
    for row in daily_rows:
        row_day = _analytics_day(row.get("day"))
        if row_day is None:
            continue
        bucket = by_day.setdefault(
            row_day,
            {"runs": 0, "successful_runs": 0, "failed_runs": 0},
        )
        runs = max(int(row.get("runs") or 0), 0)
        failed_runs = max(int(row.get("failed_runs") or 0), 0)
        successful_runs = max(
            int(row.get("successful_runs") or max(runs - failed_runs, 0)),
            0,
        )
        bucket["runs"] += runs
        bucket["successful_runs"] += successful_runs
        bucket["failed_runs"] += failed_runs

    current_start = reference_day - timedelta(days=ANALYTICS_TREND_DAYS - 1)
    previous_start = current_start - timedelta(days=ANALYTICS_TREND_DAYS)
    previous_end = current_start - timedelta(days=1)
    days: list[dict[str, Any]] = []
    for offset in range(ANALYTICS_TREND_DAYS):
        row_day = current_start + timedelta(days=offset)
        counts = by_day.get(
            row_day,
            {"runs": 0, "successful_runs": 0, "failed_runs": 0},
        )
        days.append({"day": row_day, **counts})

    current_runs = sum(item["runs"] for item in days)
    current_successful = sum(item["successful_runs"] for item in days)
    current_failed = sum(item["failed_runs"] for item in days)
    previous_runs = sum(
        counts["runs"]
        for row_day, counts in by_day.items()
        if previous_start <= row_day <= previous_end
    )

    if current_runs == previous_runs:
        comparison = "与前 14 天持平" if current_runs else "近 14 天暂无运行"
    elif previous_runs == 0:
        comparison = f"本周期新增 {current_runs} 次"
    else:
        change = round((current_runs - previous_runs) / previous_runs * 100)
        comparison = f"较前 14 天 {change:+d}%"

    active_days = [item for item in days if item["runs"] > 0]
    peak = max(active_days, key=lambda item: (item["runs"], item["day"]), default=None)
    peak_label = (
        f"{peak['day'].month}月{peak['day'].day}日 · {peak['runs']} 次"
        if peak
        else "—"
    )
    completion_rate = (
        f"{current_successful / current_runs * 100:.0f}%" if current_runs else "—"
    )
    max_runs = max((item["runs"] for item in days), default=0)
    latest_activity = max(by_day, default=None)

    return {
        "days": days,
        "period_label": (
            f"{current_start.month}月{current_start.day}日"
            f"至{reference_day.month}月{reference_day.day}日"
        ),
        "current_runs": current_runs,
        "previous_runs": previous_runs,
        "comparison": comparison,
        "active_days": len(active_days),
        "successful_runs": current_successful,
        "failed_runs": current_failed,
        "completion_rate": completion_rate,
        "peak_label": peak_label,
        "latest_activity_label": _trend_activity_label(latest_activity, reference_day),
        "max_runs": max_runs,
        "has_history": bool(by_day),
    }


def _render_run_trend(daily_rows: list[dict[str, Any]]) -> None:
    trend = _build_run_trend(daily_rows)
    if not trend["has_history"]:
        st.markdown(
            """
            <section class="analytics-trend-empty" aria-label="运行趋势空状态">
                <strong>暂无运行记录</strong>
                <span>当前账户还没有可汇总的分析运行。</span>
            </section>
            """,
            unsafe_allow_html=True,
        )
        return

    major_labels = {0, 3, 6, 9, ANALYTICS_TREND_DAYS - 1}
    bar_columns: list[str] = []
    max_runs = max(int(trend["max_runs"]), 1)
    for index, item in enumerate(trend["days"]):
        runs = int(item["runs"])
        successful_runs = int(item["successful_runs"])
        failed_runs = int(item["failed_runs"])
        bar_height = max(runs / max_runs * 88, 5) if runs else 0
        successful_share = successful_runs / runs * 100 if runs else 0
        failed_share = failed_runs / runs * 100 if runs else 0
        row_day: date = item["day"]
        axis_label = f"{row_day.month}/{row_day.day}"
        visible_label = (
            axis_label
            if index in major_labels or (runs and trend["active_days"] <= 4)
            else ""
        )
        aria_label = (
            f"{row_day.month}月{row_day.day}日，{runs} 次运行，"
            f"{successful_runs} 次完成，{failed_runs} 次异常"
        )
        bar_columns.append(
            f'<div class="analytics-trend-day">'
            f'<div class="analytics-trend-bar-zone" '
            f'title="{html.escape(aria_label, quote=True)}">'
            f'<span class="analytics-trend-bar{" is-empty" if not runs else ""}" '
            f'role="img" aria-label="{html.escape(aria_label, quote=True)}" '
            f'style="--bar-height:{bar_height:.2f}%;'
            f'--success-share:{successful_share:.2f}%;'
            f'--failed-share:{failed_share:.2f}%">'
            '<span class="analytics-trend-success"></span>'
            '<span class="analytics-trend-failed"></span>'
            '</span></div>'
            f'<span class="analytics-trend-axis-label">'
            f'<span class="analytics-trend-axis-desktop">'
            f'{html.escape(visible_label)}</span>'
            f'<span class="analytics-trend-axis-mobile">'
            f'{row_day.day if visible_label else ""}</span>'
            '</span></div>'
        )

    completion_note = (
        f"{trend['failed_runs']} 次异常"
        if trend["failed_runs"]
        else f"{trend['successful_runs']} 次完成"
    )
    st.markdown(
        f"""
        <section class="analytics-trend-panel" aria-label="近十四天运行趋势">
            <header class="analytics-trend-header">
                <div>
                    <div class="analytics-trend-period">近 14 天 · {html.escape(trend['period_label'])}</div>
                    <div class="analytics-trend-total">
                        <strong>{trend['current_runs']}</strong><span>次运行</span>
                    </div>
                    <div class="analytics-trend-compare">{html.escape(trend['comparison'])}</div>
                </div>
                <div class="analytics-trend-legend" aria-label="图例">
                    <span><i class="is-success"></i>完成</span>
                    <span><i class="is-failed"></i>异常</span>
                </div>
            </header>
            <div class="analytics-trend-plot">
                <span class="analytics-trend-grid-line is-top" aria-hidden="true"></span>
                <span class="analytics-trend-grid-line is-middle" aria-hidden="true"></span>
                <div class="analytics-trend-bars">
                    {''.join(bar_columns)}
                </div>
            </div>
            <dl class="analytics-trend-stats">
                <div>
                    <dt>活跃天数</dt>
                    <dd>{trend['active_days']}<small> / 14 天</small></dd>
                </div>
                <div>
                    <dt>近 14 天完成率</dt>
                    <dd>{html.escape(trend['completion_rate'])}<small>{html.escape(completion_note)}</small></dd>
                </div>
                <div>
                    <dt>峰值日</dt>
                    <dd>{html.escape(trend['peak_label'])}</dd>
                </div>
                <div>
                    <dt>最近运行</dt>
                    <dd>{html.escape(trend['latest_activity_label'])}</dd>
                </div>
            </dl>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _model_settings() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        from agent import llm_client

        configured = bool(llm_client.get_deepseek_api_key())
        rows.append(
            {
                "能力": "语言模型",
                "模型": str(llm_client.DEEPSEEK_MODEL),
                "配置状态": "已配置" if configured else "未配置",
                "用途": "普通问答与分析总结",
            }
        )
    except Exception:
        rows.append(
            {
                "能力": "语言模型",
                "模型": "不可用",
                "配置状态": "无法读取",
                "用途": "普通问答与分析总结",
            }
        )

    try:
        from agent import vision_client

        configured = bool(vision_client.get_vision_api_key())
        rows.append(
            {
                "能力": "视觉模型",
                "模型": str(vision_client.get_vision_model()),
                "配置状态": "已配置" if configured else "未配置",
                "用途": "柑橘图片外观识别",
            }
        )
    except Exception:
        rows.append(
            {
                "能力": "视觉模型",
                "模型": "不可用",
                "配置状态": "无法读取",
                "用途": "柑橘图片外观识别",
            }
        )
    return rows


def _scoped_storage_counts(path: Path, scope: _Scope) -> dict[str, int]:
    with _readonly_database(path) as connection:
        return dict(
            connection.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*) FROM (
                            SELECT session_id
                            FROM conversation_messages
                            WHERE user_id = ? AND project_id = ?
                              AND role IN ('user', 'assistant')
                            UNION
                            SELECT session_id
                            FROM agent_runs
                            WHERE user_id = ? AND project_id = ?
                        ) scoped_sessions
                    ) AS sessions,
                    (SELECT COUNT(*) FROM conversation_messages
                     WHERE user_id = ? AND project_id = ?) AS messages,
                    (SELECT COUNT(*) FROM agent_runs
                     WHERE user_id = ? AND project_id = ?) AS runs,
                    (SELECT COUNT(*) FROM memories
                     WHERE user_id = ? AND project_id = ? AND status = 'active') AS memories,
                    (SELECT COUNT(*) FROM citrus_samples
                     WHERE user_id = ? AND project_id = ? AND status = 'active') AS samples
                """,
                (
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                    scope.user_id,
                    scope.project_id,
                ),
            ).fetchone()
        )


def _knowledge_storage_counts(path: Path) -> dict[str, int]:
    with _readonly_database(path) as connection:
        if _is_knowledge_catalog(connection):
            meta = {
                str(row["key"]): int(row["value"])
                for row in connection.execute(
                    """
                    SELECT key, value
                    FROM catalog_meta
                    WHERE key IN ('source_documents', 'source_chunks')
                    """
                )
            }
            return {
                "documents": int(meta.get("source_documents") or 0),
                "chunks": int(meta.get("source_chunks") or 0),
            }
        return dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM documents) AS documents,
                    (SELECT COUNT(*) FROM chunks) AS chunks
                """
            ).fetchone()
        )


def _privacy_manager(scope: _Scope) -> agent_memory.MemoryManager:
    return agent_memory.MemoryManager(
        _memory_db_path(),
        default_user_id=scope.user_id,
        default_project_id=scope.project_id,
    )


def _privacy_event_label(value: Any) -> str:
    return {
        "session_created": "创建匿名会话",
        "session_resumed": "使用短期令牌恢复会话",
        "data_exported": "生成用户数据导出",
        "session_deleted": "删除会话数据",
        "retention_cleanup": "执行保存期限清理",
    }.get(str(value or ""), "隐私操作")


def _session_fingerprint(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def _clear_identity_query_values() -> None:
    try:
        for key in ("ctx", "uid", "sid"):
            if key in st.query_params:
                del st.query_params[key]
    except Exception:
        pass


def _reset_after_privacy_deletion(*, delete_all: bool) -> None:
    for key in (
        "agent_messages",
        "current_batch",
        "last_result",
        "last_vision_context",
        "memory_restored_session",
        "memory_session_id",
        "memory_context_token",
        "memory_privacy_event_marker",
        "active_agent_job_id",
        "active_agent_progress_revealed",
        "active_agent_retrieval_mode",
        "pending_agent_persistence",
        "privacy_export_json",
        "privacy_export_filename",
        "privacy_delete_session_confirmation",
        "privacy_delete_all_confirmation",
    ):
        st.session_state.pop(key, None)
    if delete_all:
        st.session_state.pop("memory_user_id", None)
        st.session_state.pop("memory_project_id", None)
    _clear_identity_query_values()


def _privacy_delete_disabled(
    confirmation: str,
    expected_phrase: str,
    *,
    active_job_running: bool,
) -> bool:
    return str(confirmation or "").strip() != expected_phrase or bool(active_job_running)


def _privacy_deletion_notice(
    *,
    delete_all: bool,
    file_cleanup_errors: int,
) -> dict[str, str]:
    failed = max(int(file_cleanup_errors or 0), 0)
    if failed:
        subject = "数据库中的项目数据" if delete_all else "当前会话的数据库记录"
        return {
            "level": "warning",
            "message": f"{subject}已删除，但有 {failed} 个已知文件清理失败，请联系管理员。",
        }
    return {
        "level": "success",
        "message": (
            "当前用户在本项目中的全部数据已删除，并已创建新的匿名身份。"
            if delete_all
            else "当前会话数据已删除，并已创建新的隔离会话。"
        ),
    }


def _prepare_privacy_export(
    manager: agent_memory.MemoryManager,
    scope: _Scope,
) -> dict[str, Any]:
    try:
        exported = manager.export_user_data(
            user_id=scope.user_id,
            project_id=scope.project_id,
        )
        manager.log_privacy_event(
            "data_exported",
            user_id=scope.user_id,
            project_id=scope.project_id,
            session_id=scope.session_id,
            details={"format": "json", "action": "prepared"},
        )
    except (agent_memory.MemoryManagerError, OSError, sqlite3.Error, ValueError):
        try:
            manager.log_privacy_event(
                "data_exported",
                user_id=scope.user_id,
                project_id=scope.project_id,
                session_id=scope.session_id,
                outcome="failed",
                details={"format": "json"},
            )
        except (agent_memory.MemoryManagerError, OSError, sqlite3.Error, ValueError):
            pass
        raise
    return exported


def render_settings_page() -> None:
    _render_page_header(
        "CITRUS AI · SETTINGS",
        "设置",
        "查看产品状态，并管理当前身份范围内的数据与隐私。",
        "Product status, scoped data controls and privacy",
    )

    deletion_notice = st.session_state.pop("privacy_deletion_notice", None)
    if isinstance(deletion_notice, dict):
        message = str(deletion_notice.get("message") or "")
        if message:
            if deletion_notice.get("level") == "warning":
                st.warning(message)
            else:
                st.success(message)

    st.subheader("产品")
    product_rows = [
        {"项目": "产品", "当前状态": "Citrus AI · Decision Lab"},
        {"项目": "前端运行时", "当前状态": f"Streamlit {getattr(st, '__version__', '未知')}"},
        {"项目": "页面设置", "当前状态": "业务配置只读；隐私数据支持导出与确认删除"},
    ]
    _render_table(product_rows, "产品状态暂不可用。", height=176, variant="settings")

    st.subheader("模型")
    model_rows = [
        {
            "项目": f"{row.get('能力') or '模型'} · {row.get('模型') or '未知'}",
            "当前状态": f"{row.get('配置状态') or '未知'} · {row.get('用途') or '—'}",
        }
        for row in _model_settings()
    ]
    _render_table(model_rows, "模型状态暂不可用。", height=176, variant="settings")
    st.caption("安全说明：此页面只检查凭据是否已配置，不读取到页面、不返回也不显示任何 API Key 值。")

    scope = _current_scope()
    st.subheader("存储")
    storage_rows: list[dict[str, Any]] = []
    if scope is None:
        storage_rows.append(
            {
                "项目": "会话记忆",
                "当前状态": "SQLite · 身份尚未初始化",
            }
        )
    else:
        try:
            counts = _scoped_storage_counts(_memory_db_path(), scope)
        except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
            storage_rows.append(
                {
                    "项目": "会话记忆",
                    "当前状态": "SQLite · 不可用",
                }
            )
        else:
            storage_rows.append(
                {
                    "项目": "会话记忆",
                    "当前状态": "SQLite · 可用 · " + (
                        f"{int(counts.get('sessions') or 0)} 会话 · "
                        f"{int(counts.get('runs') or 0)} 运行 · "
                        f"{int(counts.get('samples') or 0)} 样本"
                    ),
                }
            )

    literature_path = _knowledge_browse_db_path()
    if not literature_path.is_file():
        literature_path = _literature_db_path()
        _prepare_literature_database(literature_path)
    try:
        knowledge_counts = _knowledge_storage_counts(literature_path)
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
        storage_rows.append(
            {
                "项目": "本地知识库",
                "当前状态": "SQLite FTS · 不可用",
            }
        )
    else:
        storage_rows.append(
            {
                "项目": "本地知识库",
                "当前状态": "SQLite FTS · 可用 · " + (
                    f"{int(knowledge_counts.get('documents') or 0)} 文献 · "
                    f"{int(knowledge_counts.get('chunks') or 0)} 片段"
                ),
            }
        )
    _render_table(storage_rows, "存储状态暂不可用。", height=176, variant="settings")

    st.subheader("隐私与数据范围")
    if scope is None:
        privacy_rows = [
            {"项目": "身份范围", "当前状态": "尚未初始化"},
            {"项目": "数据访问", "当前状态": "未执行用户数据查询"},
            {"项目": "凭据展示", "当前状态": "始终隐藏"},
        ]
    else:
        identity_type = "匿名身份哈希" if scope.user_id.startswith("anon_") else "认证/配置身份哈希"
        privacy_rows = [
            {"项目": "身份类型", "当前状态": identity_type},
            {"项目": "用户范围", "当前状态": _short_id(scope.user_id, 10, 4)},
            {"项目": "项目范围", "当前状态": _short_id(scope.project_id, 14, 4)},
            {"项目": "数据访问", "当前状态": "按 user_id + project_id 双重隔离"},
            {"项目": "凭据展示", "当前状态": "始终隐藏"},
        ]
    _render_table(privacy_rows, "隐私状态暂不可用。", height=248, variant="settings")

    if scope is None or not scope.session_id:
        st.info("会话身份尚未初始化，暂不能导出、删除或查看访问记录。")
        return

    try:
        manager = _privacy_manager(scope)
        policy = manager.retention_policy()
        access_events = manager.list_privacy_events(
            user_id=scope.user_id,
            project_id=scope.project_id,
            limit=12,
        )
    except (agent_memory.MemoryManagerError, OSError, sqlite3.Error, ValueError) as error:
        st.warning(f"隐私控制暂不可用：{error}")
        return

    st.subheader("保存期限与访问记录")
    cleanup_status = (
        "已启用自动清理"
        if policy.get("automatic_cleanup_enabled")
        else "演示版未启用后台自动清理；可使用下方主动删除"
    )
    retention_rows = [
        {
            "项目": "匿名恢复令牌",
            "当前状态": f"{int(policy.get('resume_token_ttl_hours') or 0)} 小时后失效；服务端只保存哈希",
        },
        {
            "项目": "会话数据目标期限",
            "当前状态": f"{int(policy.get('conversation_retention_days') or 0)} 天 · {cleanup_status}",
        },
        {
            "项目": "Agent 审计目标期限",
            "当前状态": f"{int(policy.get('agent_audit_retention_days') or 0)} 天",
        },
        {
            "项目": "访问记录目标期限",
            "当前状态": f"{int(policy.get('access_log_retention_days') or 0)} 天",
        },
    ]
    _render_table(retention_rows, "保存期限配置暂不可用。", height=220, variant="settings")
    st.caption(
        "30/90/90 天是可配置的保存目标，不代表系统已经自动执行。"
        "当前演示版未实现后台批量清理；实际生效的是恢复令牌到期失效，以及用户在下方主动删除。"
    )
    st.caption(
        "地址栏中的 ctx 是最长 24 小时有效的持有式恢复凭据，可能进入浏览器历史或同源访问日志。"
        "请勿直接转发地址栏；对外分享请使用顶部“无数据链接”。"
    )

    event_rows = [
        {
            "操作": _privacy_event_label(item.get("event_type")),
            "结果": "成功" if str(item.get("outcome") or "success") == "success" else "异常",
            "会话指纹": _session_fingerprint(item.get("session_id")),
            "时间": _display_time(item.get("created_at")),
        }
        for item in access_events
    ]
    _render_table(event_rows, "当前身份还没有访问记录。", height=260, variant="settings")

    st.subheader("导出我的数据")
    st.caption(
        "导出范围严格限定为当前 user_id + project_id；JSON 包含会话、记忆、样本、审计与已知文件的逻辑引用，"
        "不含恢复令牌/哈希，也不包含图片或报告文件本体。完整 ZIP 携带包尚未实现。"
    )
    if st.button("生成我的数据导出", key="privacy_prepare_export", width="stretch"):
        try:
            exported = _prepare_privacy_export(manager, scope)
        except (agent_memory.MemoryManagerError, OSError, sqlite3.Error, ValueError) as error:
            st.error(f"生成导出失败：{error}")
        else:
            st.session_state.privacy_export_json = json.dumps(
                exported,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            st.session_state.privacy_export_filename = (
                f"citrus-agent-data-{datetime.now(BEIJING_TIMEZONE):%Y%m%d-%H%M%S}.json"
            )
    export_json = str(st.session_state.get("privacy_export_json") or "")
    if export_json:
        st.download_button(
            "下载我的数据（JSON）",
            data=export_json,
            file_name=str(
                st.session_state.get("privacy_export_filename")
                or "citrus-agent-data.json"
            ),
            mime="application/json",
            key="privacy_download_export",
            width="stretch",
        )

    st.subheader("删除数据")
    st.warning("删除操作不可恢复。系统不会因为打开设置页或查看期限而自动删除任何数据。")
    active_job_running = bool(st.session_state.get("active_agent_job_id"))
    if active_job_running:
        st.info("当前分析任务仍在运行。请等待任务完成后再删除，避免运行结果重新写入已删除的数据范围。")
    session_confirmation = st.text_input(
        "删除当前会话确认词",
        key="privacy_delete_session_confirmation",
        placeholder="请输入：删除本次会话",
    )
    if st.button(
        "删除本次会话",
        key="privacy_delete_session",
        disabled=_privacy_delete_disabled(
            session_confirmation,
            "删除本次会话",
            active_job_running=active_job_running,
        ),
        width="stretch",
    ):
        try:
            result = manager.delete_session_data(
                scope.session_id,
                user_id=scope.user_id,
                project_id=scope.project_id,
            )
        except (agent_memory.MemoryManagerError, OSError, sqlite3.Error, ValueError) as error:
            st.error(f"删除失败：{error}")
        else:
            if result.get("deleted"):
                file_cleanup_errors = int(result.get("file_cleanup_errors") or 0)
                st.session_state.privacy_deletion_notice = _privacy_deletion_notice(
                    delete_all=False,
                    file_cleanup_errors=file_cleanup_errors,
                )
                _reset_after_privacy_deletion(delete_all=False)
                st.rerun()
            else:
                st.info("当前会话已经不存在，无需重复删除。")

    with st.expander("删除我的全部数据", expanded=False):
        st.error("这会删除当前用户在本项目中的全部会话、记忆、样本、运行审计和已知上传文件。")
        all_confirmation = st.text_input(
            "删除全部数据确认词",
            key="privacy_delete_all_confirmation",
            placeholder="请输入：删除我的全部数据",
        )
        if st.button(
            "永久删除我的全部数据",
            key="privacy_delete_all",
            disabled=_privacy_delete_disabled(
                all_confirmation,
                "删除我的全部数据",
                active_job_running=active_job_running,
            ),
            width="stretch",
        ):
            try:
                result = manager.delete_user_data(
                    user_id=scope.user_id,
                    project_id=scope.project_id,
                )
            except (agent_memory.MemoryManagerError, OSError, sqlite3.Error, ValueError) as error:
                st.error(f"删除失败：{error}")
            else:
                file_cleanup_errors = int(result.get("file_cleanup_errors") or 0)
                st.session_state.privacy_deletion_notice = _privacy_deletion_notice(
                    delete_all=True,
                    file_cleanup_errors=file_cleanup_errors,
                )
                _reset_after_privacy_deletion(delete_all=True)
                st.rerun()


def _go_view(view: str) -> None:
    """Navigate inside the existing Streamlit session without discarding state."""
    st.session_state.product_view = view
    st.session_state.reset_main_scroll_position = True
    try:
        st.query_params["view"] = view
    except Exception:
        pass
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()


def _current_result() -> dict[str, Any]:
    value = st.session_state.get("last_result")
    return value if isinstance(value, dict) else {}


def _select_identity_role(role: str) -> None:
    """Persist the role selected from an identity card."""
    st.session_state.citrus_workbench_role = role


def _result_value(item: Any, key: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def render_identity_page() -> None:
    ui_components.render_page_header(
        "CITRUS AI · IDENTITY",
        "身份选择",
        "先确认组织与角色，再加载对应的数据范围、任务模板和审批权限。",
    )
    st.markdown(
        """
        <div class="identity-hero">
            <div class="identity-kicker">CITRUS AI</div>
            <h2>选择你的工作身份</h2>
            <p>不同身份对应不同的数据范围、任务入口和审批边界。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    roles = {
        "研发工作者": "实验设计、工艺开发、数据分析与报告撰写",
        "质量管理": "质量控制、检测分析、证据复核与合规审核",
        "管理决策者": "项目进度、资源配置、路线确认与最终审批",
    }
    selected = st.session_state.get("citrus_workbench_role") or next(iter(roles))
    with st.container(key="identity_role_picker"):
        st.markdown('<div class="identity-role-label">工作身份</div>', unsafe_allow_html=True)
        role_columns = st.columns(3, gap="small")
        for index, (role, description) in enumerate(roles.items(), 1):
            with role_columns[index - 1]:
                state = "selected" if selected == role else "idle"
                with st.container(key=f"identity_role_card_{index}_{state}"):
                    st.markdown(
                        f'<article class="identity-card{" is-selected" if selected == role else ""}">'
                        f'<span class="identity-card-number">{index:02d}</span>'
                        f'<h3>{html.escape(role)}</h3>'
                        f'<p>{html.escape(description)}</p></article>',
                        unsafe_allow_html=True,
                    )
                    st.button(
                        f"选择{role}",
                        key=f"identity_role_button_{index}",
                        width="stretch",
                        type="secondary",
                        on_click=_select_identity_role,
                        args=(role,),
                    )
    with st.container(key="identity_quick_task"):
        st.markdown('<h3 class="section-title">快速创建任务</h3>', unsafe_allow_html=True)
        task_col, project_col = st.columns([1.4, 1])
        task_name = task_col.text_input(
            "任务名称", placeholder="例如：沃柑 NFC 果汁工艺优化"
        )
        project_col.text_input("所属项目", placeholder="选择项目（可选）")
        if st.button(
            "创建任务并进入资料确认",
            type="primary",
            disabled=not task_name.strip(),
        ):
            st.session_state.workbench_task_name = task_name.strip()
            _go_view("intake")


def _render_industry_task_page(
    view: str, industry_view: str, title: str, subtitle: str
) -> None:
    ui_components.render_page_header(f"TASK · {view.upper()}", title, subtitle)
    ui_components.render_process_stepper(view)
    st.session_state.industry_workspace_view = industry_view
    try:
        st.query_params["industry"] = industry_view
    except Exception:
        pass
    ui_industry_pages.render_industry_workspace()


def render_intake_page() -> None:
    _render_industry_task_page(
        "intake",
        "data",
        "资料确认",
        "在任务内录入、复用和补充批次数据，确认后进入证据分析。",
    )


def render_evidence_page() -> None:
    ui_components.render_page_header(
        "TASK · ANALYSIS",
        "分析与证据",
        "拆解证据等级、规则命中和风险缺口，确保判断可回查。",
    )
    ui_components.render_process_stepper("evidence")
    result = _current_result()
    evidence = list(result.get("evidence") or [])
    scores = list(result.get("scores") or [])
    risks = list(result.get("quality_risks") or [])
    direct = sum(
        "直接"
        in str(_result_value(item, "grade", _result_value(item, "evidence_grade", "")))
        for item in evidence
    )
    ui_components.render_metric_cards([
        ("证据条目", len(evidence), ""),
        ("直接证据", direct, ""),
        ("候选路线", len(scores), ""),
        ("风险提示", len(risks), ""),
    ])
    if not result:
        ui_components.render_empty_state(
            "尚未形成分析结果",
            "先在资料确认页补齐批次信息，或从 Agent 对话发起一次完整分析。",
            icon="search",
        )
        if st.button("打开 Agent 发起分析", type="primary"):
            _go_view("chat")
        return
    score_rows = [
        {
            "候选路线": _result_value(item, "direction", "未命名路线"),
            "匹配等级": _result_value(item, "match_level", "待评估"),
            "证据支持": _result_value(item, "evidence_support", "未评估"),
            "数据置信度": _result_value(item, "data_confidence", "待评估"),
        }
        for item in scores[:8]
    ]
    st.subheader("路线证据分布")
    _render_table(score_rows, "当前结果没有可展示的路线评分。", height=320)
    if risks:
        st.subheader("风险提示")
        st.markdown(
            '<div class="risk-list">'
            + "".join(
                f'<div>{ui_components.status_badge("待复核", "warning")}'
                f'<span>{html.escape(str(risk))}</span></div>'
                for risk in risks[:6]
            )
            + "</div>",
            unsafe_allow_html=True,
        )


def render_decision_page() -> None:
    ui_components.render_page_header(
        "TASK · DECISION",
        "路线决策",
        "并列比较候选路线，确认前可补充约束并重新评估。",
    )
    ui_components.render_process_stepper("decision")
    scores = list(_current_result().get("scores") or [])
    if not scores:
        ui_components.render_empty_state(
            "暂无可确认路线",
            "完成一次带批次信息的分析后，候选路线会按真实评分显示。",
            icon="decision",
        )
        return
    cards = []
    for index, item in enumerate(scores[:4]):
        title = str(_result_value(item, "direction", "未命名路线"))
        level = str(_result_value(item, "match_level", "待评估"))
        evidence = str(_result_value(item, "evidence_support", "未评估"))
        confidence = str(_result_value(item, "data_confidence", "待评估"))
        cards.append(
            f'<article class="route-card{" is-recommended" if index == 0 else ""}">'
            f'<header><span>{"推荐方案" if index == 0 else "候选方案"}</span>'
            f'<h3>{html.escape(title)}</h3></header><dl>'
            f'<div><dt>匹配等级</dt><dd>{html.escape(level)}</dd></div>'
            f'<div><dt>证据支持</dt><dd>{html.escape(evidence)}</dd></div>'
            f'<div><dt>数据置信度</dt><dd>{html.escape(confidence)}</dd></div>'
            "</dl></article>"
        )
    st.markdown(
        '<div class="route-card-list">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "路线排序沿用当前 Agent 结果；正式采用前仍需核对企业能力、检测结论、设备状态和小试结果。"
    )


def render_process_page() -> None:
    ui_components.render_page_header(
        "TASK · PROCESS",
        "工艺方案",
        "将确认路线转成可编辑、可追溯、可审核的端到端工艺草案。",
    )
    ui_components.render_process_stepper("process")
    plan = _current_result().get("processing_plan") or {}
    stages = list(plan.get("stages") or []) if isinstance(plan, dict) else []
    if not stages:
        ui_components.render_empty_state(
            "尚未生成工艺方案",
            "确认路线后，系统会展示工序、参数来源、设备、状态和风险边界。",
            icon="factory",
        )
        return
    rows = []
    for index, stage in enumerate(stages, 1):
        steps = stage.get("steps") if isinstance(stage, dict) else []
        rows.append(
            {
                "序号": f"{index:02d}",
                "工艺阶段": _result_value(stage, "name", "未命名阶段"),
                "工序": " → ".join(steps or []),
                "操作与参数": _result_value(stage, "operation", "待补充"),
                "质控与风险": _result_value(stage, "control", "待复核"),
                "状态": "待确认",
            }
        )
    _render_table(rows, "当前方案没有可展示的工序。", height=520)


def render_matching_page() -> None:
    ui_components.render_page_header(
        "TASK · MATCHING",
        "供需匹配",
        "按硬条件过滤，再基于真实业务字段解释综合适配度。",
    )
    st.session_state.industry_workspace_view = "market"
    try:
        st.query_params["industry"] = "market"
    except Exception:
        pass
    ui_industry_pages.render_industry_workspace()


def render_report_page() -> None:
    _render_industry_task_page(
        "report",
        "reports",
        "报告撰写",
        "把任务资料、证据、决策和工艺自动组装成可复核的报告初稿。",
    )


def render_assets_page() -> None:
    _render_industry_task_page(
        "assets", "data", "数据清洗", "统一检查缺失项、异常值和批次资料，形成可复核的数据底稿。"
    )


def render_analytics_page() -> None:
    _render_industry_task_page(
        "analytics", "visuals", "数据看板", "查看供应、产量、质量和区域流向等任务指标。"
    )


def render_review_page() -> None:
    ui_components.render_page_header(
        "TASK · REVIEW",
        "审核发布",
        "自动检查负责定位问题，最终确认、签署与发布由授权人员完成。",
    )
    ui_components.render_process_stepper("review")
    result = _current_result()
    evidence = list(result.get("evidence") or [])
    risks = list(result.get("quality_risks") or [])
    plan = result.get("processing_plan") if isinstance(result.get("processing_plan"), dict) else {}
    report_ready = bool(str(result.get("report") or "").strip())
    checks = [
        ("数据字段完整性", bool(result.get("batch")), "已通过" if result.get("batch") else "待补充"),
        ("证据引用与定位", bool(evidence), "已通过" if evidence else "待补充"),
        ("风险边界表达", bool(risks), "已检查" if risks else "待人工确认"),
        ("工艺方案结构", bool(plan.get("stages")), "已通过" if plan.get("stages") else "待生成"),
        ("报告初稿", report_ready, "已生成" if report_ready else "待生成"),
    ]
    rows = [
        {
            "审核项目": name,
            "状态": status,
            "责任边界": "自动检查" if passed else "需要人工处理",
        }
        for name, passed, status in checks
    ]
    ui_components.render_metric_cards([
        ("自动检查", f"{sum(passed for _name, passed, _status in checks)} / {len(checks)}", ""),
        ("人工确认", sum(not passed for _name, passed, _status in checks), ""),
        ("风险条目", len(risks), ""),
        ("发布状态", "待审核", ""),
    ])
    _render_table(rows, "当前没有审核项目。", height=330, variant="settings")
    st.info(
        "系统不会自动对外发布、签署或形成生产放行结论。请由具备权限的人员复核并完成最终操作。"
    )


_PAGE_RENDERERS = {
    "identity": render_identity_page,
    "intake": render_intake_page,
    "evidence": render_evidence_page,
    "decision": render_decision_page,
    "process": render_process_page,
    "matching": render_matching_page,
    "report": render_report_page,
    "assets": render_assets_page,
    "analytics": render_analytics_page,
    "review": render_review_page,
    "knowledge": render_knowledge_page,
    "知识库": render_knowledge_page,
    "settings": render_settings_page,
    "设置": render_settings_page,
}


def render_product_page(view: str) -> bool:
    """Render a product page and return whether ``view`` was recognized.

    The function accepts both stable English route keys and their Chinese labels.
    Chat remains owned by the existing main application and therefore is not
    intercepted here.
    """
    normalized = ui_components.normalize_product_view(view)
    renderer = _PAGE_RENDERERS.get(normalized)
    if renderer is None:
        return False
    renderer()
    return True


__all__ = [
    "current_industry_view",
    "render_knowledge_page",
    "render_product_page",
    "render_settings_page",
    "render_workspace_page",
]
