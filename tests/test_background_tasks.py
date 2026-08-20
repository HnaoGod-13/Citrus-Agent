from __future__ import annotations

import inspect
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from agent.background_tasks import TaskRunner
from app import main as app_main


class SessionStateStub(dict):
    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


def wait_until_done(runner: TaskRunner, job_id: str, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = runner.snapshot(job_id)
        if snapshot is not None and snapshot.done:
            return
        time.sleep(0.01)
    raise AssertionError(f"task {job_id} did not finish")


class TaskRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = TaskRunner(max_workers=2)

    def tearDown(self) -> None:
        self.runner.shutdown()

    def test_task_continues_without_page_polling(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def target(progress):
            progress("正在检索文献")
            started.set()
            release.wait(timeout=2)
            return {"answer": "completed"}

        self.runner.submit("job_navigation", ("user", "project", "session"), target)
        self.assertTrue(started.wait(timeout=1))
        snapshot = self.runner.snapshot("job_navigation")
        self.assertIsNotNone(snapshot)
        self.assertEqual("正在检索文献", snapshot.progress)
        self.assertFalse(snapshot.done)

        release.set()
        wait_until_done(self.runner, "job_navigation")
        self.assertEqual({"answer": "completed"}, self.runner.result("job_navigation"))

    def test_only_one_active_task_is_allowed_per_conversation(self) -> None:
        release = threading.Event()

        def target(_progress):
            release.wait(timeout=2)
            return "done"

        scope = ("user", "project", "session")
        self.runner.submit("job_one", scope, target)
        with self.assertRaisesRegex(RuntimeError, "正在运行"):
            self.runner.submit("job_two", scope, target)
        release.set()
        wait_until_done(self.runner, "job_one")

    def test_rejected_executor_submission_does_not_lock_the_scope(self) -> None:
        self.runner.shutdown()

        with self.assertRaises(RuntimeError):
            self.runner.submit(
                "job_rejected",
                ("user", "project", "session"),
                lambda _progress: "never runs",
            )

        self.assertIsNone(self.runner.snapshot("job_rejected"))
        self.assertEqual("", self.runner.active_job(("user", "project", "session")))

    def test_terminal_result_is_claimed_by_exactly_one_harvester(self) -> None:
        self.runner.submit(
            "job_claim_once",
            ("user", "project", "session"),
            lambda _progress: {"answer": "done"},
        )
        wait_until_done(self.runner, "job_claim_once")

        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed = list(
                executor.map(
                    lambda _index: self.runner.claim_result("job_claim_once"),
                    range(2),
                )
            )

        leases = [item for item in claimed if item is not None]
        self.assertEqual(1, len(leases))
        self.assertEqual({"answer": "done"}, leases[0].result)
        self.assertEqual(1, sum(item is None for item in claimed))
        self.assertTrue(
            self.runner.acknowledge_result("job_claim_once", leases[0].token)
        )

    def test_unacknowledged_result_can_be_reclaimed_after_lease_expiry(self) -> None:
        self.runner.submit(
            "job_reclaim",
            ("user", "project", "session"),
            lambda _progress: "done",
        )
        wait_until_done(self.runner, "job_reclaim")

        with patch("agent.background_tasks.time.monotonic", return_value=100.0):
            first = self.runner.claim_result("job_reclaim", lease_seconds=15.0)
        with patch("agent.background_tasks.time.monotonic", return_value=110.0):
            self.assertIsNone(
                self.runner.claim_result("job_reclaim", lease_seconds=15.0)
            )
        with patch("agent.background_tasks.time.monotonic", return_value=116.0):
            recovered = self.runner.claim_result("job_reclaim", lease_seconds=15.0)

        self.assertIsNotNone(first)
        self.assertIsNotNone(recovered)
        self.assertNotEqual(first.token, recovered.token)
        self.assertTrue(
            self.runner.acknowledge_result("job_reclaim", recovered.token)
        )


class AgentJobHarvestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = TaskRunner(max_workers=1)
        self.state = SessionStateStub(
            memory_user_id="user",
            memory_project_id="project",
            memory_session_id="session",
            agent_messages=[{"role": "user", "content": "question", "message_id": "user_message"}],
            active_agent_job_id="job_harvest",
            active_agent_progress_revealed=True,
            clear_sidebar_inputs=False,
            restore_main_scroll_position=False,
        )

    def tearDown(self) -> None:
        self.runner.shutdown()

    def test_completed_result_is_harvested_exactly_once(self) -> None:
        manager = MagicMock()
        outcome = {
            "scope": ("user", "project", "session"),
            "assistant_message": {
                "role": "assistant",
                "content": "answer",
                "message_id": "assistant_message",
            },
            "state_updates": {
                "current_batch": {"batch_id": "B1"},
                "last_result": {"answer": "answer"},
            },
        }
        self.runner.submit("job_harvest", ("user", "project", "session"), lambda _progress: outcome)
        wait_until_done(self.runner, "job_harvest")

        with (
            patch.object(app_main.st, "session_state", self.state),
            patch.object(app_main, "get_agent_task_runner", return_value=self.runner),
            patch.object(app_main, "get_memory_manager", return_value=manager),
        ):
            self.assertTrue(app_main.sync_active_agent_job())
            self.assertFalse(app_main.sync_active_agent_job())

        assistant_messages = [
            item for item in self.state.agent_messages if item.get("message_id") == "assistant_message"
        ]
        self.assertEqual(1, len(assistant_messages))
        self.assertEqual({"batch_id": "B1"}, self.state.current_batch)
        self.assertEqual("", self.state.active_agent_job_id)
        self.assertTrue(self.state.restore_main_scroll_position)
        self.assertIsNotNone(self.runner.snapshot("job_harvest"))
        manager.record_message.assert_called_once()
        self.assertEqual(
            "assistant_message",
            manager.record_message.call_args.kwargs["message_id"],
        )

    def test_failed_harvest_persistence_keeps_generated_answer_and_warning(self) -> None:
        manager = MagicMock()
        manager.record_message.side_effect = app_main.agent_memory.MemoryStorageError(
            "database is locked"
        )
        outcome = {
            "scope": ("user", "project", "session"),
            "assistant_message": {
                "role": "assistant",
                "content": "已生成的完整加工流程",
                "message_id": "assistant_pending",
                "_persistence": {
                    "user_id": "user",
                    "project_id": "project",
                    "session_id": "session",
                    "role": "assistant",
                    "content": "已生成的完整加工流程",
                    "message_id": "assistant_pending",
                    "message_type": "chat",
                    "metadata": {},
                    "persisted": False,
                    "error": "worker write failed",
                },
            },
            "assistant_text": "已生成的完整加工流程",
            "mode": "chat",
            "state_updates": {},
        }
        self.runner.submit("job_harvest", ("user", "project", "session"), lambda _progress: outcome)
        wait_until_done(self.runner, "job_harvest")

        with (
            patch.object(app_main.st, "session_state", self.state),
            patch.object(app_main, "get_agent_task_runner", return_value=self.runner),
            patch.object(app_main, "get_memory_manager", return_value=manager),
        ):
            self.assertTrue(app_main.sync_active_agent_job())

        saved = [
            item for item in self.state.agent_messages
            if item.get("message_id") == "assistant_pending"
        ]
        self.assertEqual(1, len(saved))
        self.assertEqual("已生成的完整加工流程", saved[0]["content"])
        self.assertIn("未能写入对话历史", saved[0]["persistence_warning"])
        self.assertFalse(saved[0]["_persistence"]["persisted"])
        self.assertEqual("", self.state.active_agent_job_id)
        self.assertEqual("assistant_pending", self.state.pending_agent_persistence["message_id"])

    def test_pending_persistence_recovers_on_later_rerun_without_duplicate_answer(self) -> None:
        manager = MagicMock()
        manager.record_message.side_effect = [
            app_main.agent_memory.MemoryStorageError("database is locked"),
            "assistant_retry_later",
        ]
        outcome = {
            "scope": ("user", "project", "session"),
            "assistant_message": {
                "role": "assistant",
                "content": "已生成的文献证据回答",
                "message_id": "assistant_retry_later",
                "_persistence": {
                    "user_id": "user",
                    "project_id": "project",
                    "session_id": "session",
                    "role": "assistant",
                    "content": "已生成的文献证据回答",
                    "message_id": "assistant_retry_later",
                    "message_type": "chat",
                    "metadata": {},
                    "persisted": False,
                    "error": "worker write failed",
                },
            },
            "assistant_text": "已生成的文献证据回答",
            "mode": "chat",
            "state_updates": {},
        }
        self.runner.submit("job_harvest", ("user", "project", "session"), lambda _progress: outcome)
        wait_until_done(self.runner, "job_harvest")

        with (
            patch.object(app_main.st, "session_state", self.state),
            patch.object(app_main, "get_agent_task_runner", return_value=self.runner),
            patch.object(app_main, "get_memory_manager", return_value=manager),
            patch.object(app_main.time, "monotonic", return_value=100.0),
        ):
            self.assertTrue(app_main.sync_active_agent_job())

        self.assertTrue(self.state.pending_agent_persistence)
        with (
            patch.object(app_main.st, "session_state", self.state),
            patch.object(app_main, "get_agent_task_runner", return_value=self.runner),
            patch.object(app_main, "get_memory_manager", return_value=manager),
            patch.object(app_main.time, "monotonic", return_value=102.0),
        ):
            self.assertTrue(app_main.sync_active_agent_job())

        saved = [
            item for item in self.state.agent_messages
            if item.get("message_id") == "assistant_retry_later"
        ]
        self.assertEqual(1, len(saved))
        self.assertNotIn("persistence_warning", saved[0])
        self.assertTrue(saved[0]["_persistence"]["persisted"])
        self.assertEqual({}, self.state.pending_agent_persistence)
        self.assertEqual(2, manager.record_message.call_count)

    def test_sync_rejects_mismatched_outcome_scope_before_persistence(self) -> None:
        manager = MagicMock()
        outcome = {
            "scope": ("other-user", "project", "session"),
            "assistant_message": {
                "role": "assistant",
                "content": "wrong scope",
                "message_id": "assistant_wrong_scope",
            },
            "state_updates": {},
        }
        self.runner.submit("job_harvest", ("user", "project", "session"), lambda _progress: outcome)
        wait_until_done(self.runner, "job_harvest")

        with (
            patch.object(app_main.st, "session_state", self.state),
            patch.object(app_main, "get_agent_task_runner", return_value=self.runner),
            patch.object(app_main, "get_memory_manager", return_value=manager),
        ):
            self.assertFalse(app_main.sync_active_agent_job())

        manager.record_message.assert_not_called()
        self.assertNotIn(
            "assistant_wrong_scope",
            {item.get("message_id") for item in self.state.agent_messages},
        )

    def test_worker_returns_generated_answer_when_memory_manager_cannot_open(self) -> None:
        request = {
            "prompt": "请给出脐橙汁完整加工流程",
            "resolved_prompt": "请给出脐橙汁完整加工流程",
            "user_id": "user",
            "project_id": "project",
            "session_id": "session",
            "history": [],
        }
        with (
            patch.object(app_main.orchestrator, "should_request_batch_data", return_value=False),
            patch.object(app_main, "run_general_turn", return_value=("完整加工流程正文", {})),
            patch.object(
                app_main.agent_memory,
                "MemoryManager",
                side_effect=app_main.agent_memory.MemoryStorageError("database is locked"),
            ),
        ):
            outcome = app_main._execute_agent_job(request, lambda _message: None)

        assistant = outcome["assistant_message"]
        self.assertEqual("完整加工流程正文", assistant["content"])
        self.assertIn("未能写入对话历史", assistant["persistence_warning"])
        self.assertFalse(outcome["message_persistence"]["persisted"])

    def test_result_from_another_session_is_not_added_to_current_chat(self) -> None:
        outcome = {
            "scope": ("user", "project", "old_session"),
            "assistant_message": {
                "role": "assistant",
                "content": "old answer",
                "message_id": "old_assistant",
            },
            "state_updates": {},
        }

        with patch.object(app_main.st, "session_state", self.state):
            self.assertFalse(app_main._append_agent_job_outcome(outcome))
        self.assertNotIn("old_assistant", {item.get("message_id") for item in self.state.agent_messages})

    def test_worker_has_no_streamlit_rendering_or_session_access(self) -> None:
        source = inspect.getsource(app_main._execute_agent_job)
        self.assertNotIn("st.session_state", source)
        self.assertNotIn("render_agent_progress", source)
        self.assertIn("finalize_memory_turn(", source)


class BackgroundNavigationWiringTests(unittest.TestCase):
    def test_navigation_stays_available_while_chat_input_is_disabled(self) -> None:
        source = inspect.getsource(app_main.main)
        self.assertEqual(1, source.count("render_agent_job_monitor(active_view)"))
        self.assertIn("ui_product_pages.render_product_page(active_view)", source)
        self.assertIn('st.session_state.get("pending_agent_persistence")', source)
        self.assertIn("active_job is not None", source)


class DeepRetrievalBackgroundWiringTests(unittest.TestCase):
    def test_mode_defaults_to_quick_and_invalid_values_are_normalized(self) -> None:
        self.assertEqual("quick", app_main.normalize_retrieval_mode(None))
        self.assertEqual("quick", app_main.normalize_retrieval_mode("invalid"))
        self.assertEqual("deep", app_main.normalize_retrieval_mode(" DEEP "))

    def test_submission_freezes_mode_in_an_immutable_request(self) -> None:
        source = inspect.getsource(app_main.handle_prompt)

        self.assertIn("submitted_retrieval_mode = normalize_retrieval_mode", source)
        self.assertIn("request = MappingProxyType({", source)
        self.assertIn('"retrieval_mode": submitted_retrieval_mode', source)
        self.assertIn(
            "st.session_state.active_agent_retrieval_mode = submitted_retrieval_mode",
            source,
        )
        self.assertIn("lambda callback: _execute_agent_job(request, callback)", source)

    def test_worker_forwards_frozen_mode_to_both_answer_paths(self) -> None:
        source = inspect.getsource(app_main._execute_agent_job)

        self.assertIn(
            'retrieval_mode = normalize_retrieval_mode(request.get("retrieval_mode"))',
            source,
        )
        self.assertGreaterEqual(source.count("retrieval_mode=retrieval_mode"), 2)
        self.assertIn("正在扫描全库文献", source)
        self.assertIn("正在扫描全库文献并组织回答", source)

    def test_general_deep_mode_uses_larger_evidence_budget_and_context_mode(self) -> None:
        source = inspect.getsource(app_main.run_general_turn)

        self.assertIn('top_k=24 if normalized_mode == "deep" else 10', source)
        self.assertIn("retrieval_mode=normalized_mode", source)

    def test_general_deep_mode_carries_statistics_into_the_answer_trace(self) -> None:
        stats = {
            "retrieval_mode": "deep",
            "library_document_count": 17300,
            "selected_count": 1,
        }
        evidence = [{"chunk_id": "chunk-1", "chunk_text": "evidence"}]
        with (
            patch.object(
                app_main,
                "retrieve_general_literature",
                return_value={"evidence": evidence, "deep_retrieval_stats": stats},
            ) as retrieve,
            patch.object(
                app_main,
                "build_general_chat_messages",
                return_value=[{"role": "user", "content": "question"}],
            ) as build_messages,
            patch.object(app_main, "chat_with_deepseek", return_value="answer"),
        ):
            answer, trace = app_main.run_general_turn(
                "question",
                "api-key",
                [],
                retrieval_mode="deep",
            )

        self.assertEqual("answer", answer)
        self.assertEqual(stats, trace["deep_retrieval_stats"])
        self.assertEqual("evidence", trace["evidence"][0]["chunk_text"])
        self.assertEqual(24, retrieve.call_args.kwargs["top_k"])
        self.assertEqual("deep", retrieve.call_args.kwargs["retrieval_mode"])
        self.assertEqual("deep", build_messages.call_args.kwargs["retrieval_mode"])

    def test_general_local_fallback_keeps_reference_details_out_of_main_answer(self) -> None:
        evidence = [
            {
                "title": "Citrus source",
                "year": 2026,
                "page": 12,
                "doi": "10.1000/citrus",
                "chunk_text": "原文证据片段",
            }
        ]
        with patch.object(
            app_main,
            "retrieve_general_literature",
            return_value={"evidence": evidence, "deep_retrieval_stats": {}},
        ):
            answer, trace = app_main.run_general_turn("柑橘加工", "", [])

        self.assertIn("参考依据", answer)
        self.assertNotIn("Citrus source", answer)
        self.assertNotIn("第12页", answer)
        self.assertEqual("Citrus source", trace["evidence"][0]["title"])

    def test_background_monitor_uses_active_job_mode_not_live_sidebar_mode(self) -> None:
        source = inspect.getsource(app_main.render_agent_job_monitor)

        self.assertIn("active_agent_retrieval_mode", source)
        self.assertNotIn('session_state.get("retrieval_mode")', source)


if __name__ == "__main__":
    unittest.main()
