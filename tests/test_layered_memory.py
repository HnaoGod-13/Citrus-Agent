from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual(
            self.manager.retrieve_similar_samples(
                {"user_id": self.user_id, "project_id": "project_b", "query": "赣南脐橙NFC"},
                3,
            ),
            [],
        )

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

    def test_database_failure_is_wrapped(self) -> None:
        blocked = Path(self.tempdir.name) / "is-a-directory"
        blocked.mkdir()
        with self.assertRaises(MemoryStorageError):
            MemoryManager(blocked)


if __name__ == "__main__":
    unittest.main()
