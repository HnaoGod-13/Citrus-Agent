from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from agent.llm_client import build_analysis_context, build_general_chat_messages
from agent.orchestrator import (
    PROCESSING_FLOW_START,
    ensure_primary_processing_flow,
    strip_primary_processing_flow,
    summarize_result,
)
from agent.report import build_processing_plan, processing_flow
from agent.rules import ALL_DIRECTIONS, DIRECTION_JUICE, QualityRisk, ScoreResult
from agent.tools import retrieve_literature, retrieve_processing_parameters, write_report
from agent.workflow import _merge_retrieval_stats


class ProcessingPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.batch = {
            "batch_id": "DEMO-001",
            "origin": "赣南",
            "variety": "脐橙",
            "harvest_date": "",
            "weight_kg": 1200,
            "brix": 12.2,
            "acidity": 0.7,
            "moisture": None,
            "customer_type": "食品加工厂",
            "pesticide": None,
            "heavy_metal": None,
            "microbe": None,
            "aflatoxin": None,
        }

    def test_every_scored_direction_has_a_complete_five_stage_plan(self) -> None:
        for direction in ALL_DIRECTIONS:
            with self.subTest(direction=direction):
                plan = build_processing_plan(self.batch, direction, [])
                self.assertEqual(plan["flow"], processing_flow(direction))
                self.assertEqual(len(plan["stages"]), 5)
                self.assertTrue(plan["product_form"])
                self.assertTrue(plan["pilot_parameters"])
                self.assertTrue(plan["release_checks"])

    def test_plan_uses_current_batch_data_and_marks_missing_evidence(self) -> None:
        plan = build_processing_plan(
            self.batch,
            DIRECTION_JUICE,
            [
                QualityRisk(
                    level="中",
                    item="检测资料不完整",
                    suggestion="补齐检测后再放行。",
                )
            ],
            "果皮完整，未见明显霉斑",
        )
        basis_text = "；".join(plan["basis"])
        self.assertIn("赣南", basis_text)
        self.assertIn("糖度：12.2", basis_text)
        self.assertIn("果皮完整", basis_text)
        self.assertIn("真实文献", "；".join(plan["missing_data"]))
        self.assertIn("检测资料不完整", "；".join(plan["risk_controls"]))

    def test_report_tool_returns_the_same_plan_used_in_markdown(self) -> None:
        result = write_report(
            self.batch,
            "果皮完整，未见明显霉斑",
            [],
            [ScoreResult(direction=DIRECTION_JUICE, score=82, reasons=["演示评分"])],
            [],
        )
        plan = result.data["processing_plan"]
        report = result.data["report"]
        self.assertEqual(plan["direction"], DIRECTION_JUICE)
        self.assertIn("## 5. 完整加工流程（方案）", report)
        self.assertIn("### 5.2 分阶段执行方案", report)
        self.assertIn("核心加工与小试定参", report)
        self.assertIn("待小试、文献与企业 SOP 复核", report)

    def test_answer_places_the_complete_flow_immediately_after_recommendation(self) -> None:
        plan = build_processing_plan(self.batch, DIRECTION_JUICE, [])
        result = {
            "scores": [ScoreResult(direction=DIRECTION_JUICE, score=82, reasons=["演示评分"])],
            "quality_risks": [],
            "evidence": [],
            "next_actions": ["补齐检测"],
            "processing_plan": plan,
        }
        answer = summarize_result(result, Path("demo.md"))
        recommendation_position = answer.index("**推荐方向**")
        plan_position = answer.index("### 完整加工流程（方案）")
        risk_position = answer.index("**质控风险**")
        self.assertLess(recommendation_position, plan_position)
        self.assertLess(plan_position, risk_position)
        self.assertIn("#### 01 原料准入与隔离", answer)
        self.assertIn("#### 05 成品检测与人工放行", answer)

    def test_model_context_and_general_prompt_cannot_drop_the_flow(self) -> None:
        plan = build_processing_plan(self.batch, DIRECTION_JUICE, [])
        context = build_analysis_context(
            {
                "batch": self.batch,
                "scores": [ScoreResult(direction=DIRECTION_JUICE, score=82, reasons=["演示评分"])],
                "quality_risks": [],
                "evidence": [],
                "next_actions": [],
                "processing_plan": plan,
                "report": "",
            }
        )
        system_prompt = build_general_chat_messages([], "柑橘汁怎么加工？")[0]["content"]
        self.assertIn("完整加工流程（方案）", context)
        self.assertIn("成品检测与人工放行", context)
        self.assertIn("必须在建议句后立即给出完整加工流程", system_prompt)

    def test_model_heading_without_steps_cannot_suppress_structured_flow(self) -> None:
        plan = build_processing_plan(self.batch, DIRECTION_JUICE, [])
        result = {
            "scores": [ScoreResult(direction=DIRECTION_JUICE, score=82, reasons=["演示评分"])],
            "quality_risks": [],
            "evidence": [],
            "next_actions": [],
            "processing_plan": plan,
        }
        model_answer = "结论摘要：建议加工果汁。完整加工流程将在后续评估中说明。"
        answer = ensure_primary_processing_flow(result, model_answer)
        self.assertIn(PROCESSING_FLOW_START, answer)
        self.assertIn("原料验收", answer)
        self.assertIn("成品检测与人工放行", answer)
        self.assertLess(answer.index("完整加工流程（方案）"), answer.index("简明结论"))
        self.assertIn(model_answer, strip_primary_processing_flow(answer))

    @patch("agent.tools.comprehensive_search_knowledge")
    def test_general_literature_retriever_always_returns_tool_result(self, search_mock) -> None:
        search_mock.return_value = [
            {
                "document_id": "DOC-1",
                "title": "柑橘汁加工研究",
                "category": "果汁",
                "chunk_text": "材料与方法包含榨汁、澄清和杀菌步骤。",
            }
        ]
        result = retrieve_literature("柑橘加工方向", "柑橘", top_k=4)
        self.assertEqual(result.status, "完成")
        self.assertEqual(result.data[0]["document_id"], "DOC-1")
        self.assertIn("1 篇文献", result.observation)

    @patch("agent.tools.comprehensive_search_knowledge")
    def test_faceted_literature_retriever_preserves_incomplete_status(self, search_mock) -> None:
        search_mock.side_effect = [
            {
                "evidence": [],
                "deep_retrieval_stats": {
                    "fts_rows_returned": 5,
                    "unique_candidate_count": 3,
                    "database_available": True,
                    "retrieval_complete": True,
                },
            },
            {
                "evidence": [],
                "deep_retrieval_stats": {
                    "fts_rows_returned": 7,
                    "unique_candidate_count": 4,
                    "database_available": False,
                    "retrieval_complete": False,
                    "retrieval_error": "索引加载失败；查询超时",
                    "timed_out": True,
                },
            },
        ]

        result = retrieve_literature(
            [{"query": "a", "category": None}, {"query": "b", "category": "橙汁"}, {"query": "c", "category": None}],
            "柑橘",
            retrieval_mode="deep",
        )
        stats = result.metadata["deep_retrieval_stats"]

        self.assertEqual(result.status, "部分完成")
        self.assertIn("全库索引未能加载", result.observation)
        self.assertEqual(search_mock.call_count, 2)
        self.assertEqual(stats["fts_rows_returned"], 12)
        self.assertEqual(stats["unique_candidate_count"], 7)
        self.assertFalse(stats["database_available"])
        self.assertFalse(stats["retrieval_complete"])
        self.assertTrue(stats["timed_out"])
        self.assertEqual(stats["retrieval_error"], "索引加载失败；查询超时")

    def test_workflow_retrieval_stats_keep_any_stage_failure(self) -> None:
        merged = _merge_retrieval_stats(
            {
                "fts_rows_returned": 10,
                "unique_candidate_count": 6,
                "database_available": True,
                "retrieval_complete": True,
            },
            {
                "fts_rows_returned": 4,
                "unique_candidate_count": 2,
                "database_available": False,
                "retrieval_complete": False,
                "retrieval_error": "索引加载失败",
            },
            {
                "database_available": True,
                "retrieval_complete": True,
                "retrieval_error": "索引加载失败；查询超时",
                "timed_out": True,
            },
        )

        self.assertEqual(merged["fts_rows_returned"], 14)
        self.assertEqual(merged["unique_candidate_count"], 8)
        self.assertFalse(merged["database_available"])
        self.assertFalse(merged["retrieval_complete"])
        self.assertTrue(merged["timed_out"])
        self.assertEqual(merged["retrieval_error"], "索引加载失败；查询超时")

    @patch("agent.tools.retrieve_processing_evidence")
    def test_processing_retriever_reports_partial_deep_search(self, retrieve_mock) -> None:
        retrieve_mock.return_value = {
            "evidence": [],
            "subquestions": [{} for _ in range(12)],
            "deep_retrieval_stats": {
                "retrieval_mode": "deep",
                "attempted_subquery_count": 4,
                "timed_out": True,
                "retrieval_complete": False,
            },
        }

        result = retrieve_processing_parameters(
            {"primary_product": "柑橘汁", "raw_material": "甜橙"},
            "柑橘",
            retrieval_mode="deep",
        )

        self.assertEqual(result.status, "部分完成")
        self.assertIn("4/12", result.observation)
        self.assertIn("时限", result.observation)

if __name__ == "__main__":
    unittest.main()
