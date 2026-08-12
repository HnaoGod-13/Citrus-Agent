"""Read-only product pages used by the Citrus AI Streamlit application.

The module intentionally contains no Agent mutations. Workspace and analytics
queries are always scoped by both ``memory_user_id`` and ``memory_project_id``;
if either identity is unavailable, those pages render a safe empty state rather
than falling back to an unscoped query. On cloud deployments the immutable,
packaged literature index may be materialized into its runtime cache before the
Knowledge page opens it in read-only mode.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import html
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_DB_PATH = PROJECT_ROOT / "data" / "memory" / "memory.db"
DEFAULT_LITERATURE_DB_PATH = PROJECT_ROOT / "data" / "literature" / "literature.db"

WORKSPACE_LIMIT = 16
KNOWLEDGE_LIMIT = 200
ANALYTICS_RECENT_LIMIT = 24
ANALYTICS_DAY_LIMIT = 30
CHART_COLOR = "#737373"


@dataclass(frozen=True)
class _Scope:
    user_id: str
    project_id: str


def _current_scope() -> _Scope | None:
    """Return the initialized memory scope without inventing a fallback user."""
    try:
        user_id = str(st.session_state.get("memory_user_id") or "").strip()
        project_id = str(st.session_state.get("memory_project_id") or "").strip()
    except Exception:
        return None
    if not user_id or not project_id:
        return None
    return _Scope(user_id=user_id, project_id=project_id)


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
        return [str(value)]
    return decoded if isinstance(decoded, list) else []


def _compact_text(value: Any, limit: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text or "—"
    return text[: max(limit - 1, 1)].rstrip() + "…"


def _display_time(value: Any) -> str:
    text = str(value or "").strip().replace("T", " ")
    return text[:16] if len(text) >= 16 else (text or "—")


def _short_id(value: Any, left: int = 8, right: int = 4) -> str:
    text = str(value or "").strip()
    if len(text) <= left + right + 1:
        return text or "—"
    return f"{text[:left]}…{text[-right:]}"


def _source_name(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1] if text else "—"


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


def _render_table(rows: list[dict[str, Any]], empty_message: str, *, height: int = 360) -> None:
    if not rows:
        st.info(empty_message)
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=height)


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
                ),
            ).fetchone()
        )

        sessions = _row_dicts(
            connection.execute(
                """
                WITH scoped_messages AS (
                    SELECT id, session_id, content, created_at
                    FROM conversation_messages
                    WHERE user_id = ? AND project_id = ?
                      AND role IN ('user', 'assistant')
                ),
                message_summary AS (
                    SELECT session_id, COUNT(*) AS message_count,
                           MAX(id) AS last_message_id,
                           MAX(created_at) AS last_message_at
                    FROM scoped_messages
                    GROUP BY session_id
                ),
                last_messages AS (
                    SELECT message_summary.session_id, scoped_messages.content
                    FROM message_summary
                    JOIN scoped_messages
                      ON scoped_messages.id = message_summary.last_message_id
                ),
                scoped_runs AS (
                    SELECT session_id, created_at
                    FROM agent_runs
                    WHERE user_id = ? AND project_id = ?
                ),
                run_summary AS (
                    SELECT session_id, COUNT(*) AS run_count,
                           MAX(created_at) AS last_run_at
                    FROM scoped_runs
                    GROUP BY session_id
                )
                SELECT s.session_id, s.status, s.created_at, s.updated_at,
                       COALESCE(message_summary.message_count, 0) AS message_count,
                       COALESCE(run_summary.run_count, 0) AS run_count,
                       last_messages.content AS last_message,
                       MAX(
                           COALESCE(s.updated_at, ''),
                           COALESCE(message_summary.last_message_at, ''),
                           COALESCE(run_summary.last_run_at, '')
                       ) AS activity_at
                FROM sessions s
                LEFT JOIN message_summary ON message_summary.session_id = s.session_id
                LEFT JOIN last_messages ON last_messages.session_id = s.session_id
                LEFT JOIN run_summary ON run_summary.session_id = s.session_id
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
                SELECT run_id, session_id, original_input, model_name,
                       tool_calls_json, error, created_at
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
                       outcome, confidence, status, updated_at
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
    _render_page_header(
        "CITRUS AI · WORKSPACE",
        "工作台",
        "查看当前账户最近的会话、分析运行与批次样本。",
        "Recent conversations, analysis runs and saved batch records",
    )
    scope = _current_scope()
    if scope is None:
        _render_scope_empty()
        return

    try:
        data = _load_workspace(_memory_db_path(), scope)
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
        _render_data_unavailable("工作台数据")
        return

    counts = data["counts"]
    metric_columns = st.columns(4)
    metric_columns[0].metric("有内容会话", int(counts.get("sessions") or 0))
    metric_columns[1].metric("对话消息", int(counts.get("messages") or 0))
    metric_columns[2].metric("分析运行", int(counts.get("runs") or 0))
    metric_columns[3].metric("批次样本", int(counts.get("samples") or 0))

    sessions_tab, runs_tab, samples_tab = st.tabs(["最近会话", "分析运行", "批次样本"])
    with sessions_tab:
        session_rows = [
            {
                "会话": _short_id(row.get("session_id")),
                "状态": "活跃" if row.get("status") == "active" else _compact_text(row.get("status"), 24),
                "消息": int(row.get("message_count") or 0),
                "分析": int(row.get("run_count") or 0),
                "最近内容": _compact_text(row.get("last_message"), 88),
                "更新时间": _display_time(row.get("activity_at") or row.get("updated_at")),
            }
            for row in data["sessions"]
        ]
        _render_table(session_rows, "当前账户还没有有内容的会话。")

    with runs_tab:
        run_rows = []
        for row in data["runs"]:
            tool_count = len(_json_list(row.get("tool_calls_json")))
            run_rows.append(
                {
                    "运行": _short_id(row.get("run_id")),
                    "任务": _compact_text(row.get("original_input"), 92),
                    "模型": _compact_text(row.get("model_name"), 36),
                    "工具调用": tool_count,
                    "结果": "异常" if str(row.get("error") or "").strip() else "完成",
                    "时间": _display_time(row.get("created_at")),
                }
            )
        _render_table(run_rows, "当前账户还没有分析运行记录。")

    with samples_tab:
        sample_rows = [
            {
                "样本": _short_id(row.get("sample_id")),
                "品种": _compact_text(row.get("variety"), 28),
                "产地": _compact_text(row.get("origin"), 28),
                "加工目标": _compact_text(row.get("processing_goal"), 82),
                "可信度": (
                    f"{float(row['confidence']) * 100:.0f}%"
                    if row.get("confidence") is not None
                    else "—"
                ),
                "更新时间": _display_time(row.get("updated_at")),
            }
            for row in data["samples"]
        ]
        _render_table(sample_rows, "当前账户还没有保存的批次样本。")


def _load_knowledge_facets(path: Path) -> dict[str, Any]:
    with _readonly_database(path) as connection:
        stats = dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM documents) AS documents,
                    (SELECT COUNT(*) FROM chunks) AS chunks
                """
            ).fetchone()
        )
        category_rows = _row_dicts(connection.execute("SELECT categories FROM documents"))

    category_counts: Counter[str] = Counter()
    for row in category_rows:
        for item in _json_list(row.get("categories")):
            category = str(item or "").strip()
            if category:
                category_counts[category] += 1
    return {"stats": stats, "categories": category_counts}


def _load_knowledge_documents(
    path: Path,
    *,
    search: str = "",
    category: str = "",
    limit: int = KNOWLEDGE_LIMIT,
) -> dict[str, Any]:
    clean_search = " ".join(search.split())
    search_pattern = f"%{clean_search}%"
    category_pattern = f"%{category}%"
    parameters = (
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
        total = int(
            connection.execute(
                """
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
                """,
                parameters,
            ).fetchone()[0]
        )
        rows = _row_dicts(
            connection.execute(
                """
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
                ORDER BY
                    CASE
                        WHEN TRIM(COALESCE(d.year, '')) GLOB '[0-9][0-9][0-9][0-9]'
                        THEN CAST(d.year AS INTEGER)
                        ELSE 0
                    END DESC,
                    d.title COLLATE NOCASE
                LIMIT ?
                """,
                (*parameters, max(1, min(int(limit), KNOWLEDGE_LIMIT))),
            )
        )
    return {"total": total, "rows": rows}


def _list_text(value: Any, *, limit: int = 4) -> str:
    items = [str(item).strip() for item in _json_list(value) if str(item).strip()]
    if not items:
        return "—"
    shown = items[:limit]
    return "、".join(shown) + ("…" if len(items) > limit else "")


def render_knowledge_page() -> None:
    _render_page_header(
        "CITRUS AI · KNOWLEDGE",
        "知识库",
        "检索已入库文献及其来源、年份与分类。",
        "Search indexed literature, sources, years and categories",
    )
    path = _literature_db_path()
    if not path.is_file():
        with st.spinner("正在准备文献索引…"):
            _prepare_literature_database(path)
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
    try:
        listing = _load_knowledge_documents(path, search=search, category=category)
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
        _render_data_unavailable("知识库检索")
        return

    stats = facets["stats"]
    metric_columns = st.columns(3)
    metric_columns[0].metric("文献", int(stats.get("documents") or 0))
    metric_columns[1].metric("证据片段", int(stats.get("chunks") or 0))
    metric_columns[2].metric("分类", len(categories))

    total = int(listing["total"])
    st.caption(
        f"找到 {total} 条文献"
        + (f"，当前显示前 {KNOWLEDGE_LIMIT} 条" if total > KNOWLEDGE_LIMIT else "")
    )
    quality_labels = {"good": "已索引", "fair": "可用", "poor": "待复核"}
    rows = [
        {
            "题名": _compact_text(row.get("title"), 112),
            "作者": _compact_text(_list_text(row.get("authors")), 58),
            "年份": str(row.get("year") or "—"),
            "分类": _compact_text(_list_text(row.get("categories")), 42),
            "来源": _compact_text(row.get("publication") or _source_name(row.get("source_file")), 58),
            "片段": int(row.get("chunk_count") or 0),
            "状态": quality_labels.get(str(row.get("text_quality") or "").lower(), "已入库"),
        }
        for row in listing["rows"]
    ]
    _render_table(rows, "没有符合当前搜索和分类条件的文献。", height=520)


def _load_analytics(path: Path, scope: _Scope) -> dict[str, Any]:
    with _readonly_database(path) as connection:
        counts = dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM sessions
                     WHERE user_id = ? AND project_id = ?) AS sessions,
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
                ),
            ).fetchone()
        )

        daily = _row_dicts(
            connection.execute(
                """
                SELECT SUBSTR(created_at, 1, 10) AS day,
                       COUNT(*) AS runs,
                       SUM(CASE WHEN TRIM(COALESCE(error, '')) = '' THEN 1 ELSE 0 END)
                           AS successful_runs,
                       SUM(CASE WHEN TRIM(COALESCE(error, '')) <> '' THEN 1 ELSE 0 END)
                           AS failed_runs
                FROM agent_runs
                WHERE user_id = ? AND project_id = ?
                  AND TRIM(COALESCE(created_at, '')) <> ''
                GROUP BY SUBSTR(created_at, 1, 10)
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


def _render_native_bar_chart(frame: pd.DataFrame) -> None:
    try:
        st.bar_chart(frame, color=CHART_COLOR, height=260)
    except TypeError:
        # Compatibility with older supported Streamlit versions.
        st.bar_chart(frame, height=260)


def render_analytics_page() -> None:
    _render_page_header(
        "CITRUS AI · ANALYTICS",
        "分析",
        "基于当前账户实际运行记录汇总使用情况与执行状态。",
        "Usage and execution status derived from your recorded runs",
    )
    scope = _current_scope()
    if scope is None:
        _render_scope_empty()
        return

    try:
        data = _load_analytics(_memory_db_path(), scope)
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
        _render_data_unavailable("分析数据")
        return

    counts = data["counts"]
    total_runs = int(counts.get("runs") or 0)
    successful_runs = int(counts.get("successful_runs") or 0)
    success_rate = f"{successful_runs / total_runs * 100:.0f}%" if total_runs else "—"

    metric_columns = st.columns(4)
    metric_columns[0].metric("会话", int(counts.get("sessions") or 0))
    metric_columns[1].metric("分析运行", total_runs)
    metric_columns[2].metric("运行完成率", success_rate)
    metric_columns[3].metric("批次样本", int(counts.get("samples") or 0))

    st.subheader("运行趋势")
    if data["daily"]:
        daily_frame = pd.DataFrame(
            [
                {
                    "日期": row.get("day") or "未知",
                    "运行次数": int(row.get("runs") or 0),
                }
                for row in data["daily"]
            ]
        ).set_index("日期")
        _render_native_bar_chart(daily_frame)
    else:
        st.info("当前账户还没有可绘制的分析运行记录。")

    st.subheader("模型使用")
    model_rows = [
        {
            "模型": _compact_text(row.get("model_name"), 52),
            "运行": int(row.get("runs") or 0),
            "完成": int(row.get("runs") or 0) - int(row.get("failed_runs") or 0),
            "异常": int(row.get("failed_runs") or 0),
        }
        for row in data["models"]
    ]
    _render_table(model_rows, "当前账户还没有模型运行记录。", height=240)

    st.subheader("最近运行")
    recent_rows = [
        {
            "运行": _short_id(row.get("run_id")),
            "任务": _compact_text(row.get("original_input"), 92),
            "模型": _compact_text(row.get("model_name"), 38),
            "工具": len(_json_list(row.get("tool_calls_json"))),
            "文献": len(_json_list(row.get("retrieved_literature_ids_json"))),
            "结果": "异常" if str(row.get("error") or "").strip() else "完成",
            "时间": _display_time(row.get("created_at")),
        }
        for row in data["recent_runs"]
    ]
    _render_table(recent_rows, "当前账户还没有分析运行记录。")


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
                    (SELECT COUNT(*) FROM sessions
                     WHERE user_id = ? AND project_id = ?) AS sessions,
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
                ),
            ).fetchone()
        )


def _knowledge_storage_counts(path: Path) -> dict[str, int]:
    with _readonly_database(path) as connection:
        return dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM documents) AS documents,
                    (SELECT COUNT(*) FROM chunks) AS chunks
                """
            ).fetchone()
        )


def render_settings_page() -> None:
    _render_page_header(
        "CITRUS AI · SETTINGS",
        "设置",
        "只读查看产品、模型、存储与隐私状态。",
        "Read-only product, model, storage and privacy status",
    )

    st.subheader("产品")
    product_rows = [
        {"项目": "产品", "当前状态": "Citrus AI · Decision Lab"},
        {"项目": "前端运行时", "当前状态": f"Streamlit {getattr(st, '__version__', '未知')}"},
        {"项目": "页面设置", "当前状态": "只读；不提供未接入业务的保存操作"},
    ]
    _render_table(product_rows, "产品状态暂不可用。", height=176)

    st.subheader("模型")
    _render_table(_model_settings(), "模型状态暂不可用。", height=176)
    st.caption("安全说明：此页面只检查凭据是否已配置，不读取到页面、不返回也不显示任何 API Key 值。")

    scope = _current_scope()
    st.subheader("存储")
    storage_rows: list[dict[str, Any]] = []
    if scope is None:
        storage_rows.append(
            {
                "存储": "会话记忆",
                "类型": "SQLite",
                "状态": "身份尚未初始化",
                "当前范围数据": "—",
            }
        )
    else:
        try:
            counts = _scoped_storage_counts(_memory_db_path(), scope)
        except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
            storage_rows.append(
                {
                    "存储": "会话记忆",
                    "类型": "SQLite",
                    "状态": "不可用",
                    "当前范围数据": "—",
                }
            )
        else:
            storage_rows.append(
                {
                    "存储": "会话记忆",
                    "类型": "SQLite",
                    "状态": "可用",
                    "当前范围数据": (
                        f"{int(counts.get('sessions') or 0)} 会话 · "
                        f"{int(counts.get('runs') or 0)} 运行 · "
                        f"{int(counts.get('samples') or 0)} 样本"
                    ),
                }
            )

    try:
        knowledge_counts = _knowledge_storage_counts(_literature_db_path())
    except (FileNotFoundError, OSError, sqlite3.Error, ValueError):
        storage_rows.append(
            {
                "存储": "本地知识库",
                "类型": "SQLite FTS",
                "状态": "不可用",
                "当前范围数据": "—",
            }
        )
    else:
        storage_rows.append(
            {
                "存储": "本地知识库",
                "类型": "SQLite FTS",
                "状态": "可用",
                "当前范围数据": (
                    f"{int(knowledge_counts.get('documents') or 0)} 文献 · "
                    f"{int(knowledge_counts.get('chunks') or 0)} 片段"
                ),
            }
        )
    _render_table(storage_rows, "存储状态暂不可用。", height=176)

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
    _render_table(privacy_rows, "隐私状态暂不可用。", height=248)


_PAGE_RENDERERS = {
    "workspace": render_workspace_page,
    "工作台": render_workspace_page,
    "knowledge": render_knowledge_page,
    "知识库": render_knowledge_page,
    "analytics": render_analytics_page,
    "分析": render_analytics_page,
    "settings": render_settings_page,
    "设置": render_settings_page,
}


def render_product_page(view: str) -> bool:
    """Render a product page and return whether ``view`` was recognized.

    The function accepts both stable English route keys and their Chinese labels.
    Chat remains owned by the existing main application and therefore is not
    intercepted here.
    """
    normalized = str(view or "").strip().lower().replace("-", "_").replace(" ", "_")
    renderer = _PAGE_RENDERERS.get(normalized)
    if renderer is None:
        return False
    renderer()
    return True


__all__ = [
    "render_analytics_page",
    "render_knowledge_page",
    "render_product_page",
    "render_settings_page",
    "render_workspace_page",
]
