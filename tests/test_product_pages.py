from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

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
    processing_goal TEXT,
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
                        f"private message for {suffix}",
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"run_{suffix}",
                        user_id,
                        session_id,
                        project_id,
                        f"private task for {suffix}",
                        "fixture-model",
                        '[{"tool": "fixture"}]',
                        f'["literature_{suffix}"]',
                        "",
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO citrus_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"sample_{suffix}",
                        session_id,
                        user_id,
                        project_id,
                        f"variety_{suffix}",
                        f"origin_{suffix}",
                        f"goal_{suffix}",
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
from app.ui import product_pages

product_pages._memory_db_path = lambda: Path({str(self.memory_db)!r})
product_pages._literature_db_path = lambda: Path({str(self.literature_db)!r})
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

    def test_workspace_analytics_and_storage_are_scope_isolated(self) -> None:
        scope = product_pages._Scope("user_alpha", "project_one")
        workspace = product_pages._load_workspace(self.memory_db, scope)
        analytics = product_pages._load_analytics(self.memory_db, scope)
        storage = product_pages._scoped_storage_counts(self.memory_db, scope)

        self.assertEqual(
            {"sessions": 1, "messages": 1, "runs": 1, "samples": 1},
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
            {"sessions": 1, "messages": 1, "runs": 1, "memories": 1, "samples": 1},
            storage,
        )

        serialized = repr(workspace) + repr(analytics)
        self.assertNotIn("private message for beta", serialized)
        self.assertNotIn("private task for beta", serialized)
        self.assertNotIn("other_project", serialized)

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
                    {"sessions": 0, "messages": 0, "runs": 0, "samples": 0},
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
