from __future__ import annotations

import json
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from streamlit.testing.v1 import AppTest

from app import knowledge_catalog as catalog_index
from app.ui import product_pages


MEMORY_SCHEMA = """
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE agent_runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    original_input TEXT NOT NULL,
    model_name TEXT,
    tool_calls_json TEXT NOT NULL DEFAULT '[]',
    retrieved_literature_ids_json TEXT NOT NULL DEFAULT '[]',
    final_output TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE citrus_samples (
    sample_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    variety TEXT,
    origin TEXT,
    disease_or_quality TEXT,
    processing_goal TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    solution TEXT,
    outcome TEXT,
    confidence REAL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE memories (
    memory_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


LITERATURE_SCHEMA = """
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    year TEXT,
    categories TEXT,
    publication TEXT,
    doi TEXT,
    source_file TEXT,
    chunk_count INTEGER,
    text_quality TEXT
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL,
    category TEXT,
    chunk_text TEXT
);
"""


class ProductPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.memory_db = root / "memory.db"
        self.literature_db = root / "literature.db"
        self._build_memory_fixture()
        self._build_literature_fixture()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _build_memory_fixture(self) -> None:
        connection = sqlite3.connect(self.memory_db)
        try:
            connection.executescript(MEMORY_SCHEMA)
            scopes = [
                ("user_alpha", "project_one", "alpha"),
                ("user_beta", "project_one", "beta"),
                ("user_alpha", "project_two", "other_project"),
            ]
            for index, (user_id, project_id, suffix) in enumerate(scopes, 1):
                session_id = f"session_{suffix}"
                timestamp = f"2026-08-{index:02d}T10:00:00+00:00"
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, user_id, project_id, "active", timestamp, timestamp),
                )
                connection.execute(
                    """
                    INSERT INTO conversation_messages(
                        message_id, user_id, session_id, project_id,
                        role, content, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"message_{suffix}",
                        user_id,
                        session_id,
                        project_id,
                        "user",
                        (
                            "分析广西沃柑的加工方向，请完整运行Agent工作流程："
                            "检索文献、评估路线和质控风险。"
                            if suffix == "alpha"
                            else f"private message for {suffix}"
                        ),
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO conversation_messages(
                        message_id, user_id, session_id, project_id,
                        role, content, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"answer_{suffix}",
                        user_id,
                        session_id,
                        project_id,
                        "assistant",
                        (
                            "### 综合结论\n\n"
                            "当前优先方向是 **果肉-柑橘汁/NFC**。"
                            if suffix == "alpha"
                            else f"private answer for {suffix}"
                        ),
                        timestamp,
                    ),
                )
                tool_calls = [
                    {
                        "tool": "Evidence-aware Route Ranker",
                        "status": "完成",
                        "result_summary": (
                            "当前优先方向是 果肉-柑橘汁/NFC（条件性备选）。"
                            if suffix == "alpha"
                            else f"private route for {suffix}"
                        ),
                    },
                    {
                        "tool": "Quality Gate",
                        "status": "完成",
                        "result_summary": "发现 2 个需复核风险项。",
                    },
                ]
                connection.execute(
                    """
                    INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"run_{suffix}",
                        user_id,
                        session_id,
                        project_id,
                        (
                            "分析广西沃柑的加工方向，请完整运行Agent工作流程："
                            "检索文献、评估路线和质控风险。"
                            if suffix == "alpha"
                            else f"private task for {suffix}"
                        ),
                        "fixture-model",
                        json.dumps(tool_calls, ensure_ascii=False),
                        f'["literature_{suffix}"]',
                        (
                            "### 综合结论\n\n"
                            "当前优先方向是 **果肉-柑橘汁/NFC**。"
                            if suffix == "alpha"
                            else f"private result for {suffix}"
                        ),
                        "",
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO citrus_samples VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        f"sample_{suffix}",
                        session_id,
                        user_id,
                        project_id,
                        "沃柑" if suffix == "alpha" else f"variety_{suffix}",
                        "广西" if suffix == "alpha" else f"origin_{suffix}",
                        (
                            "缺少微生物检测，不能输出最终放行结论。"
                            if suffix == "alpha"
                            else f"private quality for {suffix}"
                        ),
                        f"goal_{suffix}",
                        json.dumps(
                            {
                                "weight_kg": 1500,
                                "brix": 13.0,
                                "acidity": 0.6,
                                "microbe_status": "missing",
                            },
                            ensure_ascii=False,
                        ),
                        (
                            "果肉-柑橘汁/NFC；待小试和企业 SOP 复核。"
                            if suffix == "alpha"
                            else f"private solution for {suffix}"
                        ),
                        f"outcome_{suffix}",
                        0.75,
                        "active",
                        timestamp,
                    ),
                )
                connection.execute(
                    "INSERT INTO memories VALUES (?, ?, ?, ?)",
                    (f"memory_{suffix}", user_id, project_id, "active"),
                )
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "session_alpha_empty",
                    "user_alpha",
                    "project_one",
                    "active",
                    "2026-08-09T10:00:00+00:00",
                    "2026-08-09T10:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _build_literature_fixture(self) -> None:
        connection = sqlite3.connect(self.literature_db)
        try:
            connection.executescript(LITERATURE_SCHEMA)
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "doc_juice",
                    "Citrus juice processing",
                    '["Researcher A"]',
                    "2025",
                    '["橙汁"]',
                    "Journal A",
                    "10.1000/juice",
                    "橙汁/citrus-juice.pdf",
                    2,
                    "good",
                ),
            )
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "doc_peel",
                    "Citrus peel utilization",
                    '["Researcher B"]',
                    "2024",
                    '["副产物", "果胶"]',
                    "Journal B",
                    "10.1000/peel",
                    "副产物/citrus-peel.pdf",
                    1,
                    "good",
                ),
            )
            connection.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                [
                    (1, "doc_juice", "橙汁", "juice evidence one"),
                    (2, "doc_juice", "橙汁", "juice evidence two"),
                    (3, "doc_peel", "果胶", "peel evidence"),
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def _render_page(self, view: str) -> AppTest:
        source = f"""
from pathlib import Path
import streamlit as st
from unittest.mock import patch
from app.ui import product_pages

with (
    patch.object(product_pages, "_memory_db_path", return_value=Path({str(self.memory_db)!r})),
    patch.object(product_pages, "_literature_db_path", return_value=Path({str(self.literature_db)!r})),
    patch.object(product_pages, "_knowledge_browse_db_path", return_value=Path({str(self.literature_db)!r})),
):
    st.session_state.memory_user_id = "user_alpha"
    st.session_state.memory_project_id = "project_one"
    assert product_pages.render_product_page({view!r}) is True
"""
        return AppTest.from_string(source, default_timeout=30).run()

    def test_product_page_dispatch_renders_every_supported_view(self) -> None:
        for view in ("workspace", "knowledge", "analytics", "settings"):
            with self.subTest(view=view):
                app = self._render_page(view)
                self.assertEqual([], list(app.exception))

    def test_product_page_dispatch_leaves_chat_and_unknown_views_unhandled(self) -> None:
        self.assertFalse(product_pages.render_product_page("chat"))
        self.assertFalse(product_pages.render_product_page("unknown"))

    def test_privacy_delete_requires_exact_phrase_and_blocks_active_jobs(self) -> None:
        self.assertTrue(
            product_pages._privacy_delete_disabled(
                "",
                "删除本次会话",
                active_job_running=False,
            )
        )
        self.assertTrue(
            product_pages._privacy_delete_disabled(
                "删除会话",
                "删除本次会话",
                active_job_running=False,
            )
        )
        self.assertFalse(
            product_pages._privacy_delete_disabled(
                " 删除本次会话 ",
                "删除本次会话",
                active_job_running=False,
            )
        )
        self.assertTrue(
            product_pages._privacy_delete_disabled(
                "删除本次会话",
                "删除本次会话",
                active_job_running=True,
            )
        )

    def test_privacy_export_logs_accurate_success_and_failure_outcomes(self) -> None:
        scope = product_pages._Scope("user_alpha", "project_one", "session_alpha")
        success_manager = Mock()
        success_manager.export_user_data.return_value = {"data": {"sessions": []}}

        exported = product_pages._prepare_privacy_export(success_manager, scope)

        self.assertEqual({"data": {"sessions": []}}, exported)
        self.assertEqual(
            [
                call.export_user_data(user_id="user_alpha", project_id="project_one"),
                call.log_privacy_event(
                    "data_exported",
                    user_id="user_alpha",
                    project_id="project_one",
                    session_id="session_alpha",
                    details={"format": "json", "action": "prepared"},
                ),
            ],
            success_manager.mock_calls,
        )

        failed_manager = Mock()
        failed_manager.export_user_data.side_effect = product_pages.agent_memory.MemoryStorageError(
            "temporary export failure"
        )
        with self.assertRaises(product_pages.agent_memory.MemoryStorageError):
            product_pages._prepare_privacy_export(failed_manager, scope)
        failed_manager.log_privacy_event.assert_called_once_with(
            "data_exported",
            user_id="user_alpha",
            project_id="project_one",
            session_id="session_alpha",
            outcome="failed",
            details={"format": "json"},
        )

    def test_privacy_deletion_notice_reports_file_cleanup_failures(self) -> None:
        success = product_pages._privacy_deletion_notice(
            delete_all=False,
            file_cleanup_errors=0,
        )
        warning = product_pages._privacy_deletion_notice(
            delete_all=True,
            file_cleanup_errors=2,
        )
        self.assertEqual("success", success["level"])
        self.assertIn("新的隔离会话", success["message"])
        self.assertEqual("warning", warning["level"])
        self.assertIn("2 个已知文件清理失败", warning["message"])

    def test_privacy_reset_keeps_one_time_notice_but_clears_credentials(self) -> None:
        notice = {"level": "success", "message": "deleted"}
        state = {
            "memory_user_id": "user_alpha",
            "memory_project_id": "project_one",
            "memory_session_id": "session_alpha",
            "memory_context_token": "ctx_secret",
            "active_agent_job_id": "job_active",
            "privacy_deletion_notice": notice,
        }
        query = {"ctx": "ctx_secret", "uid": "legacy", "sid": "legacy", "view": "settings"}
        with (
            patch.object(product_pages.st, "session_state", state),
            patch.object(product_pages.st, "query_params", query),
        ):
            product_pages._reset_after_privacy_deletion(delete_all=True)

        self.assertEqual(notice, state["privacy_deletion_notice"])
        self.assertNotIn("memory_user_id", state)
        self.assertNotIn("memory_project_id", state)
        self.assertNotIn("memory_session_id", state)
        self.assertNotIn("memory_context_token", state)
        self.assertNotIn("active_agent_job_id", state)
        self.assertEqual({"view": "settings"}, query)

    def test_readonly_database_enables_query_only_and_rejects_writes(self) -> None:
        with product_pages._readonly_database(self.memory_db) as connection:
            query_only = int(connection.execute("PRAGMA query_only").fetchone()[0])
            self.assertEqual(1, query_only)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden_write(value TEXT)")

        connection = sqlite3.connect(self.memory_db)
        try:
            forbidden_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("forbidden_write",),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(forbidden_table)

    def test_packaged_literature_index_materializes_only_configured_path(self) -> None:
        from agent import rag

        runtime_db = Path(self.tempdir.name) / "runtime" / "literature.db"
        foreign_db = Path(self.tempdir.name) / "foreign" / "literature.db"
        calls: list[Path] = []

        def materialize(path: Path) -> bool:
            candidate = Path(path)
            calls.append(candidate)
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(b"fixture")
            return True

        with (
            patch.object(rag, "LITERATURE_DB_PATH", runtime_db),
            patch.object(rag, "ensure_literature_database", side_effect=materialize),
        ):
            self.assertFalse(product_pages._prepare_literature_database(foreign_db))
            self.assertTrue(product_pages._prepare_literature_database(runtime_db))

        self.assertEqual([runtime_db], calls)
        self.assertEqual(b"fixture", runtime_db.read_bytes())

    def test_packaged_knowledge_catalog_matches_the_full_index_manifest(self) -> None:
        catalog_path = product_pages.DEFAULT_KNOWLEDGE_CATALOG_PATH
        self.assertTrue(catalog_path.is_file())
        self.assertLess(catalog_path.stat().st_size, 32 * 1024 * 1024)
        with closing(sqlite3.connect(catalog_path)) as connection:
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
            meta = dict(connection.execute("SELECT key, value FROM catalog_meta"))

        manifest_path = catalog_path.parent / "package" / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(int(manifest["documents"]), int(meta["source_documents"]))
            self.assertEqual(int(manifest["chunks"]), int(meta["source_chunks"]))
        else:
            with closing(sqlite3.connect(product_pages.DEFAULT_LITERATURE_DB_PATH)) as connection:
                self.assertEqual(
                    int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
                    int(meta["source_documents"]),
                )
                self.assertEqual(
                    int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]),
                    int(meta["source_chunks"]),
                )

    def test_lightweight_catalog_preserves_filters_counts_and_storage_totals(self) -> None:
        connection = sqlite3.connect(self.literature_db)
        try:
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "doc_nfc_technology",
                    "DC-NFC framework for NFC-enabled IoT",
                    '["Researcher C"]',
                    "2026",
                    '["橙汁"]',
                    "Unrelated Journal",
                    "",
                    "橙汁/nfc-iot.pdf",
                    999,
                    "good",
                ),
            )
            connection.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                (4, "doc_nfc_technology", "橙汁", "wireless network evidence"),
            )
            connection.commit()
        finally:
            connection.close()

        catalog_path = Path(self.tempdir.name) / "knowledge_catalog.db"
        built = catalog_index.build_catalog(self.literature_db, catalog_path)
        self.assertLess(catalog_path.stat().st_size, 2 * 1024 * 1024)
        self.assertEqual(3, built["source_documents"])
        self.assertEqual(4, built["source_chunks"])
        self.assertEqual(2, built["visible_documents"])
        self.assertEqual(3, built["visible_chunks"])

        with closing(sqlite3.connect(catalog_path)) as catalog:
            tables = {
                row[0]
                for row in catalog.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertNotIn("chunks", tables)
        self.assertIn("catalog_meta", tables)

        facets = product_pages._load_knowledge_facets(catalog_path)
        listing = product_pages._load_knowledge_documents(catalog_path)
        storage = product_pages._knowledge_storage_counts(catalog_path)
        self.assertEqual({"documents": 2, "chunks": 3}, facets["stats"])
        self.assertEqual(["doc_juice", "doc_peel"], [row["document_id"] for row in listing["rows"]])
        self.assertEqual({"documents": 3, "chunks": 4}, storage)

    def test_knowledge_render_uses_catalog_without_materializing_full_database(self) -> None:
        catalog_path = Path(self.tempdir.name) / "knowledge_catalog.db"
        missing_full_path = Path(self.tempdir.name) / "runtime" / "literature.db"
        catalog_index.build_catalog(self.literature_db, catalog_path)
        source = f"""
from pathlib import Path
import streamlit as st
from unittest.mock import patch
from app.ui import product_pages

def fail_materialization(path):
    raise AssertionError("full database must not be materialized")

with (
    patch.object(product_pages, "DEFAULT_KNOWLEDGE_CATALOG_PATH", Path({str(catalog_path)!r})),
    patch.object(product_pages, "_literature_db_path", return_value=Path({str(missing_full_path)!r})),
    patch.object(product_pages, "_prepare_literature_database", side_effect=fail_materialization),
):
    st.session_state.memory_user_id = "user_alpha"
    st.session_state.memory_project_id = "project_one"
    product_pages.render_knowledge_page()
"""
        app = AppTest.from_string(source, default_timeout=30).run()
        self.assertEqual([], list(app.exception))

    def test_workspace_analytics_and_storage_are_scope_isolated(self) -> None:
        scope = product_pages._Scope("user_alpha", "project_one")
        workspace = product_pages._load_workspace(self.memory_db, scope)
        analytics = product_pages._load_analytics(self.memory_db, scope)
        storage = product_pages._scoped_storage_counts(self.memory_db, scope)

        self.assertEqual(
            {
                "sessions": 1,
                "messages": 2,
                "runs": 1,
                "completed_runs": 1,
                "failed_runs": 0,
                "samples": 1,
                "review_samples": 1,
            },
            workspace["counts"],
        )
        self.assertEqual(["run_alpha"], [row["run_id"] for row in workspace["runs"]])
        self.assertEqual(
            ["sample_alpha"],
            [row["sample_id"] for row in workspace["samples"]],
        )
        self.assertEqual(1, analytics["counts"]["sessions"])
        self.assertEqual(1, analytics["counts"]["runs"])
        self.assertEqual(
            ["run_alpha"],
            [row["run_id"] for row in analytics["recent_runs"]],
        )
        self.assertEqual(
            {"sessions": 1, "messages": 2, "runs": 1, "memories": 1, "samples": 1},
            storage,
        )

        serialized = repr(workspace) + repr(analytics)
        self.assertNotIn("private message for beta", serialized)
        self.assertNotIn("private task for beta", serialized)
        self.assertNotIn("other_project", serialized)

    def test_json_arrays_are_strict_but_legacy_author_text_is_supported(self) -> None:
        self.assertEqual([], product_pages._json_list("not-json"))
        self.assertEqual([], product_pages._json_list('{"value": 1}'))
        self.assertEqual(["one"], product_pages._json_list('["one"]'))
        self.assertEqual("—", product_pages._list_text("Legacy Author"))
        self.assertEqual(
            "Legacy Author",
            product_pages._list_text("Legacy Author", allow_plain_text=True),
        )
        self.assertEqual(
            "Legacy Author",
            product_pages._list_text('"Legacy Author"', allow_plain_text=True),
        )

    def test_display_time_and_daily_analytics_use_beijing_time(self) -> None:
        self.assertEqual(
            "2026-08-02 00:30",
            product_pages._display_time("2026-08-01T16:30:00Z"),
        )
        self.assertEqual(
            "2026-08-01 18:00",
            product_pages._display_time("2026-08-01T10:00:00"),
        )

        connection = sqlite3.connect(self.memory_db)
        try:
            connection.execute(
                "INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "run_alpha_after_midnight",
                    "user_alpha",
                    "session_alpha",
                    "project_one",
                    "late analysis",
                    "fixture-model",
                    "[]",
                    "[]",
                    "done",
                    "",
                    "2026-08-01T16:30:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        analytics = product_pages._load_analytics(
            self.memory_db,
            product_pages._Scope("user_alpha", "project_one"),
        )
        self.assertEqual(
            ["2026-08-01", "2026-08-02"],
            [row["day"] for row in analytics["daily"]],
        )

    def test_run_trend_fills_calendar_days_and_compares_equal_windows(self) -> None:
        trend = product_pages._build_run_trend(
            [
                {
                    "day": "2026-07-31",
                    "runs": 2,
                    "successful_runs": 1,
                    "failed_runs": 1,
                },
                {
                    "day": "2026-08-01",
                    "runs": 3,
                    "successful_runs": 2,
                    "failed_runs": 1,
                },
                {
                    "day": "2026-08-14",
                    "runs": 1,
                    "successful_runs": 1,
                    "failed_runs": 0,
                },
                {"day": "invalid", "runs": 99},
            ],
            today=date(2026, 8, 14),
        )

        self.assertEqual(14, len(trend["days"]))
        self.assertEqual(date(2026, 8, 1), trend["days"][0]["day"])
        self.assertEqual(date(2026, 8, 14), trend["days"][-1]["day"])
        self.assertEqual(4, trend["current_runs"])
        self.assertEqual(2, trend["previous_runs"])
        self.assertEqual("较前 14 天 +100%", trend["comparison"])
        self.assertEqual(2, trend["active_days"])
        self.assertEqual(1, trend["failed_runs"])
        self.assertEqual("75%", trend["completion_rate"])
        self.assertEqual("8月1日 · 3 次", trend["peak_label"])
        self.assertEqual("今天", trend["latest_activity_label"])
        self.assertEqual(0, trend["days"][1]["runs"])

    def test_run_trend_distinguishes_no_history_from_recent_inactivity(self) -> None:
        empty = product_pages._build_run_trend([], today=date(2026, 8, 14))
        inactive = product_pages._build_run_trend(
            [
                {
                    "day": "2026-07-01",
                    "runs": 1,
                    "successful_runs": 1,
                    "failed_runs": 0,
                }
            ],
            today=date(2026, 8, 14),
        )

        self.assertFalse(empty["has_history"])
        self.assertTrue(inactive["has_history"])
        self.assertEqual(0, inactive["current_runs"])
        self.assertEqual("近 14 天暂无运行", inactive["comparison"])
        self.assertEqual("7月1日", inactive["latest_activity_label"])

    def test_pending_follow_up_does_not_reuse_previous_answer(self) -> None:
        connection = sqlite3.connect(self.memory_db)
        try:
            connection.execute(
                """
                INSERT INTO conversation_messages(
                    message_id, user_id, session_id, project_id,
                    role, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "message_alpha_follow_up",
                    "user_alpha",
                    "session_alpha",
                    "project_one",
                    "user",
                    "第二个问题还在等待回答",
                    "2026-08-01T11:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        scope = product_pages._Scope("user_alpha", "project_one")
        workspace = product_pages._load_workspace(self.memory_db, scope)
        pending = product_pages._workspace_session_row(workspace["sessions"][0])
        self.assertEqual("第二个问题还在等待回答", pending["主题"])
        self.assertEqual("—", pending["最新结论"])
        self.assertEqual("待回复", pending["进度"])

        connection = sqlite3.connect(self.memory_db)
        try:
            connection.execute(
                """
                INSERT INTO conversation_messages(
                    message_id, user_id, session_id, project_id,
                    role, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "answer_alpha_follow_up",
                    "user_alpha",
                    "session_alpha",
                    "project_one",
                    "assistant",
                    "第二个问题的新结论。",
                    "2026-08-01T11:01:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        workspace = product_pages._load_workspace(self.memory_db, scope)
        answered = product_pages._workspace_session_row(workspace["sessions"][0])
        self.assertEqual("第二个问题的新结论。", answered["最新结论"])
        self.assertEqual("已回复 · 2 轮", answered["进度"])

    def test_workspace_activity_ignores_session_maintenance_updates(self) -> None:
        connection = sqlite3.connect(self.memory_db)
        try:
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                ("2026-08-14T15:03:29+00:00", "session_alpha"),
            )
            connection.commit()
        finally:
            connection.close()

        workspace = product_pages._load_workspace(
            self.memory_db,
            product_pages._Scope("user_alpha", "project_one"),
        )
        row = workspace["sessions"][0]
        self.assertEqual("2026-08-01T10:00:00+00:00", row["activity_at"])
        self.assertEqual(
            "2026-08-01 18:00",
            product_pages._workspace_session_row(row)["最近时间"],
        )

    def test_evidence_counts_are_deduplicated_and_malformed_json_is_empty(self) -> None:
        row = {
            "original_input": "分析任务",
            "tool_calls_json": "[]",
            "retrieved_literature_ids_json": '["chunk_a", "chunk_a", "chunk_b"]',
            "final_output": "分析完成。",
            "error": "",
            "created_at": "2026-08-01T10:00:00+00:00",
        }
        self.assertEqual("2 条证据", product_pages._workspace_run_row(row)["证据"])
        row["retrieved_literature_ids_json"] = "not-json"
        self.assertEqual("暂无证据", product_pages._workspace_run_row(row)["证据"])

    def test_knowledge_quality_labels_cover_real_and_unknown_states(self) -> None:
        self.assertEqual("已索引", product_pages._knowledge_quality_label("good"))
        self.assertEqual("内容有限", product_pages._knowledge_quality_label("limited"))
        self.assertEqual("待 OCR", product_pages._knowledge_quality_label("ocr_required"))
        self.assertEqual("状态未知", product_pages._knowledge_quality_label("unexpected"))

    def test_knowledge_filters_technology_false_positives_and_labels_relevance(self) -> None:
        connection = sqlite3.connect(self.literature_db)
        try:
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "doc_nfc_technology",
                    "DC-NFC framework for NFC-enabled IoT",
                    '["Researcher C"]',
                    "2026",
                    '["橙汁"]',
                    "Unrelated Journal",
                    "",
                    "橙汁/nfc-iot.pdf",
                    1,
                    "good",
                ),
            )
            connection.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?)",
                (4, "doc_nfc_technology", "橙汁", "wireless network evidence"),
            )
            connection.commit()
        finally:
            connection.close()

        listing = product_pages._load_knowledge_documents(self.literature_db)
        facets = product_pages._load_knowledge_facets(self.literature_db)
        self.assertEqual(2, listing["total"])
        self.assertEqual(
            ["doc_juice", "doc_peel"],
            [row["document_id"] for row in listing["rows"]],
        )
        self.assertEqual(2, facets["stats"]["documents"])
        self.assertEqual(3, facets["stats"]["chunks"])
        self.assertEqual(
            {"橙汁": 1, "副产物": 1, "果胶": 1},
            dict(facets["categories"]),
        )
        self.assertTrue(
            product_pages._is_off_domain_knowledge_title(
                "Near Field Communication for future payment systems"
            )
        )
        self.assertEqual(
            "柑橘直接证据",
            product_pages._knowledge_relevance_label("Citrus peel utilization"),
        )
        self.assertEqual(
            "柑橘直接证据",
            product_pages._knowledge_relevance_label(
                "Identification of Citri Reticulatae Pericarpium"
            ),
        )
        self.assertEqual(
            "工艺参考",
            product_pages._knowledge_relevance_label("Pineapple peel extraction"),
        )

    def test_review_sample_count_uses_the_same_status_classifier_as_rows(self) -> None:
        connection = sqlite3.connect(self.memory_db)
        try:
            connection.execute(
                """
                INSERT INTO citrus_samples VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    "sample_alpha_manual_review",
                    "session_alpha",
                    "user_alpha",
                    "project_one",
                    "沃柑",
                    "广西",
                    "外观与检测记录完整，仍需人工确认。",
                    "复核加工方向",
                    json.dumps(
                        {
                            "weight_kg": 500,
                            "pesticide_status": "passed",
                            "microbe_status": "passed",
                        },
                        ensure_ascii=False,
                    ),
                    "果肉-柑橘汁/NFC",
                    "待确认",
                    0.8,
                    "active",
                    "2026-08-02T10:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        workspace = product_pages._load_workspace(
            self.memory_db,
            product_pages._Scope("user_alpha", "project_one"),
        )
        self.assertEqual(2, workspace["counts"]["samples"])
        self.assertEqual(2, workspace["counts"]["review_samples"])
        manual_sample = next(
            row
            for row in workspace["samples"]
            if row["sample_id"] == "sample_alpha_manual_review"
        )
        self.assertEqual("质量复核", product_pages._sample_quality_status(manual_sample))

    def test_analytics_uses_evidence_language_instead_of_document_counts(self) -> None:
        app = self._render_page("analytics")
        rendered = "\n".join(element.value for element in app.markdown)
        self.assertIn("analytics-trend-panel", rendered)
        self.assertIn("活跃天数", rendered)
        self.assertIn("近 14 天完成率", rendered)
        self.assertIn("证据", rendered)
        self.assertIn("1 条证据", rendered)
        self.assertNotIn("<th scope=\"col\">文献</th>", rendered)

        source = Path(product_pages.__file__).read_text(encoding="utf-8")
        self.assertNotIn("st.bar_chart", source)

    def test_workspace_rows_show_business_information_only(self) -> None:
        workspace = product_pages._load_workspace(
            self.memory_db,
            product_pages._Scope("user_alpha", "project_one"),
        )

        self.assertEqual(
            {
                "主题": "分析广西沃柑的加工方向",
                "最新结论": "当前优先方向是 果肉-柑橘汁/NFC。",
                "进度": "已回复 · 1 轮",
                "最近时间": "2026-08-01 18:00",
            },
            product_pages._workspace_session_row(workspace["sessions"][0]),
        )
        self.assertEqual(
            {
                "分析任务": "分析广西沃柑的加工方向",
                "主要结果": "当前优先方向是 果肉-柑橘汁/NFC（条件性备选）。",
                "状态": "完成 · 待复核",
                "证据": "1 条证据",
                "时间": "2026-08-01 18:00",
            },
            product_pages._workspace_run_row(workspace["runs"][0]),
        )
        self.assertEqual(
            {
                "批次概况": "沃柑 · 广西",
                "关键指标": "重量 1,500 kg · 糖度 13 °Brix · 酸度 0.6%",
                "建议方向": "果肉-柑橘汁/NFC",
                "质控状态": "暂不可放行",
                "更新时间": "2026-08-01 18:00",
            },
            product_pages._workspace_sample_row(workspace["samples"][0]),
        )

    def test_workspace_page_hides_internal_identifiers_and_tool_metadata(self) -> None:
        app = self._render_page("workspace")
        rendered = "\n".join(element.value for element in app.markdown)

        self.assertIn("workspace-table", rendered)
        self.assertIn('data-label="主题"', rendered)

        for heading in (
            "主题",
            "最新结论",
            "分析任务",
            "主要结果",
            "批次概况",
            "关键指标",
            "建议方向",
            "质控状态",
        ):
            self.assertIn(heading, rendered)
        for internal_value in (
            "session_alpha",
            "run_alpha",
            "sample_alpha",
            "fixture-model",
            "Evidence-aware Route Ranker",
            "Quality Gate",
            "工具调用",
            "可信度",
        ):
            self.assertNotIn(internal_value, rendered)

    def test_sql_injection_shaped_scope_values_do_not_expand_results(self) -> None:
        malicious_scopes = [
            product_pages._Scope("user_alpha' OR 1=1 --", "project_one"),
            product_pages._Scope("user_alpha", "project_one' OR 1=1 --"),
        ]
        for scope in malicious_scopes:
            with self.subTest(scope=scope):
                workspace = product_pages._load_workspace(self.memory_db, scope)
                analytics = product_pages._load_analytics(self.memory_db, scope)
                storage = product_pages._scoped_storage_counts(self.memory_db, scope)

                self.assertEqual(
                    {
                        "sessions": 0,
                        "messages": 0,
                        "runs": 0,
                        "completed_runs": 0,
                        "failed_runs": 0,
                        "samples": 0,
                        "review_samples": 0,
                    },
                    workspace["counts"],
                )
                self.assertEqual([], workspace["sessions"])
                self.assertEqual([], workspace["runs"])
                self.assertEqual([], workspace["samples"])
                self.assertEqual(0, analytics["counts"]["sessions"])
                self.assertEqual(0, analytics["counts"]["runs"])
                self.assertEqual([], analytics["recent_runs"])
                self.assertTrue(all(int(value) == 0 for value in storage.values()))


if __name__ == "__main__":
    unittest.main()
