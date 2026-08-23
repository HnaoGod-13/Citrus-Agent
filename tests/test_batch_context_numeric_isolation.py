from __future__ import annotations

import unittest

from agent.evidence import (
    DIRECT_EVIDENCE,
    EVIDENCE_POLICY_VERSION,
    INSUFFICIENT_EVIDENCE,
    REFERENCE_EVIDENCE,
)
from agent.llm_client import build_analysis_context, build_general_chat_messages
from agent.process_knowledge import format_processing_context


def approved_temperature_group() -> dict:
    return {
        "product": "柑橘汁",
        "raw_material": "甜橙",
        "process_step": "杀菌",
        "parameter_name": "温度",
        "unit": "℃",
        "scale": "lab",
        "process_method": "热处理",
        "recommended_range": "80 ℃（单篇文献直接报告，需小试验证）",
        "confidence_level": "中可信度",
        "source_ids": ["direct-study"],
        "source_refs": ["direct-study；片段 direct-c1；Materials and Methods，第2页"],
        "basis_type": "文献直接报告",
        "applicability": "原料：甜橙；规模：lab；方法：热处理",
        "recommendable": True,
        "public_display": True,
        "conflict": False,
        "scope_issues": [],
        "evidence_level": DIRECT_EVIDENCE,
        "alternatives": [],
    }


def raw_evidence(level: str, document_id: str, text: str, *, title: str) -> dict:
    return {
        "document_id": document_id,
        "chunk_id": f"{document_id}-c1",
        "title": title,
        "year": "2024",
        "category": "橙汁",
        "section": "Introduction",
        "page": 1,
        "chunk_text": text,
        "match_score": 96,
        "evidence_level": level,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
        "applicability": "回顾性背景材料；原文条件为 pH 3.5",
    }


class BatchContextNumericIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = {
            "raw_material": "甜橙",
            "primary_product": "柑橘汁",
            "scale": "lab",
            "equipment": [],
        }
        self.reference = raw_evidence(
            REFERENCE_EVIDENCE,
            "review-study",
            (
                "A review discusses orange juice pasteurization at 78 °C for 45 min, "
                "pH 3.5, a solid-to-liquid ratio of 1:20, and 0.8% enzyme."
            ),
            title="Review of pasteurization at 78 °C",
        )
        self.insufficient = raw_evidence(
            INSUFFICIENT_EVIDENCE,
            "catalog-note",
            "A catalog note mentions treatment at 75°C for 30 min under 80 MPa.",
            title="Unverified processing note",
        )
        self.groups = [approved_temperature_group()]

    def assert_raw_values_are_absent(self, context: str) -> None:
        for forbidden in (
            "78 °C",
            "45 min",
            "pH 3.5",
            "1:20",
            "0.8%",
            "75°C",
            "30 min",
            "80 MPa",
        ):
            self.assertNotIn(forbidden, context)

    def test_processing_context_uses_structured_values_not_raw_excerpt_values(self) -> None:
        context = format_processing_context(
            self.intent,
            self.groups,
            [self.reference, self.insufficient],
        )

        self.assertIn("[参数1] 杀菌/温度：80 ℃", context)
        self.assertIn("[工艺数值已屏蔽]", context)
        self.assertIn("[pH数值已屏蔽]", context)
        self.assertIn("[料液比数值已屏蔽]", context)
        self.assert_raw_values_are_absent(context)

    def test_analysis_context_masks_both_evidence_sections_but_keeps_approved_value(self) -> None:
        context = build_analysis_context(
            {
                "batch": {},
                "scores": [],
                "quality_risks": [],
                "evidence": [self.reference, self.insufficient],
                "processing_evidence": [self.reference, self.insufficient],
                "processing_intent": self.intent,
                "parameter_groups": self.groups,
                "next_actions": [],
                "processing_plan": {},
                "report": (
                    "# 批次报告\n\n弱证据背景曾报告 76 °C、40 min、pH 3.6 和料液比 1:18，"
                    "这些数值不得进入批次模型上下文。"
                ),
            }
        )

        self.assertIn("[参数1] 杀菌/温度：80 ℃", context)
        self.assert_raw_values_are_absent(context)

    def test_general_literature_qa_keeps_original_reported_values(self) -> None:
        messages = build_general_chat_messages(
            [],
            "请概述这篇橙汁研究",
            evidence=[self.reference],
        )
        model_input = "\n".join(message["content"] for message in messages)

        for reported in ("78 °C", "45 min", "pH 3.5", "1:20", "0.8%"):
            self.assertIn(reported, model_input)


if __name__ == "__main__":
    unittest.main()
