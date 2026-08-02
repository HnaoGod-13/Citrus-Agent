from __future__ import annotations

import unittest

from agent.process_knowledge import (
    aggregate_parameter_evidence,
    analyze_processing_intent,
    build_parameterized_process_plan,
    build_processing_subquestions,
    extract_processing_parameters,
    retrieve_processing_evidence,
)
from agent.report import parameterized_plan_markdown


def evidence(
    document_id: str,
    title: str,
    text: str,
    *,
    section: str = "材料与方法",
    page: int = 1,
    category: str = "橙汁",
    year: int = 2022,
) -> dict:
    return {
        "chunk_id": f"{document_id}-c1",
        "document_id": document_id,
        "title": title,
        "chunk_text": text,
        "section": section,
        "page_start": page,
        "category": category,
        "year": year,
        "match_score": 75,
        "retrieval_method": "test_hybrid",
    }


class ProcessingKnowledgeTests(unittest.TestCase):
    def test_juice_end_to_end_produces_traceable_parameterized_plan(self) -> None:
        intent = analyze_processing_intent(
            "这批脐橙适合怎样加工成果汁？现有榨汁机和均质机，先做中试。",
            {"origin": "赣南", "variety": "脐橙"},
        )
        chunks = [
            evidence(
                "juice-001",
                "脐橙汁酶法澄清工艺",
                "脐橙汁采用果胶酶酶解澄清，果胶酶添加量为0.04–0.06%，在45–50℃处理60–90 min，澄清度提高。",
                page=5,
            ),
            evidence(
                "juice-002",
                "橙汁澄清和稳定化研究",
                "橙汁果胶酶酶解时使用0.05%，温度45–50°C，时间60–90 min，处理后浊度降低。",
                page=7,
            ),
            evidence(
                "juice-003",
                "橙汁热处理工艺",
                "橙汁杀菌在85–90℃保持15–30 s，随后灌装；该条件下微生物数量降低。",
                page=9,
            ),
        ]
        records = extract_processing_parameters(chunks, intent)
        groups = aggregate_parameter_evidence(records)
        plan = build_parameterized_process_plan(intent, groups, chunks)

        required = {
            "product", "raw_material", "process_step", "parameter_name", "value", "unit",
            "range", "conditions", "scale", "effect_on_quality", "source_id",
            "source_location", "confidence",
        }
        self.assertTrue(records)
        self.assertTrue(required.issubset(records[0]))
        self.assertEqual(intent["primary_product"], "柑橘汁")
        self.assertEqual(intent["scale"], "pilot")
        self.assertIn("榨汁机", intent["equipment"])
        self.assertGreater(plan["parameter_count"], 0)
        self.assertIn("破碎/榨汁", plan["flow"])
        self.assertTrue(any("juice-001" in group["source_ids"] for group in groups))
        self.assertTrue(any(group["confidence_level"] == "高可信度" for group in groups))

    def test_chenpi_end_to_end_keeps_drying_method_and_scale(self) -> None:
        intent = analyze_processing_intent(
            "茶枝柑果皮加工广陈皮，实验室比较热风干燥条件",
            {"origin": "新会", "variety": "茶枝柑"},
        )
        chunks = [
            evidence(
                "chenpi-001",
                "茶枝柑果皮热风干燥研究",
                "实验室采用热风干燥茶枝柑果皮，温度45–55℃，干燥6–8 h，终点水分为12–14%，色泽保持较好。",
                category="陈皮",
                page=3,
            ),
            evidence(
                "chenpi-002",
                "广陈皮干燥条件优化",
                "实验室热风干燥温度50–55℃，处理6–8 h，水分控制在12–14%，可减少返潮。",
                category="陈皮",
                page=6,
            ),
        ]
        records = extract_processing_parameters(chunks, intent)
        groups = aggregate_parameter_evidence(records)
        plan = build_parameterized_process_plan(intent, groups, chunks)
        markdown = parameterized_plan_markdown(plan, groups, intent)

        self.assertEqual(intent["primary_product"], "陈皮")
        self.assertTrue(any(item["process_step"] == "干燥" for item in records))
        self.assertTrue(all(item["scale"] == "lab" for item in records))
        self.assertTrue(any(item["process_method"] == "热风" for item in records))
        self.assertIn("开皮取皮", plan["flow"])
        self.assertIn("详细操作参数", markdown)
        self.assertIn("证据来源", markdown)
        self.assertIn("chenpi-001", markdown)

    def test_conflicting_parameters_are_preserved_not_averaged(self) -> None:
        base = {
            "product": "柑橘汁",
            "raw_material": "脐橙",
            "process_step": "杀菌",
            "parameter_name": "温度",
            "unit": "℃",
            "range": "70–72",
            "value": "",
            "conditions": "冷藏NFC果汁，保持30 s",
            "scale": "pilot",
            "process_method": "未标明方法",
            "effect_on_quality": "",
            "source_location": "材料与方法，第2页",
            "confidence": 0.8,
            "eligible_for_recommendation": True,
            "unit_missing": False,
            "title": "A",
            "year": "2020",
        }
        first = {**base, "source_id": "A"}
        second = {**base, "source_id": "B", "range": "95–98", "conditions": "常温果汁，保持15 s", "title": "B"}
        group = aggregate_parameter_evidence([first, second])[0]
        self.assertTrue(group["conflict"])
        self.assertEqual(group["confidence_level"], "低可信度")
        self.assertEqual(len(group["alternatives"]), 2)
        self.assertNotIn("84", group["recommended_range"])

    def test_missing_unit_is_low_confidence_and_never_recommended(self) -> None:
        intent = analyze_processing_intent("果汁酶解澄清", {"variety": "脐橙"})
        chunks = [
            evidence(
                "missing-unit",
                "橙汁酶解试验",
                "橙汁用果胶酶进行酶解，酶添加量为0.05，处理后再过滤。",
                page=4,
            )
        ]
        records = extract_processing_parameters(chunks, intent)
        missing = [item for item in records if item.get("unit_missing")]
        self.assertTrue(missing)
        self.assertFalse(missing[0]["eligible_for_recommendation"])
        group = aggregate_parameter_evidence(missing)[0]
        self.assertEqual(group["confidence_level"], "低可信度")
        self.assertIn("单位缺失", group["recommended_range"])

    def test_equation_line_numbers_and_equipment_models_are_not_parameters(self) -> None:
        intent = analyze_processing_intent("橙汁杀菌", {"variety": "甜橙"})
        chunks = [
            evidence(
                "false-numbers",
                "High-pressure homogenization of orange juice",
                "The equipment was Branson CPX3800H, 40 kHz. pH = 148 (7.8-a)e(-kt). Supplier 146 Barcelona. The juice was adjusted to pH 7.8 and was measured for 30 min at 147 ºC. Thermal treatment was 68 ºC for 15 s.",
                section="Materials and Methods",
            )
        ]
        records = extract_processing_parameters(chunks, intent)
        values = {(item["parameter_name"], item["value"], item["unit"]) for item in records}
        self.assertNotIn(("时间", "3800", "H"), values)
        self.assertFalse(any(item["parameter_name"] == "pH" and item["value"] == "148" for item in records))
        self.assertFalse(any(item["parameter_name"] == "压力" and item["value"] == "146" for item in records))
        self.assertIn(("温度", "68", "°C"), values)
        self.assertIn(("时间", "15", "s"), values)
        groups = aggregate_parameter_evidence(records)
        plan = build_parameterized_process_plan(intent, groups, chunks)
        displayed = {
            (param["name"], param["recommendation"])
            for row in plan["rows"]
            for param in row["parameters"]
        }
        self.assertFalse(any(name == "pH" and "7.8" in value for name, value in displayed))
        self.assertFalse(any(name == "温度" and "147" in value for name, value in displayed))

    def test_different_scale_and_method_are_not_mixed(self) -> None:
        common = {
            "product": "陈皮", "raw_material": "茶枝柑", "process_step": "干燥",
            "parameter_name": "温度", "unit": "℃", "value": "50", "range": "",
            "conditions": "干燥处理", "effect_on_quality": "", "source_location": "第1页",
            "confidence": 0.8, "eligible_for_recommendation": True, "unit_missing": False,
            "title": "研究", "year": "2022",
        }
        records = [
            {**common, "source_id": "lab-hot", "scale": "lab", "process_method": "热风"},
            {**common, "source_id": "pilot-vacuum", "scale": "pilot", "process_method": "真空", "value": "42"},
        ]
        groups = aggregate_parameter_evidence(records)
        self.assertEqual(len(groups), 2)
        self.assertEqual({item["scale"] for item in groups}, {"lab", "pilot"})
        self.assertEqual({item["process_method"] for item in groups}, {"热风", "真空"})

    def test_insufficient_evidence_keeps_complete_flow_without_numbers(self) -> None:
        intent = analyze_processing_intent("加工成果汁", {"variety": "甜橙"})
        plan = build_parameterized_process_plan(intent, [], [])
        markdown = parameterized_plan_markdown(plan, [], intent)
        self.assertIn("杀菌", plan["flow"])
        self.assertIn("现有知识库证据不足，不填入数值", markdown)
        self.assertEqual(plan["parameter_count"], 0)

    def test_faceted_retrieval_prefers_methods_with_parameters_over_background(self) -> None:
        intent = analyze_processing_intent("橙汁怎样加工", {"variety": "甜橙"})
        method = evidence(
            "method",
            "Orange juice processing method",
            "Orange juice was pasteurized at 85–90°C for 15–30 s and then filled.",
            section="Materials and Methods",
        )
        background = evidence(
            "background",
            "Orange juice: a broad review",
            "Orange juice is widely consumed and has nutritional and commercial importance.",
            section="引言",
        )
        background["match_score"] = 95

        def fake_search(*args, **kwargs):
            return [background, method]

        retrieved, specs = retrieve_processing_evidence(
            intent,
            product_filter="柑橘",
            top_k=6,
            search_fn=fake_search,
        )
        self.assertGreaterEqual(len(build_processing_subquestions(intent)), 8)
        self.assertTrue(specs)
        self.assertTrue(retrieved)
        self.assertEqual(retrieved[0]["document_id"], "method")
        self.assertIn("processing_faceted_hybrid", retrieved[0]["retrieval_method"])


if __name__ == "__main__":
    unittest.main()
