from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.memory import MemoryManager
from agent.rules import QualityRisk, ScoreResult
from agent.workflow import AgentStep
from app.main import (
    build_persisted_analysis_payload,
    restore_latest_analysis_state,
    restore_ui_messages,
)


def make_payload(batch_id: str = "B-001", with_vision: bool = True) -> dict:
    batch = {"batch_id": batch_id, "origin": "Test origin", "variety": "Orange"}
    return {
        "batch": batch,
        "result": {
            "batch": batch,
            "agent_steps": [AgentStep("retrieve", "retriever", "done", "evidence")],
            "scores": [ScoreResult("juice", 88)],
            "quality_risks": [QualityRisk("high", "microbe", "verify")],
            "evidence": [],
            "processing_plan": {},
            "parameter_groups": [],
            "parameterized_plan": {},
            "report": "# Report",
        },
        "report_path": f"outputs/reports/{batch_id}.md",
        "summary": f"Summary {batch_id}",
        "answer": f"Answer {batch_id}",
        "vision_result": (
            {
                "answer": "The candidate is Orange",
                "variety_candidate": "Orange",
                "variety_confidence": "medium",
                "_raw_model_output": "private raw output",
            }
            if with_vision
            else {}
        ),
    }


def row(
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


class AnalysisPayloadTests(unittest.TestCase):
    def test_snapshot_is_json_safe_and_sanitized(self) -> None:
        snapshot = build_persisted_analysis_payload(make_payload())
        decoded = json.loads(json.dumps(snapshot))
        self.assertIsInstance(decoded["result"]["agent_steps"][0], dict)
        self.assertIsInstance(decoded["result"]["scores"][0], dict)
        self.assertIsInstance(decoded["result"]["quality_risks"][0], dict)
        self.assertNotIn("_raw_model_output", decoded["vision_result"])

    def test_snapshot_survives_sqlite_metadata_round_trip(self) -> None:
        snapshot = build_persisted_analysis_payload(make_payload())
        with tempfile.TemporaryDirectory() as tempdir:
            manager = MemoryManager(Path(tempdir) / "memory.db")
            manager.record_message(
                "user-a",
                "session-a",
                "project-a",
                "assistant",
                snapshot["answer"],
                message_id="analysis-1",
                message_type="analysis",
                metadata={"analysis_payload": snapshot},
            )
            rows = manager.restore_session_messages("user-a", "session-a", "project-a")
        self.assertEqual(rows[0]["metadata"]["analysis_payload"], snapshot)


class AnalysisRestoreTests(unittest.TestCase):
    def test_new_analysis_restores_structured_payload(self) -> None:
        snapshot = build_persisted_analysis_payload(make_payload())
        messages = restore_ui_messages(
            [
                row(
                    "analysis-1",
                    "assistant",
                    snapshot["answer"],
                    message_type="analysis",
                    metadata={"analysis_payload": snapshot, "audit_trace": {"run_id": "run-1"}},
                )
            ]
        )
        self.assertEqual(messages[0]["kind"], "analysis")
        self.assertEqual(messages[0]["payload"], snapshot)
        self.assertEqual(messages[0]["audit_trace"]["run_id"], "run-1")

    def test_legacy_analysis_is_compact_but_keeps_history_content(self) -> None:
        content = "legacy analysis " * 1000
        messages = restore_ui_messages(
            [row("legacy-1", "assistant", content, message_type="analysis")]
        )
        self.assertEqual(messages[0]["kind"], "analysis_summary")
        self.assertEqual(messages[0]["content"], content)
        self.assertNotIn("payload", messages[0])

    def test_filters_internal_rows_and_deduplicates_ids(self) -> None:
        snapshot = build_persisted_analysis_payload(make_payload())
        analysis = row(
            "assistant-1",
            "assistant",
            snapshot["answer"],
            message_type="analysis",
            metadata={"analysis_payload": snapshot},
        )
        messages = restore_ui_messages(
            [
                row("user-1", "user", "first"),
                row("tool-1", "tool", "internal", message_type="tool_result"),
                analysis,
                dict(analysis),
                row("audit-1", "assistant", "internal", message_type="audit"),
                row("summary-1", "assistant", "internal", message_type="summary"),
                row("user-2", "user", "second"),
                row("assistant-2", "assistant", "second answer"),
            ]
        )
        self.assertEqual(
            [message["message_id"] for message in messages],
            ["user-1", "assistant-1", "user-2", "assistant-2"],
        )

    def test_latest_analysis_restores_follow_up_state(self) -> None:
        older = build_persisted_analysis_payload(make_payload("B-OLD"))
        latest = build_persisted_analysis_payload(make_payload("B-LATEST"))
        messages = restore_ui_messages(
            [
                row(
                    "analysis-old",
                    "assistant",
                    older["answer"],
                    message_type="analysis",
                    metadata={"analysis_payload": older},
                ),
                row(
                    "analysis-latest",
                    "assistant",
                    latest["answer"],
                    message_type="analysis",
                    metadata={"analysis_payload": latest},
                ),
                row("assistant-after", "assistant", "follow-up"),
            ]
        )
        batch, result, vision = restore_latest_analysis_state(messages)
        self.assertEqual(batch["batch_id"], "B-LATEST")
        self.assertEqual(result["batch"]["batch_id"], "B-LATEST")
        self.assertEqual(vision["variety_candidate"], "Orange")

    def test_no_snapshot_returns_empty_state(self) -> None:
        messages = restore_ui_messages(
            [row("legacy-1", "assistant", "legacy", message_type="analysis")]
        )
        self.assertEqual(restore_latest_analysis_state(messages), (None, None, None))


if __name__ == "__main__":
    unittest.main()
