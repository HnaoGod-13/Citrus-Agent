from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from app import main as app_main
from agent.memory import MemoryManager, MemoryValidationError, _normalize_message_content
from agent.rules import QualityRisk, ScoreResult
from agent.workflow import AgentStep
from app.main import (
    build_persisted_analysis_payload,
    restore_flattened_markdown,
    restore_ui_messages,
)


def make_analysis_payload(batch_id: str = "B-FORMAT-001") -> dict:
    batch = {
        "batch_id": batch_id,
        "origin": "赣南",
        "variety": "脐橙",
    }
    answer = "# 批次结论\n\n- 优先生产 NFC 果汁\n- 果皮同步利用"
    return {
        "batch": batch,
        "result": {
            "batch": batch,
            "agent_steps": [AgentStep("检索", "retriever", "完成", "已获得证据")],
            "scores": [ScoreResult("NFC 果汁", 88)],
            "quality_risks": [QualityRisk("高", "微生物", "补充检测")],
            "evidence": [],
            "processing_plan": {},
            "parameter_groups": [],
            "parameterized_plan": {},
            "report": "# 报告",
        },
        "report_path": Path(f"outputs/reports/{batch_id}.md"),
        "summary": "批次分析完成",
        "answer": answer,
        "vision_result": {
            "answer": "候选品种为脐橙",
            "variety_candidate": "脐橙",
            "_raw_model_output": "不应持久化的原始模型输出",
        },
    }


def make_row(
    message_id: str,
    role: str,
    content: str,
    *,
    message_type: str = "chat",
    metadata: dict | None = None,
) -> dict:
    return {
        "message_id": message_id,
        "role": role,
        "content": content,
        "message_type": message_type,
        "metadata": metadata or {},
    }


class MessagePersistenceFormattingTests(unittest.TestCase):
    def test_message_normalization_only_normalizes_line_endings(self) -> None:
        raw = "# 分析结果\r\n\r\n- 一级项目\r\n  - 二级项目\r\n\r\n    保留四格缩进"
        expected = "# 分析结果\n\n- 一级项目\n  - 二级项目\n\n    保留四格缩进"

        self.assertEqual(_normalize_message_content(raw), expected)

    def test_sqlite_round_trip_preserves_full_formatted_answer_beyond_12000_chars(self) -> None:
        block = (
            "# 批次分析\n\n"
            "**优先方向**：NFC 果汁\n\n"
            "- 原料验收\n"
            "  - 糖度 12.2 Brix\n\n"
            "| 指标 | 结果 |\n"
            "| --- | --- |\n"
            "| 糖度 | 12.2 Brix |\n\n"
            "```text\n"
            "    保留四格缩进\n"
            "```\n\n"
        )
        content = block * 220 + "END_OF_FORMATTED_ANSWER"
        self.assertGreater(len(content), 12000)

        with tempfile.TemporaryDirectory() as tempdir:
            manager = MemoryManager(Path(tempdir) / "memory.db")
            manager.record_message(
                "user-format",
                "session-format",
                "project-format",
                "assistant",
                content,
                message_id="assistant-format",
            )
            restored = manager.restore_session_messages(
                "user-format",
                "session-format",
                "project-format",
            )

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["content"], content)
        self.assertTrue(restored[0]["content"].endswith("END_OF_FORMATTED_ANSWER"))

    def test_sqlite_round_trip_preserves_leading_indentation_and_trailing_newline(self) -> None:
        content = "    首行保留四格缩进\n正文保持原样\n"

        with tempfile.TemporaryDirectory() as tempdir:
            manager = MemoryManager(Path(tempdir) / "memory.db")
            manager.record_message(
                "user-boundary",
                "session-boundary",
                "project-boundary",
                "assistant",
                content,
                message_id="assistant-boundary",
            )
            restored = manager.restore_session_messages(
                "user-boundary",
                "session-boundary",
                "project-boundary",
            )

        self.assertEqual(restored[0]["content"], content)

    def test_whitespace_only_message_is_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            manager = MemoryManager(Path(tempdir) / "memory.db")

            with self.assertRaises(MemoryValidationError):
                manager.record_message(
                    "user-whitespace",
                    "session-whitespace",
                    "project-whitespace",
                    "assistant",
                    "  \t\n\r\n    ",
                    message_id="assistant-whitespace",
                )


class MemoryManagerCacheVersionTests(unittest.TestCase):
    def test_get_memory_manager_passes_message_storage_version_to_cache_factory(self) -> None:
        manager = object()
        with patch.object(app_main, "_get_memory_manager", return_value=manager) as factory:
            restored = app_main.get_memory_manager()

        self.assertIs(restored, manager)
        factory.assert_called_once_with(app_main.agent_memory.MESSAGE_STORAGE_VERSION)

    def test_message_storage_version_change_creates_a_different_cache_key(self) -> None:
        current_version = app_main.agent_memory.MESSAGE_STORAGE_VERSION
        next_version = current_version + 1
        with patch.object(app_main, "_get_memory_manager") as factory:
            with patch.object(
                app_main.agent_memory,
                "MESSAGE_STORAGE_VERSION",
                current_version,
            ):
                app_main.get_memory_manager()
            with patch.object(
                app_main.agent_memory,
                "MESSAGE_STORAGE_VERSION",
                next_version,
            ):
                app_main.get_memory_manager()

        self.assertEqual(factory.call_args_list, [call(current_version), call(next_version)])


class AssistantMarkdownRenderingTests(unittest.TestCase):
    def test_regular_assistant_uses_native_markdown_without_cleaning(self) -> None:
        original = (
            "# 原始标题\n\n"
            "- **保留粗体列表**\n\n"
            "```text\n"
            "    保留代码缩进\n"
            "```\n\n"
            "<script>alert('must stay inert')</script>"
        )

        with (
            patch.object(
                app_main,
                "clean_assistant_text",
                return_value="CLEANED_CONTENT_MUST_NOT_BE_USED",
                create=True,
            ) as clean_mock,
            patch.object(app_main.st, "markdown") as markdown_mock,
        ):
            app_main.render_message({"role": "assistant", "content": original})

        clean_mock.assert_not_called()
        native_calls = [
            markdown_call
            for markdown_call in markdown_mock.call_args_list
            if markdown_call.args
            and markdown_call.args[0] == original
            and not markdown_call.kwargs.get("unsafe_allow_html", False)
        ]
        self.assertEqual(len(native_calls), 1)


class AnalysisMessageRestorationTests(unittest.TestCase):
    def test_analysis_snapshot_is_json_safe_and_restores_structured_payload(self) -> None:
        source = make_analysis_payload()
        snapshot = build_persisted_analysis_payload(source)
        decoded = json.loads(json.dumps(snapshot, ensure_ascii=False))

        self.assertIsInstance(decoded["result"]["agent_steps"][0], dict)
        self.assertIsInstance(decoded["result"]["scores"][0], dict)
        self.assertIsInstance(decoded["result"]["quality_risks"][0], dict)
        self.assertNotIn("_raw_model_output", decoded["vision_result"])
        self.assertEqual(decoded["answer"], source["answer"])

        restored = restore_ui_messages(
            [
                make_row(
                    "analysis-new",
                    "assistant",
                    source["answer"],
                    message_type="analysis",
                    metadata={
                        "analysis_payload": snapshot,
                        "audit_trace": {"run_id": "run-format"},
                    },
                )
            ]
        )

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["kind"], "analysis")
        self.assertEqual(restored[0]["payload"], snapshot)
        self.assertEqual(restored[0]["content"], source["answer"])

    def test_analysis_snapshot_survives_sqlite_metadata_round_trip(self) -> None:
        snapshot = build_persisted_analysis_payload(make_analysis_payload())

        with tempfile.TemporaryDirectory() as tempdir:
            manager = MemoryManager(Path(tempdir) / "memory.db")
            manager.record_message(
                "user-analysis",
                "session-analysis",
                "project-analysis",
                "assistant",
                snapshot["answer"],
                message_id="analysis-snapshot",
                message_type="analysis",
                metadata={"analysis_payload": snapshot},
            )
            rows = manager.restore_session_messages(
                "user-analysis",
                "session-analysis",
                "project-analysis",
            )

        self.assertEqual(rows[0]["metadata"]["analysis_payload"], snapshot)
        restored = restore_ui_messages(rows)
        self.assertEqual(restored[0]["kind"], "analysis")
        self.assertEqual(restored[0]["payload"], snapshot)

    def test_incomplete_v1_snapshots_fall_back_without_render_key_error(self) -> None:
        invalid_snapshots = {
            "missing_result": {
                "version": 1,
                "report_path": "outputs/reports/incomplete.md",
                "answer": "# 旧分析\n\n保留原回答",
            },
            "missing_report_path": {
                "version": 1,
                "result": {"report": "# 报告"},
                "answer": "# 旧分析\n\n保留原回答",
            },
            "missing_result_report": {
                "version": 1,
                "result": {},
                "report_path": "outputs/reports/incomplete.md",
                "answer": "# 旧分析\n\n保留原回答",
            },
        }

        for case_name, snapshot in invalid_snapshots.items():
            with self.subTest(case=case_name):
                restored = restore_ui_messages(
                    [
                        make_row(
                            f"analysis-{case_name}",
                            "assistant",
                            snapshot["answer"],
                            message_type="analysis",
                            metadata={"analysis_payload": snapshot},
                        )
                    ]
                )

                self.assertEqual(len(restored), 1)
                self.assertEqual(restored[0].get("kind"), "analysis_legacy")
                self.assertNotIn("payload", restored[0])
                with patch.object(app_main.st, "markdown"):
                    app_main.render_message(restored[0])

    def test_restore_flattened_markdown_recreates_headings_lists_and_table_rows(self) -> None:
        flattened = (
            "# 批次分析 ## 结论 - 建议优先生产 NFC 果汁 - 果皮同步利用 "
            "| 指标 | 结果 | | --- | --- | | 糖度 | 12.2 Brix | ## 风险提示 "
            "- 补做微生物检测"
        )
        restored = restore_flattened_markdown(flattened)
        nonempty_lines = [line for line in restored.splitlines() if line.strip()]

        self.assertEqual(
            nonempty_lines,
            [
                "# 批次分析",
                "## 结论",
                "- 建议优先生产 NFC 果汁",
                "- 果皮同步利用",
                "| 指标 | 结果 |",
                "| --- | --- |",
                "| 糖度 | 12.2 Brix |",
                "## 风险提示",
                "- 补做微生物检测",
            ],
        )

    def test_restore_flattened_markdown_does_not_change_existing_layout(self) -> None:
        formatted = (
            "# 批次分析\n\n"
            "## 结论\n"
            "- 建议优先生产 NFC 果汁\n"
            "- 果皮同步利用\n\n"
            "| 指标 | 结果 |\n"
            "| --- | --- |\n"
            "| 糖度 | 12.2 Brix |"
        )

        self.assertEqual(restore_flattened_markdown(formatted), formatted)

    def test_legacy_analysis_is_not_folded_and_recovers_flattened_layout(self) -> None:
        flattened = "# 批次分析 ## 结论 - 优先榨汁 - 果皮同步利用"
        expected = restore_flattened_markdown(flattened)
        restored = restore_ui_messages(
            [
                make_row(
                    "analysis-legacy",
                    "assistant",
                    flattened,
                    message_type="analysis",
                )
            ]
        )

        self.assertEqual(len(restored), 1)
        self.assertNotEqual(restored[0].get("kind"), "analysis_summary")
        self.assertNotEqual(restored[0].get("kind"), "analysis")
        self.assertNotIn("payload", restored[0])
        self.assertEqual(restored[0]["content"], expected)
        self.assertGreater(restored[0]["content"].count("\n"), 1)

    def test_tool_audit_and_summary_rows_do_not_enter_ui_history(self) -> None:
        restored = restore_ui_messages(
            [
                make_row("user-1", "user", "第一个问题"),
                make_row("tool-1", "tool", "内部工具结果", message_type="tool_result"),
                make_row("audit-1", "assistant", "内部审计", message_type="audit"),
                make_row("summary-1", "assistant", "内部摘要", message_type="summary"),
                make_row("assistant-1", "assistant", "正常回答"),
            ]
        )

        self.assertEqual(
            [message["message_id"] for message in restored],
            ["user-1", "assistant-1"],
        )

    def test_latest_analysis_restores_batch_result_and_vision_context(self) -> None:
        older = build_persisted_analysis_payload(make_analysis_payload("B-OLDER"))
        latest = build_persisted_analysis_payload(make_analysis_payload("B-LATEST"))
        messages = restore_ui_messages(
            [
                make_row(
                    "analysis-older",
                    "assistant",
                    older["answer"],
                    message_type="analysis",
                    metadata={"analysis_payload": older},
                ),
                make_row(
                    "analysis-latest",
                    "assistant",
                    latest["answer"],
                    message_type="analysis",
                    metadata={"analysis_payload": latest},
                ),
                make_row("assistant-follow-up", "assistant", "后续普通回答"),
            ]
        )

        batch, result, vision = app_main.restore_latest_analysis_state(messages)

        self.assertEqual(batch["batch_id"], "B-LATEST")
        self.assertEqual(result["batch"]["batch_id"], "B-LATEST")
        self.assertEqual(vision["variety_candidate"], "脐橙")
        self.assertEqual(vision["vision_answer"], "候选品种为脐橙")

    def test_duplicate_message_ids_are_restored_only_once(self) -> None:
        restored = restore_ui_messages(
            [
                make_row("duplicate-1", "assistant", "首次保存的回答"),
                make_row("duplicate-1", "assistant", "不应重复出现的回答"),
            ]
        )

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["message_id"], "duplicate-1")
        self.assertEqual(restored[0]["content"], "首次保存的回答")

    def test_two_turn_history_restores_visible_order_and_uniqueness(self) -> None:
        snapshot = build_persisted_analysis_payload(make_analysis_payload("B-TWO-TURN"))
        restored = restore_ui_messages(
            [
                make_row("user-first", "user", "第一个问题"),
                make_row(
                    "analysis-first",
                    "assistant",
                    snapshot["answer"],
                    message_type="analysis",
                    metadata={"analysis_payload": snapshot},
                ),
                make_row(
                    "tool-between",
                    "tool",
                    "内部工具结果",
                    message_type="tool_result",
                ),
                make_row("user-second", "user", "第二个问题"),
                make_row("chat-second", "assistant", "第二个问题的回答"),
            ]
        )

        restored_ids = [message["message_id"] for message in restored]
        self.assertEqual(
            restored_ids,
            ["user-first", "analysis-first", "user-second", "chat-second"],
        )
        self.assertEqual(
            [message["role"] for message in restored],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertEqual(len(restored_ids), len(set(restored_ids)))
        self.assertEqual(
            sum(message["content"] == "第二个问题" for message in restored),
            1,
        )


class LegacyAnalysisRecoverySafetyTests(unittest.TestCase):
    def test_memory_manager_error_during_legacy_recovery_returns_none(self) -> None:
        manager = MagicMock()
        manager.get_agent_run.side_effect = app_main.agent_memory.MemoryManagerError(
            "memory unavailable"
        )

        recovered = app_main.recover_legacy_analysis_payload(
            manager,
            "user-legacy",
            "project-legacy",
            {"run_id": "run-memory-error", "content": "# 旧分析"},
        )

        self.assertIsNone(recovered)

    def test_malformed_tool_calls_during_legacy_recovery_return_none(self) -> None:
        malformed_values = [
            "not-a-list",
            {"result_ref": "not-a-list-of-dicts.tools.json"},
            [None, "not-a-dict", 42],
        ]

        for index, tool_calls in enumerate(malformed_values):
            with self.subTest(tool_calls=tool_calls):
                manager = MagicMock()
                manager.get_agent_run.return_value = {
                    "run_id": f"run-malformed-{index}",
                    "tool_calls": tool_calls,
                }

                recovered = app_main.recover_legacy_analysis_payload(
                    manager,
                    "user-legacy",
                    "project-legacy",
                    {"run_id": f"run-malformed-{index}", "content": "# 旧分析"},
                )

                self.assertIsNone(recovered)

    def test_outside_referenced_report_path_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp_root = Path(tempdir)
            report_root = temp_root / "reports"
            report_root.mkdir()
            tool_result_path = report_root / "legacy-run.tools.json"
            tool_result_path.write_text(
                json.dumps(
                    {
                        "batch": {"batch_id": "B-LEGACY"},
                        "report": "# 安全报告",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            outside_report = temp_root / "outside" / "untrusted.md"

            manager = MagicMock()
            manager.get_agent_run.return_value = {
                "run_id": "run-outside-report",
                "model_name": "remote-model",
                "tool_calls": [{"result_ref": str(tool_result_path)}],
                "state_updates": {
                    "referenced_files": {"add": [str(outside_report)]},
                },
            }
            with patch.object(app_main.workflow, "REPORT_DIR", report_root):
                recovered = app_main.recover_legacy_analysis_payload(
                    manager,
                    "user-legacy",
                    "project-legacy",
                    {
                        "run_id": "run-outside-report",
                        "content": "# 旧分析\n\n恢复原始回答",
                    },
                )

            self.assertIsNotNone(recovered)
            recovered_report = Path(recovered["report_path"]).resolve()
            resolved_root = report_root.resolve()
            self.assertTrue(
                recovered_report == resolved_root or resolved_root in recovered_report.parents
            )
            self.assertNotEqual(recovered_report, outside_report.resolve())


if __name__ == "__main__":
    unittest.main()
