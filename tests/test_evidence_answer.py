from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from agent.llm_client import build_chat_messages, build_general_chat_messages
from agent.orchestrator import (
    PROCESSING_FLOW_START,
    append_used_reference_index,
    build_evidence_grounded_fallback,
    build_previous_evidence_answer,
    compact_primary_answer,
    run_analysis_turn,
)
from agent.report import build_processing_plan
from agent.rules import DIRECTION_PEEL_PECTIN, ScoreResult
from agent.tools import build_retrieval_specs


class FocusedRetrievalTests(unittest.TestCase):
    def test_user_question_is_the_first_retrieval_facet(self) -> None:
        batch = {"origin": "新会", "variety": "茶枝柑", "customer_type": "食品加工厂"}
        specs = build_retrieval_specs(batch, "这批果皮做果胶要关注哪些提取条件？")
        self.assertIn("果胶要关注哪些提取条件", str(specs[0]["query"]))
        self.assertEqual(specs[0]["category"], "果胶")
        self.assertGreaterEqual(len(specs), 9)


class EvidenceAnswerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.batch = {
            "batch_id": "TEST-EVIDENCE",
            "origin": "新会",
            "variety": "茶枝柑",
            "harvest_date": "",
            "weight_kg": 500,
            "brix": 10.5,
            "acidity": "",
            "moisture": 18,
            "customer_type": "食品加工厂",
            "pesticide": None,
            "heavy_metal": None,
            "microbe": None,
            "aflatoxin": None,
        }
        self.evidence = [
            {
                "chunk_id": "pectin-1",
                "document_id": "pectin-paper",
                "title": "Extraction of pectin from citrus peel",
                "year": "2025",
                "category": "果胶",
                "section": "结果与讨论",
                "page": 6,
                "doi": "10.1000/pectin",
                "chunk_text": "Extraction conditions changed yield and degree of esterification.",
                "match_score": 88,
            }
        ]

    def test_model_prompts_reserve_reference_metadata_for_the_collapsed_panel(self) -> None:
        general_prompt = build_general_chat_messages(
            [],
            "陈皮陈化要注意什么？",
            evidence=self.evidence,
        )[0]["content"]
        analysis_prompt = build_chat_messages(
            {"batch": self.batch, "evidence": self.evidence},
            [],
            "这批原料怎么处理？",
        )[0]["content"]

        self.assertIn("最多 3 条", general_prompt)
        self.assertIn("折叠文献区", general_prompt)
        self.assertIn("280～500", analysis_prompt)
        self.assertIn("不得出现“[文献N]”", analysis_prompt)
        self.assertNotIn("答案末尾增加“本次引用文献”", general_prompt)

    def test_reference_details_are_removed_from_the_primary_answer(self) -> None:
        answer = append_used_reference_index("该判断由提取研究支持[文献1]。", self.evidence)
        self.assertEqual(answer, "该判断由提取研究支持。")
        self.assertNotIn("本次引用文献", answer)
        self.assertNotIn("第6页", answer)

    def test_compactor_drops_a_model_bibliography_and_caps_runaway_prose(self) -> None:
        raw = (
            "建议先做果胶提取小试[文献1]。\n\n"
            + "重点核对原料含水率与提取稳定性。" * 80
            + "\n\n### 本次引用文献\n\n"
            + "- [文献1] Extraction of pectin（2025；第6页；DOI 10.1000/pectin）"
        )

        answer = compact_primary_answer(raw)

        self.assertLessEqual(len(answer), 600)
        self.assertNotIn("[文献1]", answer)
        self.assertNotIn("本次引用文献", answer)
        self.assertNotIn("10.1000/pectin", answer)

    def test_compactor_keeps_an_ordinary_sentence_about_evidence(self) -> None:
        raw = "文献证据显示提取条件会影响得率[文献1、文献2]。下一步先做小试。"

        answer = compact_primary_answer(raw)

        self.assertEqual(answer, "文献证据显示提取条件会影响得率。下一步先做小试。")

    def test_explicit_previous_reference_request_can_still_return_source_details(self) -> None:
        answer = build_previous_evidence_answer(
            {"answer": "建议先做果胶提取小试。", "evidence": self.evidence}
        )

        self.assertIn("Extraction of pectin", answer)
        self.assertIn("第6页", answer)
        self.assertIn("10.1000/pectin", answer)

    def test_local_fallback_keeps_evidence_out_of_the_primary_answer(self) -> None:
        score = ScoreResult(direction=DIRECTION_PEEL_PECTIN, score=82, reasons=["果皮可分流利用"])
        plan = build_processing_plan(self.batch, DIRECTION_PEEL_PECTIN, [], evidence=self.evidence)
        result = {
            "scores": [score],
            "quality_risks": [],
            "evidence": self.evidence,
            "next_actions": ["开展提取小试"],
            "processing_plan": plan,
        }

        answer = build_evidence_grounded_fallback(result, Path("TEST-EVIDENCE.md"))

        self.assertIn("推荐方向", answer)
        self.assertIn("开展提取小试", answer)
        self.assertNotIn("Extraction of pectin", answer)
        self.assertNotIn("第6页", answer)
        self.assertNotIn("完整报告", answer)

    @patch("agent.orchestrator.write_audit_event")
    @patch("agent.orchestrator.save_report", return_value=Path("TEST-EVIDENCE.md"))
    @patch("agent.orchestrator.chat_with_deepseek")
    @patch("agent.orchestrator.run_demo_agent")
    def test_batch_turn_uses_literature_answer_as_primary_answer(
        self,
        run_agent_mock,
        chat_mock,
        _save_mock,
        _audit_mock,
    ) -> None:
        score = ScoreResult(direction=DIRECTION_PEEL_PECTIN, score=82, reasons=["果皮可分流利用"])
        plan = build_processing_plan(self.batch, DIRECTION_PEEL_PECTIN, [], evidence=self.evidence)
        run_agent_mock.return_value = {
            "batch": self.batch,
            "analysis_question": "果胶路线怎么做？",
            "scores": [score],
            "quality_risks": [],
            "evidence": self.evidence,
            "next_actions": ["开展提取小试"],
            "processing_plan": plan,
            "report": "报告",
        }
        chat_mock.return_value = (
            "### 综合结论\n果胶作为候选路线，提取条件会影响得率与酯化度[文献1]。\n\n"
            "### 下一步\n开展提取小试。\n\n"
            "### 本次引用文献\n"
            "- [文献1] Extraction of pectin from citrus peel（2025；第6页；DOI 10.1000/pectin）"
        )

        payload = run_analysis_turn(
            user_prompt="新会茶枝柑，糖度10.5，水分18%，果胶路线怎么做？",
            api_key="configured-key",
            history=[],
            current_batch=self.batch,
        )

        self.assertEqual(payload["answer"].splitlines()[0], PROCESSING_FLOW_START)
        self.assertLess(payload["answer"].index("完整加工流程（方案）"), payload["answer"].index("### 综合结论"))
        self.assertNotIn("[文献1]", payload["answer"])
        self.assertNotIn("### 本次引用文献", payload["answer"])
        self.assertNotIn("第6页", payload["answer"])
        self.assertEqual(payload["result"]["evidence"], self.evidence)
        prompt = chat_mock.call_args.args[1][-1]["content"]
        self.assertIn("简明主回答", prompt)
        self.assertIn("不在正文显示引用编号", prompt)


if __name__ == "__main__":
    unittest.main()
