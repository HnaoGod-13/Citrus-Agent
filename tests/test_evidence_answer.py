from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from agent.orchestrator import PROCESSING_FLOW_START, append_used_reference_index, run_analysis_turn
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

    def test_reference_index_is_added_to_cited_answer(self) -> None:
        answer = append_used_reference_index("该判断由提取研究支持[文献1]。", self.evidence)
        self.assertIn("### 本次引用文献", answer)
        self.assertIn("10.1000/pectin", answer)
        self.assertIn("第6页", answer)

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
            "### 完整加工流程\n原料准入 → 分选前处理 → 提取小试 → 稳定化包装 → 成品检测与人工放行"
        )

        payload = run_analysis_turn(
            user_prompt="新会茶枝柑，糖度10.5，水分18%，果胶路线怎么做？",
            api_key="configured-key",
            history=[],
            current_batch=self.batch,
        )

        self.assertEqual(payload["answer"].splitlines()[0], PROCESSING_FLOW_START)
        self.assertLess(payload["answer"].index("完整加工流程（方案）"), payload["answer"].index("### 综合结论"))
        self.assertIn("[文献1]", payload["answer"])
        self.assertIn("### 本次引用文献", payload["answer"])
        prompt = chat_mock.call_args.args[1][-1]["content"]
        self.assertIn("完整主回答", prompt)
        self.assertIn("把检索到的文献应用到当前问题", prompt)


if __name__ == "__main__":
    unittest.main()
