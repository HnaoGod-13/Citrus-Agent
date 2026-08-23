from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.llm_client import build_general_chat_messages
from agent.memory import (
    MemoryIsolationError,
    MemoryManager,
    MemoryStorageError,
    MemoryValidationError,
    estimate_tokens,
    select_recent_messages,
)


class LayeredMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "memory.db"
        self.manager = MemoryManager(self.db_path)
        self.user_id = "user_a"
        self.project_id = "project_a"
        self.session_id = "session_a"
        self.manager.ensure_session(self.user_id, self.session_id, self.project_id)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_recent_window_is_token_bounded_and_keeps_critical_recent_items(self) -> None:
        messages = [
            {"role": "system", "content": "系统规则" * 300},
            {"role": "user", "content": "早期问题" * 300},
            {"role": "tool", "content": "工具结果" * 300, "message_type": "tool_result"},
            {"role": "assistant", "content": "上一轮图片识别为甜橙，具体品系仍需产地信息确认。"},
            {"role": "user", "content": "这个品种适合怎样加工？"},
        ]
        selected = select_recent_messages(messages, token_budget=400)
        joined = "\n".join(item["content"] for item in selected)
        self.assertLessEqual(sum(estimate_tokens(item["content"]) for item in selected), 400)
        self.assertIn("系统规则", joined)
        self.assertIn("工具结果", joined)
        self.assertIn("上一轮图片识别为甜橙", joined)
        self.assertIn("这个品种适合怎样加工", joined)

    def test_working_memory_validates_fields_supports_set_and_survives_restart(self) -> None:
        state = self.manager.update_working_memory(
            self.session_id,
            {
                "current_goal": "分析甜橙加工路线",
                "entities": {"variety": "甜橙", "origin": "赣南"},
                "required_inputs": {"set": ["糖度", "酸度"]},
                "confirmed_decisions": {"add": ["先做 NFC 小试"]},
            },
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.assertEqual(state["entities"]["variety"], "甜橙")
        self.assertEqual(state["required_inputs"], ["糖度", "酸度"])
        state = self.manager.update_working_memory(
            self.session_id,
            {"required_inputs": {"set": []}},
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.assertEqual(state["required_inputs"], [])

        restarted = MemoryManager(self.db_path)
        restored = restarted.load_working_memory(self.user_id, self.session_id, self.project_id)
        self.assertEqual(restored["entities"]["variety"], "甜橙")
        self.assertIn("先做 NFC 小试", restored["confirmed_decisions"])
        with self.assertRaises(MemoryValidationError):
            restarted.update_working_memory(
                self.session_id,
                {"untrusted_full_state": "overwrite"},
                user_id=self.user_id,
                project_id=self.project_id,
            )
        with self.assertRaises(MemoryIsolationError):
            restarted.load_working_memory("another_user", self.session_id, self.project_id)

    def test_incremental_summary_preserves_decisions_and_only_adds_new_messages(self) -> None:
        self.manager.update_working_memory(
            self.session_id,
            {
                "current_goal": "制定甜橙果汁试产方案",
                "confirmed_decisions": {"add": ["首轮采用 NFC 小试，不直接量产"]},
                "constraints": {"set": ["必须等待农残检测"]},
            },
            user_id=self.user_id,
            project_id=self.project_id,
        )
        for index in range(100):
            self.manager.record_message(
                self.user_id,
                self.session_id,
                self.project_id,
                "user" if index % 2 == 0 else "assistant",
                f"第{index}轮甜橙试验记录，糖度为{10 + index / 10:.1f} Brix。"
                + "同时记录酸度、产地、成熟度、加工目标和小试约束。" * 8,
            )
        first = self.manager.summarize_history(
            self.session_id,
            user_id=self.user_id,
            project_id=self.project_id,
            force=True,
        )
        self.assertIn("首轮采用 NFC 小试", first["summary"])
        first_cursor = first["summarized_through_id"]
        self.manager.record_message(
            self.user_id,
            self.session_id,
            self.project_id,
            "user",
            "新增结论：酸度0.7，仅作为当前实验记录。",
        )
        for index in range(20):
            self.manager.record_message(
                self.user_id,
                self.session_id,
                self.project_id,
                "assistant",
                f"后续第{index}条阶段记录。" + "继续核对糖酸比、杀菌条件和包装稳定性。" * 10,
            )
        second = self.manager.summarize_history(
            self.session_id,
            user_id=self.user_id,
            project_id=self.project_id,
            force=True,
        )
        self.assertGreater(second["summarized_through_id"], first_cursor)
        self.assertIn("首轮采用 NFC 小试", second["summary"])
        self.assertIn("酸度0.7", second["summary"])

    def _memory(self, content: str, *, confirmed: bool, source_id: str) -> dict:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "memory_type": "project_decision",
            "content": content,
            "keywords": ["包装", "容量"],
            "importance": 8,
            "source": "user_confirmed" if confirmed else "agent_inference",
            "source_id": source_id,
            "metadata": {
                "conflict_key": "project_decision:package_size",
                "confirmed": confirmed,
            },
        }

    def test_long_term_dedup_and_confirmed_conflict_supersedes_without_silent_overwrite(self) -> None:
        first = self.manager.save_memory(self._memory("包装规格为250毫升。", confirmed=True, source_id="one"))
        duplicate = self.manager.save_memory(self._memory("包装规格为250毫升。", confirmed=True, source_id="dup"))
        self.assertEqual(first["memory_id"], duplicate["memory_id"])
        self.assertTrue(duplicate["deduplicated"])

        unconfirmed = self.manager.save_memory(
            self._memory("模型推测包装规格为330毫升。", confirmed=False, source_id="two")
        )
        connection = sqlite3.connect(self.db_path)
        try:
            statuses = dict(connection.execute("SELECT memory_id,status FROM memories").fetchall())
        finally:
            connection.close()
        self.assertEqual(statuses[first["memory_id"]], "active")
        self.assertEqual(statuses[unconfirmed["memory_id"]], "active")

        confirmed = self.manager.save_memory(
            self._memory("用户最新确认包装规格为500毫升。", confirmed=True, source_id="three")
        )
        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute(
                "SELECT memory_id,status,superseded_by FROM memories WHERE memory_id IN (?,?,?)",
                (first["memory_id"], unconfirmed["memory_id"], confirmed["memory_id"]),
            ).fetchall()
        finally:
            connection.close()
        status_map = {row[0]: (row[1], row[2]) for row in rows}
        self.assertEqual(status_map[first["memory_id"]], ("superseded", confirmed["memory_id"]))
        self.assertEqual(status_map[unconfirmed["memory_id"]], ("superseded", confirmed["memory_id"]))
        self.assertEqual(status_map[confirmed["memory_id"]][0], "active")

    def test_memory_and_sample_retrieval_are_relevant_and_isolated(self) -> None:
        self.manager.save_memory(
            {
                "user_id": self.user_id,
                "session_id": self.session_id,
                "project_id": self.project_id,
                "memory_type": "experiment_parameter",
                "content": "赣南脐橙NFC小试糖度为12.2 Brix，酸度0.7。",
                "keywords": ["赣南", "脐橙", "NFC", "糖度"],
                "importance": 8,
                "source": "experiment",
                "source_id": "exp-1",
            }
        )
        sample = self.manager.save_sample(
            {
                "user_id": self.user_id,
                "session_id": self.session_id,
                "project_id": self.project_id,
                "variety": "脐橙",
                "origin": "赣南",
                "time": "2026-01-10",
                "maturity": "成熟",
                "processing_goal": "NFC橙汁",
                "metrics": {"brix": 12.2, "acidity": 0.7},
                "solution": "清洗、分选、榨汁、低温杀菌和无菌灌装小试。",
                "outcome": "小试稳定，尚未量产验证。",
                "source": "verified_sample",
                "confidence": 0.9,
            }
        )
        found = self.manager.search_memories(
            "赣南脐橙NFC糖度参数",
            {"user_id": self.user_id, "project_id": self.project_id},
            5,
        )
        self.assertTrue(found)
        unrelated = self.manager.search_memories(
            "柠檬溃疡病叶片症状",
            {"user_id": self.user_id, "project_id": self.project_id},
            5,
        )
        self.assertEqual(unrelated, [])
        similar = self.manager.retrieve_similar_samples(
            {
                "user_id": self.user_id,
                "project_id": self.project_id,
                "query": "赣南脐橙适合做NFC吗",
                "variety": "脐橙",
                "origin": "赣南",
                "processing_goal": "NFC橙汁",
            },
            3,
        )
        self.assertEqual(similar[0]["sample_id"], sample["sample_id"])

        other_session = "session_b"
        self.manager.ensure_session("user_b", other_session, self.project_id)
        self.assertEqual(
            self.manager.search_memories(
                "赣南脐橙NFC",
                {"user_id": "user_b", "project_id": self.project_id},
                5,
            ),
            [],
        )
        self.assertEqual(
            self.manager.retrieve_similar_samples(
                {"user_id": "user_b", "project_id": self.project_id, "query": "赣南脐橙NFC"},
                3,
            ),
            [],
        )
        self.manager.ensure_session(self.user_id, "session_project_b", "project_b")
        self.assertEqual(
            self.manager.search_memories(
                "赣南脐橙NFC",
                {"user_id": self.user_id, "project_id": "project_b"},
                5,
            ),
            [],
        )

    def test_identical_samples_from_different_users_have_scoped_ids(self) -> None:
        common = {
            "project_id": self.project_id,
            "variety": "脐橙",
            "origin": "赣南",
            "processing_goal": "NFC橙汁",
            "metrics": {"brix": 12.2, "acidity": 0.7},
            "solution": "清洗、榨汁、杀菌和灌装。",
            "outcome": "待小试验证。",
            "source": "agent_analysis_pending",
        }
        first = self.manager.save_sample(
            {**common, "user_id": self.user_id, "session_id": self.session_id}
        )
        duplicate = self.manager.save_sample(
            {**common, "user_id": self.user_id, "session_id": self.session_id}
        )
        self.manager.ensure_session("user_b", "session_b", self.project_id)
        second_user = self.manager.save_sample(
            {**common, "user_id": "user_b", "session_id": "session_b"}
        )

        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(first["sample_id"], duplicate["sample_id"])
        self.assertNotEqual(first["sample_id"], second_user["sample_id"])
        self.assertEqual(
            self.manager.retrieve_similar_samples(
                {"user_id": self.user_id, "project_id": "project_b", "query": "赣南脐橙NFC"},
                3,
            ),
            [],
        )

    def test_concurrent_duplicate_sample_writes_are_atomic(self) -> None:
        second_manager = MemoryManager(self.db_path)
        common = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "variety": "脐橙",
            "origin": "赣南",
            "processing_goal": "NFC橙汁",
            "solution": "清洗、榨汁、杀菌和灌装。",
            "source": "agent_analysis_pending",
        }

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda manager: manager.save_sample(dict(common)),
                    (self.manager, second_manager),
                )
            )

        self.assertEqual(results[0]["sample_id"], results[1]["sample_id"])
        self.assertEqual(sum(bool(result.get("deduplicated")) for result in results), 1)
        with self.manager._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM citrus_samples WHERE sample_id=?",
                (results[0]["sample_id"],),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_context_manifest_audit_redaction_and_restart_message_recovery(self) -> None:
        self.manager.ensure_session(
            self.user_id,
            self.session_id,
            self.project_id,
            config={"company": "示例柑橘企业", "answer_style": "专业且有依据"},
        )
        self.manager.update_working_memory(
            self.session_id,
            {"entities": {"variety": "甜橙"}, "current_goal": "继续分析上一张图片中的品种"},
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.manager.record_message(
            self.user_id,
            self.session_id,
            self.project_id,
            "user",
            "这是当前样本，品种是甜橙。",
            message_id="msg-user",
        )
        self.manager.record_message(
            self.user_id,
            self.session_id,
            self.project_id,
            "assistant",
            "已识别为甜橙大类。",
            message_id="msg-assistant",
        )
        context = self.manager.load_context(
            self.user_id,
            self.session_id,
            self.project_id,
            "这个品种适合怎样加工",
        )
        self.assertIn("示例柑橘企业", context["context_sections"]["profile"])
        for section, usage in context["token_usage"].items():
            if section != "current_input":
                self.assertLessEqual(usage, context["token_budgets"][section])
        model_messages = build_general_chat_messages(
            [],
            "这个品种适合怎样加工？",
            memory_context=context,
            evidence=[],
        )
        model_context = "\n".join(item["content"] for item in model_messages)
        self.assertIn("甜橙", model_context)
        self.assertIn("已识别为甜橙大类", model_context)
        run_id = self.manager.log_agent_run(
            {
                "run_id": "run-redaction",
                "user_id": self.user_id,
                "session_id": self.session_id,
                "project_id": self.project_id,
                "original_input": "使用 sk-1234567890SECRET 调试",
                "system_prompt_version": "test-v1",
                "model_name": "test-model",
                "context_manifest": context["manifest"],
                "retrieved_memory_ids": ["mem-1"],
                "retrieved_literature_ids": ["lit-1"],
                "retrieved_sample_ids": ["sample-1"],
                "tool_calls": [{"tool": "demo", "parameters": {"api_key": "do-not-log"}}],
                "model_raw_output": "raw",
                "final_output": "final",
                "state_updates": {"current_goal": "demo"},
            }
        )
        record = self.manager.get_agent_run(
            run_id,
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.assertNotIn("sk-1234567890SECRET", record["original_input"])
        self.assertEqual(record["tool_calls"][0]["parameters"]["api_key"], "[REDACTED]")
        self.assertEqual(record["retrieved_literature_ids"], ["lit-1"])

        restarted = MemoryManager(self.db_path)
        messages = restarted.restore_session_messages(self.user_id, self.session_id, self.project_id)
        self.assertEqual([item["message_id"] for item in messages], ["msg-user", "msg-assistant"])

    def test_opaque_resume_grant_is_hashed_scoped_expiring_and_revocable(self) -> None:
        token = self.manager.create_session_access_grant(
            self.user_id,
            self.session_id,
            self.project_id,
            ttl_hours=2,
        )
        self.assertRegex(token, r"^ctx_[A-Za-z0-9_-]{32,96}$")
        with self.manager._connect() as connection:
            row = connection.execute(
                "SELECT token_hash,revoked_at FROM session_access_grants"
            ).fetchone()
        self.assertEqual(hashlib.sha256(token.encode("utf-8")).hexdigest(), row["token_hash"])
        self.assertNotEqual(token, row["token_hash"])
        self.assertIsNone(row["revoked_at"])

        resolved = self.manager.resolve_session_access_grant(
            token,
            project_id=self.project_id,
        )
        self.assertEqual(self.user_id, resolved["user_id"])
        self.assertEqual(self.session_id, resolved["session_id"])
        self.assertIsNone(
            self.manager.resolve_session_access_grant(token, project_id="another_project")
        )
        self.assertFalse(
            self.manager.revoke_session_access_grant(
                token,
                user_id="another_user",
                session_id=self.session_id,
                project_id=self.project_id,
            )
        )
        self.assertTrue(
            self.manager.revoke_session_access_grant(
                token,
                user_id=self.user_id,
                session_id=self.session_id,
                project_id=self.project_id,
            )
        )
        self.assertIsNone(
            self.manager.resolve_session_access_grant(token, project_id=self.project_id)
        )

        expired = self.manager.create_session_access_grant(
            self.user_id,
            self.session_id,
            self.project_id,
        )
        with self.manager._connect() as connection:
            connection.execute(
                "UPDATE session_access_grants SET expires_at=? WHERE token_hash=?",
                (
                    "2000-01-01T00:00:00+00:00",
                    hashlib.sha256(expired.encode("utf-8")).hexdigest(),
                ),
            )
        self.assertIsNone(
            self.manager.resolve_session_access_grant(expired, project_id=self.project_id)
        )
        with self.manager._connect() as connection:
            revoked_at = connection.execute(
                "SELECT revoked_at FROM session_access_grants WHERE token_hash=?",
                (hashlib.sha256(expired.encode("utf-8")).hexdigest(),),
            ).fetchone()[0]
        self.assertTrue(revoked_at)

    def test_export_is_exactly_scoped_redacted_and_never_contains_grant_hashes(self) -> None:
        self.manager.record_message(
            self.user_id,
            self.session_id,
            self.project_id,
            "user",
            "请使用 api_key=super-secret-value 调试。",
        )
        token = self.manager.create_session_access_grant(
            self.user_id,
            self.session_id,
            self.project_id,
        )
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.manager.log_privacy_event(
            "data_exported",
            user_id=self.user_id,
            project_id=self.project_id,
            session_id=self.session_id,
            details={"api_key": "must-not-export"},
        )
        self.manager.ensure_session("user_b", "session_b", self.project_id)
        self.manager.record_message(
            "user_b",
            "session_b",
            self.project_id,
            "user",
            "other user's private message",
        )

        exported = self.manager.export_user_data(
            user_id=self.user_id,
            project_id=self.project_id,
        )
        payload = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("super-secret-value", payload)
        self.assertNotIn("must-not-export", payload)
        self.assertNotIn("other user's private message", payload)
        self.assertNotIn(token, payload)
        self.assertNotIn(token_hash, payload)
        self.assertEqual(
            [self.session_id],
            [row["session_id"] for row in exported["data"]["sessions"]],
        )
        self.assertEqual(
            "[REDACTED]",
            exported["data"]["access_records"][0]["details"]["api_key"],
        )

    def test_export_replaces_nested_server_paths_with_portable_logical_references(self) -> None:
        working_path = r"C:\Users\service-account\citrus\batch-notes.md"
        metadata_path = "/srv/citrus/private/uploads/photo.jpg"
        sample_path = r"\\fileserver\citrus-private\sample.png"
        run_state_path = "/var/lib/citrus/private/tool-result.json"
        run_tool_path = r"D:\Citrus Runtime\reports\decision-report.md"
        self.manager.update_working_memory(
            self.session_id,
            {"referenced_files": {"add": [working_path]}},
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.manager.record_message(
            self.user_id,
            self.session_id,
            self.project_id,
            "assistant",
            "图片已保存。",
            metadata={"stored_image_path": metadata_path},
        )
        self.manager.save_sample(
            {
                "user_id": self.user_id,
                "session_id": self.session_id,
                "project_id": self.project_id,
                "variety": "path-export-test",
                "image_paths": [sample_path],
                "source": "test",
            }
        )
        self.manager.log_agent_run(
            {
                "run_id": "run-portable-export",
                "user_id": self.user_id,
                "session_id": self.session_id,
                "project_id": self.project_id,
                "original_input": "生成报告",
                "system_prompt_version": "test-v1",
                "tool_calls": [{"tool": "report", "result_path": run_tool_path}],
                "state_updates": {"referenced_files": {"add": [run_state_path]}},
            }
        )

        exported = self.manager.export_user_data(
            user_id=self.user_id,
            project_id=self.project_id,
        )
        payload = json.dumps(exported, ensure_ascii=False)
        for raw_path in (
            working_path,
            metadata_path,
            sample_path,
            run_state_path,
            run_tool_path,
        ):
            self.assertNotIn(raw_path, payload)

        working_ref = exported["data"]["working_memory"][0]["state"]["referenced_files"][0]
        metadata_ref = exported["data"]["conversation_messages"][0]["metadata"][
            "stored_image_path"
        ]
        sample_ref = exported["data"]["citrus_samples"][0]["image_paths"][0]
        run_record = exported["data"]["agent_runs"][0]
        state_ref = run_record["state_updates"]["referenced_files"]["add"][0]
        tool_ref = run_record["tool_calls"][0]["result_path"]
        for logical_ref, basename in (
            (working_ref, "batch-notes.md"),
            (metadata_ref, "photo.jpg"),
            (sample_ref, "sample.png"),
            (state_ref, "tool-result.json"),
            (tool_ref, "decision-report.md"),
        ):
            self.assertRegex(logical_ref, r"^stored-file://[0-9a-f]{12}/")
            self.assertTrue(logical_ref.endswith("/" + basename))

    def test_exact_session_and_user_deletion_preserve_other_scopes(self) -> None:
        def populate(user_id: str, session_id: str, project_id: str, suffix: str) -> str:
            self.manager.ensure_session(user_id, session_id, project_id)
            self.manager.record_message(
                user_id,
                session_id,
                project_id,
                "user",
                f"message-{suffix}",
            )
            self.manager.save_memory(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "project_id": project_id,
                    "memory_type": "task_event",
                    "content": f"memory-{suffix}",
                    "source": "test",
                    "source_id": suffix,
                }
            )
            self.manager.save_sample(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "project_id": project_id,
                    "variety": f"variety-{suffix}",
                    "source": "test",
                }
            )
            self.manager.log_agent_run(
                {
                    "run_id": f"run-{suffix}",
                    "user_id": user_id,
                    "session_id": session_id,
                    "project_id": project_id,
                    "original_input": f"run-input-{suffix}",
                    "system_prompt_version": "test-v1",
                }
            )
            return self.manager.create_session_access_grant(
                user_id,
                session_id,
                project_id,
            )

        session_two = "session_two"
        other_user_session = "session_other_user"
        other_project_session = "session_other_project"
        token_one = populate(self.user_id, self.session_id, self.project_id, "one")
        token_two = populate(self.user_id, session_two, self.project_id, "two")
        token_other_user = populate("user_b", other_user_session, self.project_id, "other-user")
        token_other_project = populate(
            self.user_id,
            other_project_session,
            "project_b",
            "other-project",
        )

        with self.assertRaises(MemoryIsolationError):
            self.manager.delete_session_data(
                other_user_session,
                user_id=self.user_id,
                project_id=self.project_id,
            )

        deleted = self.manager.delete_session_data(
            self.session_id,
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.assertTrue(deleted["deleted"])
        self.assertGreater(deleted["counts"]["conversation_messages"], 0)
        self.assertIsNone(
            self.manager.resolve_session_access_grant(token_one, project_id=self.project_id)
        )
        self.assertIsNotNone(
            self.manager.resolve_session_access_grant(token_two, project_id=self.project_id)
        )

        deleted_user = self.manager.delete_user_data(
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.assertTrue(deleted_user["deleted"])
        self.assertIsNone(
            self.manager.resolve_session_access_grant(token_two, project_id=self.project_id)
        )
        self.assertIsNotNone(
            self.manager.resolve_session_access_grant(
                token_other_user,
                project_id=self.project_id,
            )
        )
        self.assertIsNotNone(
            self.manager.resolve_session_access_grant(
                token_other_project,
                project_id="project_b",
            )
        )
        with self.manager._connect() as connection:
            remaining = {
                (row["user_id"], row["project_id"], row["session_id"])
                for row in connection.execute(
                    "SELECT user_id,project_id,session_id FROM sessions"
                )
            }
        self.assertEqual(
            {
                ("user_b", self.project_id, other_user_session),
                (self.user_id, "project_b", other_project_session),
            },
            remaining,
        )

    def test_deletion_removes_only_known_files_in_the_exact_scope(self) -> None:
        scope_hash = hashlib.sha256(
            f"{self.user_id}\0{self.project_id}".encode("utf-8")
        ).hexdigest()[:24]
        image_dir = self.db_path.parent / "files" / scope_hash
        image_dir.mkdir(parents=True)
        first_image = image_dir / "first.jpg"
        second_image = image_dir / "second.jpg"
        first_image.write_bytes(b"first")
        second_image.write_bytes(b"second")
        second_session = "session_file_two"
        self.manager.ensure_session(self.user_id, second_session, self.project_id)
        self.manager.save_sample(
            {
                "user_id": self.user_id,
                "session_id": self.session_id,
                "project_id": self.project_id,
                "variety": "first-file-variety",
                "image_paths": [str(first_image)],
                "source": "test",
            }
        )
        self.manager.save_sample(
            {
                "user_id": self.user_id,
                "session_id": second_session,
                "project_id": self.project_id,
                "variety": "second-file-variety",
                "image_paths": [str(second_image)],
                "source": "test",
            }
        )

        deleted_session = self.manager.delete_session_data(
            self.session_id,
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.assertFalse(first_image.exists())
        self.assertTrue(second_image.exists())
        self.assertEqual(0, deleted_session["file_cleanup_errors"])

        deleted_user = self.manager.delete_user_data(
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.assertFalse(second_image.exists())
        self.assertFalse(image_dir.exists())
        self.assertEqual(0, deleted_user["file_cleanup_errors"])

    def test_privacy_event_scope_and_retention_policy_are_explicit(self) -> None:
        self.manager.log_privacy_event(
            "session_created",
            user_id=self.user_id,
            project_id=self.project_id,
            session_id=self.session_id,
            details={"channel": "test"},
        )
        self.manager.ensure_session("user_b", "session_b", self.project_id)
        self.manager.log_privacy_event(
            "session_created",
            user_id="user_b",
            project_id=self.project_id,
            session_id="session_b",
        )
        events = self.manager.list_privacy_events(
            user_id=self.user_id,
            project_id=self.project_id,
        )
        self.assertEqual(1, len(events))
        self.assertEqual(self.session_id, events[0]["session_id"])
        policy = self.manager.retention_policy()
        self.assertGreater(policy["resume_token_ttl_hours"], 0)
        self.assertGreater(policy["conversation_retention_days"], 0)
        self.assertGreater(policy["agent_audit_retention_days"], 0)
        self.assertGreater(policy["access_log_retention_days"], 0)
        self.assertFalse(policy["automatic_cleanup_enabled"])
        self.assertIn("不执行后台批量删除", policy["automatic_cleanup_note"])

    def test_existing_memory_database_is_upgraded_without_rewriting_sessions(self) -> None:
        legacy_path = Path(self.tempdir.name) / "legacy-memory.db"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                """
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?,?)",
                (
                    "legacy_session",
                    "legacy_user",
                    "legacy_project",
                    "active",
                    "{}",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        upgraded = MemoryManager(legacy_path)
        with upgraded._connect() as connection:
            preserved = connection.execute(
                "SELECT user_id,project_id FROM sessions WHERE session_id='legacy_session'"
            ).fetchone()
            privacy_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertEqual(("legacy_user", "legacy_project"), tuple(preserved))
        self.assertIn("session_access_grants", privacy_tables)
        self.assertIn("privacy_events", privacy_tables)
        token = upgraded.create_session_access_grant(
            "legacy_user",
            "legacy_session",
            "legacy_project",
        )
        self.assertEqual(
            "legacy_session",
            upgraded.resolve_session_access_grant(
                token,
                project_id="legacy_project",
            )["session_id"],
        )

    def test_database_failure_is_wrapped(self) -> None:
        blocked = Path(self.tempdir.name) / "is-a-directory"
        blocked.mkdir()
        with self.assertRaises(MemoryStorageError):
            MemoryManager(blocked)

    def test_record_message_retries_busy_write_and_remains_idempotent(self) -> None:
        original_connect = self.manager._connect
        connect_calls = 0

        def flaky_connect():
            nonlocal connect_calls
            connect_calls += 1
            if connect_calls == 1:
                raise sqlite3.OperationalError("database is locked")
            return original_connect()

        with (
            patch.object(self.manager, "_connect", side_effect=flaky_connect),
            patch("agent.memory.time.sleep") as sleep_mock,
        ):
            saved_id = self.manager.record_message(
                self.user_id,
                self.session_id,
                self.project_id,
                "assistant",
                "已生成的完整加工流程",
                message_id="msg_retry_once",
            )

        self.assertEqual("msg_retry_once", saved_id)
        sleep_mock.assert_called_once()
        self.manager.record_message(
            self.user_id,
            self.session_id,
            self.project_id,
            "assistant",
            "已生成的完整加工流程",
            message_id="msg_retry_once",
        )
        restored = self.manager.restore_session_messages(
            self.user_id,
            self.session_id,
            self.project_id,
        )
        self.assertEqual(
            1,
            sum(item["message_id"] == "msg_retry_once" for item in restored),
        )


class MemoryTurnFinalizationTests(unittest.TestCase):
    def test_analysis_without_uploaded_image_does_not_reference_missing_variable(self) -> None:
        from app.main import finalize_memory_turn

        manager = MagicMock()
        manager.update_working_memory.return_value = {}
        manager.capture_long_term_from_turn.return_value = []
        manager.save_memory.return_value = {}
        manager.save_sample.return_value = {"sample_id": "sample-1"}

        trace = finalize_memory_turn(
            manager=manager,
            user_id="user-a",
            session_id="session-a",
            project_id="project-a",
            prompt="这批脐橙适合怎样加工成果汁？",
            assistant_message={"role": "assistant", "content": "完整加工流程"},
            assistant_text="完整加工流程",
            mode="analysis",
            memory_context={},
            missing_inputs=[],
            result={
                "batch": {"batch_id": "B-1", "origin": "赣南", "variety": "脐橙"},
                "scores": [{"direction": "果肉-柑橘汁/NFC", "match_level": "优先评估"}],
                "processing_plan": {},
            },
            payload={},
        )

        saved_sample = manager.save_sample.call_args.args[0]
        self.assertEqual(saved_sample["image_paths"], [])
        self.assertEqual(trace["sample_ids"], ["sample-1"])

    def test_sample_integrity_error_is_audit_warning_not_page_failure(self) -> None:
        from app.main import finalize_memory_turn

        manager = MagicMock()
        manager.update_working_memory.return_value = {}
        manager.capture_long_term_from_turn.return_value = []
        manager.save_memory.return_value = {}
        manager.save_sample.side_effect = sqlite3.IntegrityError("UNIQUE constraint failed")

        trace = finalize_memory_turn(
            manager=manager,
            user_id="user-a",
            session_id="session-a",
            project_id="project-a",
            prompt="这批脐橙适合怎样加工成果汁？",
            assistant_message={"role": "assistant", "content": "完整加工流程"},
            assistant_text="完整加工流程",
            mode="analysis",
            memory_context={},
            missing_inputs=[],
            result={
                "batch": {"batch_id": "B-1", "origin": "赣南", "variety": "脐橙"},
                "scores": [{"direction": "果肉-柑橘汁/NFC", "match_level": "优先评估"}],
                "processing_plan": {},
            },
            payload={},
        )

        self.assertIn("UNIQUE constraint failed", trace["error"])
        manager.record_message.assert_called()

    def test_assistant_write_failure_keeps_stable_message_and_warning(self) -> None:
        from app.main import finalize_memory_turn

        manager = MagicMock()
        manager.update_working_memory.return_value = {}
        manager.capture_long_term_from_turn.return_value = []
        manager.record_message.side_effect = MemoryStorageError("database is locked")
        assistant_message = {
            "role": "assistant",
            "content": "完整加工流程",
            "message_id": "msg_stable_answer",
            "run_id": "run_stable_answer",
        }

        trace = finalize_memory_turn(
            manager=manager,
            user_id="user-a",
            session_id="session-a",
            project_id="project-a",
            prompt="生成脐橙汁完整加工流程",
            assistant_message=assistant_message,
            assistant_text="完整加工流程",
            mode="chat",
            memory_context={},
            missing_inputs=[],
        )

        self.assertEqual("msg_stable_answer", assistant_message["message_id"])
        self.assertEqual("run_stable_answer", assistant_message["run_id"])
        self.assertFalse(trace["message_persisted"])
        self.assertIn("database is locked", trace["message_persistence_error"])
        self.assertIn("未能写入对话历史", assistant_message["persistence_warning"])
        self.assertFalse(assistant_message["_persistence"]["persisted"])


if __name__ == "__main__":
    unittest.main()
