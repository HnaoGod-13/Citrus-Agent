from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard

from agent import rag
from agent.llm_client import build_general_chat_messages
from agent.orchestrator import (
    build_previous_evidence_answer,
    default_batch,
    extract_batch_from_text,
    references_current_batch,
    references_previous_evidence,
)
from agent.rules import DIRECTION_PEEL_PECTIN, score_processing_options


class ConversationMemoryAndRoutingTests(unittest.TestCase):
    def test_elliptical_literature_request_uses_current_batch_and_previous_evidence(self) -> None:
        prompt = "单独把文献给我"
        self.assertTrue(references_current_batch(prompt))
        self.assertTrue(references_previous_evidence(prompt))

    @patch("agent.llm_client.retrieve_general_literature", return_value=[])
    def test_general_chat_keeps_same_conversation_history(self, _search_mock) -> None:
        history = [
            {"role": "user", "content": "上一轮问题"},
            {"role": "assistant", "content": "上一轮回答"},
        ]
        messages = build_general_chat_messages(history, "单独把文献给我")
        content = "\n".join(item["content"] for item in messages)
        self.assertIn("上一轮问题", content)
        self.assertIn("上一轮回答", content)

    def test_previous_evidence_answer_lists_only_cited_items(self) -> None:
        evidence = [
            {"title": "文献甲", "chunk_text": "甲证据"},
            {"title": "文献乙", "chunk_text": "乙证据", "doi": "10.1/test"},
            {"title": "文献丙", "chunk_text": "丙证据"},
        ]
        answer = build_previous_evidence_answer({"evidence": evidence, "answer": "结论[文献2]"})
        self.assertIn("[文献2] 文献乙", answer)
        self.assertNotIn("文献甲", answer)
        self.assertNotIn("文献丙", answer)


class InputValidationTests(unittest.TestCase):
    def test_invalid_measurements_are_rejected_and_test_semantics_are_distinguished(self) -> None:
        text = (
            "新会茶枝柑，糖度999，酸度99，水分-5%，"
            "农残检测没有超标，重金属尚未检测"
        )
        batch, _observation, notes = extract_batch_from_text(text)
        self.assertEqual(batch["brix"], "")
        self.assertEqual(batch["acidity"], "")
        self.assertEqual(batch["moisture"], "")
        self.assertIs(batch["pesticide"], True)
        self.assertEqual(batch["pesticide_status"], "passed")
        self.assertIs(batch["heavy_metal"], False)
        self.assertEqual(batch["heavy_metal_status"], "missing")
        self.assertEqual(len(notes), 3)

    def test_invalid_correction_does_not_overwrite_previous_valid_value(self) -> None:
        current = default_batch()
        current["brix"] = 10.5
        batch, _observation, notes = extract_batch_from_text("糖度改成999", current)
        self.assertEqual(batch["brix"], 10.5)
        self.assertTrue(notes)


class EvidenceAwareRankingTests(unittest.TestCase):
    def test_direct_literature_changes_route_ranking_metadata(self) -> None:
        batch = default_batch()
        batch.update({"origin": "广西", "variety": "柑橘", "customer_type": "食品加工厂"})
        evidence = [
            {
                "document_id": f"pectin-{index}",
                "title": f"柑橘果胶提取研究{index}",
                "category": "果胶",
                "chunk_text": "果胶提取、酯化度和凝胶性能。",
            }
            for index in range(3)
        ]
        without_evidence = {
            item.direction: item for item in score_processing_options(batch, "", evidence=[])
        }
        with_evidence = {
            item.direction: item for item in score_processing_options(batch, "", evidence=evidence)
        }
        self.assertEqual(
            with_evidence[DIRECTION_PEEL_PECTIN].score,
            without_evidence[DIRECTION_PEEL_PECTIN].score + 9,
        )
        self.assertEqual(with_evidence[DIRECTION_PEEL_PECTIN].evidence_count, 3)
        self.assertIn("至少3篇", with_evidence[DIRECTION_PEEL_PECTIN].evidence_support)
        self.assertNotEqual(with_evidence[DIRECTION_PEEL_PECTIN].match_level, "待评估")


class PackagedDatabaseTests(unittest.TestCase):
    def test_split_zstd_database_is_materialized_and_verified(self) -> None:
        payload = b"sqlite-test-payload" * 1000
        compressed = zstandard.ZstdCompressor(level=3).compress(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "package"
            package.mkdir()
            midpoint = len(compressed) // 2
            (package / "part001").write_bytes(compressed[:midpoint])
            (package / "part002").write_bytes(compressed[midpoint:])
            (package / "manifest.json").write_text(
                json.dumps(
                    {
                        "parts": ["part001", "part002"],
                        "original_size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            target = root / "cache" / "literature.db"
            with patch.object(rag, "LITERATURE_PACKAGE_DIR", package), patch.object(
                rag, "LITERATURE_DB_PATH", target
            ):
                self.assertTrue(rag.ensure_literature_database(target))
            self.assertEqual(target.read_bytes(), payload)

    def test_stale_cached_database_is_replaced_when_package_changes(self) -> None:
        payload = b"new-sqlite-payload" * 1000
        compressed = zstandard.ZstdCompressor(level=3).compress(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "package"
            package.mkdir()
            (package / "part001").write_bytes(compressed)
            (package / "manifest.json").write_text(
                json.dumps(
                    {
                        "parts": ["part001"],
                        "original_size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            target = root / "cache" / "literature.db"
            target.parent.mkdir()
            target.write_bytes(b"stale-database")
            with patch.object(rag, "LITERATURE_PACKAGE_DIR", package), patch.object(
                rag, "LITERATURE_DB_PATH", target
            ):
                self.assertTrue(rag.ensure_literature_database(target))
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(
                target.with_name(f"{target.name}.sha256").read_text(encoding="utf-8").strip(),
                hashlib.sha256(payload).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
