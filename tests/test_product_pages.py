from __future__ import annotations

import json
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
                "最近时间": "2026-08-01 10:00",
            },
            product_pages._workspace_session_row(workspace["sessions"][0]),
        )
        self.assertEqual(
            {
                "分析任务": "分析广西沃柑的加工方向",
                "主要结果": "当前优先方向是 果肉-柑橘汁/NFC（条件性备选）。",
                "状态": "完成 · 待复核",
                "证据": "1 篇文献",
                "时间": "2026-08-01 10:00",
            },
            product_pages._workspace_run_row(workspace["runs"][0]),
        )
        self.assertEqual(
            {
                "批次概况": "沃柑 · 广西",
                "关键指标": "重量 1,500 kg · 糖度 13 °Brix · 酸度 0.6%",
                "建议方向": "果肉-柑橘汁/NFC",
                "质控状态": "暂不可放行",
                "更新时间": "2026-08-01 10:00",
            },
            product_pages._workspace_sample_row(workspace["samples"][0]),
        )

    def test_workspace_page_hides_internal_identifiers_and_tool_metadata(self) -> None:
        app = self._render_page("workspace")
        rendered = "\n".join(element.value for element in app.markdown)

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
