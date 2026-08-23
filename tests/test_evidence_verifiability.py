from __future__ import annotations

import unittest
from pathlib import Path

from agent.evidence import (
    DIRECT_EVIDENCE,
    INSUFFICIENT_EVIDENCE,
    REFERENCE_EVIDENCE,
    annotate_evidence,
    annotate_parameter_groups,
    build_key_conclusions,
    determine_evidence_level,
    format_key_conclusions_markdown,
    source_url,
)
from agent.orchestrator import (
    KEY_CONCLUSION_EVIDENCE_START,
    append_key_conclusion_evidence,
    strip_key_conclusion_evidence,
)
from agent.process_knowledge import (
    aggregate_parameter_evidence,
    build_parameterized_process_plan,
    extract_processing_parameters,
    is_public_parameter_group,
)
from agent.report import generate_report
from agent.rules import (
    DIRECTION_EVIDENCE_TERMS,
    DIRECTION_PEEL_PECTIN,
    ScoreResult,
    score_processing_options,
)


def direct_pectin_evidence() -> dict:
    return {
        "document_id": "citrus-pectin-paper",
        "chunk_id": "citrus-pectin-results-1",
        "title": "Extraction of pectin from citrus peel",
        "year": "2024",
        "doi": "doi:10.1234/citrus.2024.1",
        "category": "果胶",
        "processing_facet": "加工参数",
        "processing_score": 86,
        "section": "Results and discussion",
        "page": 6,
        "chunk_text": (
            "Extraction at 80 °C for 60 min increased citrus pectin yield to 21%, "
            "while longer treatment decreased degree of esterification."
        ),
    }


class EvidenceLevelPolicyTests(unittest.TestCase):
    def test_direct_fragment_requires_traceable_method_or_result_content(self) -> None:
        level, _reason = determine_evidence_level(direct_pectin_evidence())
        self.assertEqual(DIRECT_EVIDENCE, level)

    def test_high_retrieval_score_cannot_upgrade_weak_background_material(self) -> None:
        weak = {
            "document_id": "apple-review",
            "chunk_id": "apple-review-intro",
            "title": "A review of apple pectin",
            "year": "2025",
            "category": "果胶",
            "section": "Introduction",
            "page": 1,
            "match_score": 99.9,
            "chunk_text": "Pectin is a hydrocolloid widely used in the food industry.",
        }
        level, _reason = determine_evidence_level(weak)
        self.assertEqual(REFERENCE_EVIDENCE, level)

        batch = {"origin": "广西", "variety": "柑橘", "customer_type": "食品加工厂"}
        baseline = {
            item.direction: item
            for item in score_processing_options(batch, "", evidence=[])
        }
        with_weak = {
            item.direction: item
            for item in score_processing_options(batch, "", evidence=[weak])
        }
        self.assertEqual(
            baseline[DIRECTION_PEEL_PECTIN].score,
            with_weak[DIRECTION_PEEL_PECTIN].score,
        )
        self.assertEqual(0, with_weak[DIRECTION_PEEL_PECTIN].evidence_count)

    def test_processing_score_cannot_upgrade_an_off_focus_result(self) -> None:
        intent = {"primary_product": "果汁", "raw_material": "柑橘鲜果"}
        candidate = {
            "document_id": "citrus-pectin",
            "chunk_id": "pectin-result",
            "title": "Citrus pectin extraction",
            "year": "2024",
            "processing_score": 99,
            "section": "Results",
            "page": 4,
            "chunk_text": (
                "Extraction of citrus pectin at 80 °C for 60 min "
                "increased yield to 21%."
            ),
        }
        annotated = annotate_evidence([candidate], intent)
        self.assertEqual(REFERENCE_EVIDENCE, annotated[0]["evidence_level"])

        batch = {"origin": "广西", "variety": "柑橘", "customer_type": "食品加工厂"}
        baseline = {
            item.direction: item
            for item in score_processing_options(batch, "", evidence=[])
        }
        with_candidate = {
            item.direction: item
            for item in score_processing_options(batch, "", evidence=annotated)
        }
        self.assertEqual(
            baseline[DIRECTION_PEEL_PECTIN].score,
            with_candidate[DIRECTION_PEEL_PECTIN].score,
        )
        self.assertEqual(0, with_candidate[DIRECTION_PEEL_PECTIN].evidence_count)

    def test_pending_ocr_is_always_insufficient(self) -> None:
        pending = {
            "title": "Citrus pectin extraction",
            "year": "2022",
            "section": "题录（待OCR）",
            "chunk_text": "Citrus pectin extraction title record only.",
        }
        self.assertEqual(INSUFFICIENT_EVIDENCE, determine_evidence_level(pending)[0])

    def test_doi_is_normalized_to_a_clickable_url(self) -> None:
        self.assertEqual(
            "https://doi.org/10.1234/citrus.2024.1",
            source_url(direct_pectin_evidence()),
        )


class ParameterEvidenceBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = {
            "raw_material": "柑橘果皮",
            "primary_product": "果胶",
            "scale": "lab",
            "equipment": [],
        }

    def test_exact_parameter_chunk_cannot_borrow_another_result_from_the_document(self) -> None:
        evidence = annotate_evidence(
            [
                {
                    "document_id": "same-doc",
                    "chunk_id": "same-intro",
                    "title": "Citrus pectin extraction",
                    "year": "2024",
                    "category": "果胶",
                    "section": "Introduction",
                    "page": 1,
                    "chunk_text": "Pectin is a hydrocolloid found in citrus peel.",
                },
                {
                    "document_id": "same-doc",
                    "chunk_id": "same-result",
                    "title": "Citrus pectin extraction",
                    "year": "2024",
                    "category": "果胶",
                    "section": "Results",
                    "page": 6,
                    "chunk_text": (
                        "Extraction of citrus pectin at 80 °C for 60 min "
                        "increased yield to 21%."
                    ),
                },
            ],
            self.intent,
        )
        groups = annotate_parameter_groups(
            [
                {
                    "product": "果胶",
                    "raw_material": "柑橘果皮",
                    "process_step": "提取",
                    "parameter_name": "温度",
                    "unit": "℃",
                    "scale": "lab",
                    "process_method": "水提",
                    "recommended_range": "60 ℃（单篇文献直接报告，需小试验证）",
                    "confidence_level": "中可信度",
                    "source_ids": ["same-doc"],
                    "alternatives": [
                        {
                            "source_id": "same-doc",
                            "source_chunk_id": "same-intro",
                            "title": "Citrus pectin extraction",
                        }
                    ],
                    "recommendable": True,
                    "public_display": True,
                    "conflict": False,
                    "scope_issues": [],
                }
            ],
            evidence,
        )

        self.assertEqual(REFERENCE_EVIDENCE, groups[0]["evidence_level"])
        self.assertEqual(
            ["same-intro"],
            [item["chunk_id"] for item in groups[0]["evidence_refs"]],
        )
        self.assertTrue(
            all("80 °C" not in item["excerpt"] for item in groups[0]["evidence_refs"])
        )

    def test_reference_parameter_is_blocked_from_plan_and_key_cards(self) -> None:
        reference_group = {
            "product": "果胶",
            "raw_material": "柑橘果皮",
            "process_step": "提取",
            "parameter_name": "温度",
            "unit": "℃",
            "scale": "lab",
            "process_method": "水提",
            "recommended_range": "60 ℃（单篇文献直接报告，需小试验证）",
            "confidence_level": "中可信度",
            "recommendable": True,
            "public_display": True,
            "conflict": False,
            "scope_issues": [],
            "evidence_level": REFERENCE_EVIDENCE,
            "source_ids": ["same-doc"],
            "alternatives": [],
        }
        self.assertFalse(is_public_parameter_group(reference_group))

        plan = build_parameterized_process_plan(
            self.intent,
            [reference_group],
            [],
        )
        self.assertEqual(0, plan["parameter_count"])
        self.assertTrue(all(not row["parameters"] for row in plan["rows"]))

        cards = build_key_conclusions(
            [],
            [],
            [reference_group],
            [],
            self.intent,
            DIRECTION_EVIDENCE_TERMS,
        )
        self.assertFalse(any(item["conclusion_type"] == "工艺参数" for item in cards))

        direct_group = {**reference_group, "evidence_level": DIRECT_EVIDENCE}
        self.assertTrue(is_public_parameter_group(direct_group))

    def test_reference_value_cannot_expand_a_direct_parameter_range(self) -> None:
        intent = {
            "raw_material": "甜橙",
            "primary_product": "柑橘汁",
            "scale": "unknown",
            "equipment": [],
        }
        evidence = annotate_evidence(
            [
                {
                    "document_id": "direct-juice",
                    "chunk_id": "direct-juice-result",
                    "title": "Orange juice pasteurization experiment",
                    "year": "2024",
                    "category": "橙汁",
                    "section": "Results",
                    "page": 4,
                    "chunk_text": (
                        "Orange juice pasteurization at 80 °C reduced microbial counts."
                    ),
                },
                {
                    "document_id": "juice-review",
                    "chunk_id": "juice-review-intro",
                    "title": "Review of orange juice pasteurization",
                    "year": "2023",
                    "category": "橙汁",
                    "section": "Introduction",
                    "page": 1,
                    "chunk_text": (
                        "Orange juice pasteurization at 78 °C is frequently discussed."
                    ),
                },
            ],
            intent,
        )
        records = extract_processing_parameters(evidence, intent)
        self.assertEqual(
            {DIRECT_EVIDENCE, REFERENCE_EVIDENCE},
            {item["evidence_level"] for item in records},
        )
        groups = annotate_parameter_groups(
            aggregate_parameter_evidence(records),
            evidence,
        )
        temperature = next(
            item for item in groups if item["parameter_name"] == "温度"
        )

        self.assertEqual(DIRECT_EVIDENCE, temperature["evidence_level"])
        self.assertTrue(is_public_parameter_group(temperature))
        self.assertIn("80", temperature["recommended_range"])
        self.assertNotIn("78", temperature["recommended_range"])
        weak_alternative = next(
            item
            for item in temperature["alternatives"]
            if item["evidence_level"] == REFERENCE_EVIDENCE
        )
        self.assertFalse(weak_alternative["public_display"])


class ConclusionEvidenceCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = {
            "raw_material": "柑橘果皮",
            "primary_product": "柑橘果胶",
            "scale": "lab",
        }
        self.evidence = annotate_evidence([direct_pectin_evidence()], self.intent)
        self.groups = annotate_parameter_groups(
            [
                {
                    "process_step": "提取",
                    "parameter_name": "温度",
                    "recommended_range": "80 ℃（单篇文献直接报告，需小试验证）",
                    "confidence_level": "中可信度",
                    "source_ids": ["citrus-pectin-paper"],
                    "alternatives": [
                        {
                            "source_id": "citrus-pectin-paper",
                            "source_chunk_id": "citrus-pectin-results-1",
                            "title": "Extraction of pectin from citrus peel",
                        }
                    ],
                    "applicability": "原料：柑橘果皮；规模：lab；方法：水提",
                    "recommendable": True,
                    "conflict": False,
                }
            ],
            self.evidence,
        )
        self.score = ScoreResult(
            direction=DIRECTION_PEEL_PECTIN,
            score=82,
            match_level="优先评估",
            evidence_support="有限（1篇直接相关文献）",
            evidence_count=1,
            data_confidence="中",
        )
        self.conclusions = build_key_conclusions(
            [self.score],
            self.evidence,
            self.groups,
            [],
            self.intent,
            DIRECTION_EVIDENCE_TERMS,
        )

    def test_conclusion_card_binds_all_required_verification_fields(self) -> None:
        parameter_card = next(
            item for item in self.conclusions if item["conclusion_type"] == "工艺参数"
        )
        self.assertEqual(DIRECT_EVIDENCE, parameter_card["evidence_level"])
        reference = parameter_card["evidence"][0]
        for key in ("title", "year", "doi", "url", "excerpt", "applicability"):
            self.assertTrue(reference.get(key), key)

    def test_final_answer_cards_are_deterministic_and_removed_from_model_history(self) -> None:
        answer = append_key_conclusion_evidence("### 综合判断\n先做小试。", self.conclusions)
        self.assertIn(KEY_CONCLUSION_EVIDENCE_START, answer)
        self.assertIn("证据等级", answer)
        self.assertIn("[DOI 10.1234/citrus.2024.1](https://doi.org/10.1234/citrus.2024.1)", answer)
        self.assertEqual("### 综合判断\n先做小试。", strip_key_conclusion_evidence(answer))

    def test_report_contains_linked_conclusion_cards_and_evidence_boundaries(self) -> None:
        batch = {
            "batch_id": "VERIFY-1",
            "origin": "广西",
            "variety": "柑橘",
            "weight_kg": 100,
            "customer_type": "食品加工厂",
        }
        report = generate_report(
            batch,
            "",
            self.evidence,
            [self.score],
            [],
            parameter_groups=self.groups,
            key_conclusions=self.conclusions,
        )
        self.assertIn("关键结论证据卡", report)
        self.assertIn("直接证据", report)
        self.assertIn("原文片段", report)
        self.assertIn("适用条件", report)
        self.assertIn("https://doi.org/10.1234/citrus.2024.1", report)

    def test_ui_source_renders_linked_conclusion_cards(self) -> None:
        ui_source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def render_key_conclusion_evidence", ui_source)
        self.assertIn('target="_blank"', ui_source)
        self.assertIn('with st.expander("关键结论证据", expanded=True)', ui_source)
        self.assertIn('"证据等级": item.get("evidence_level")', ui_source)


if __name__ == "__main__":
    unittest.main()
