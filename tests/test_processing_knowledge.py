from __future__ import annotations

import unittest

from agent.evidence import DIRECT_EVIDENCE, annotate_evidence, annotate_parameter_groups
from agent.process_knowledge import (
    aggregate_parameter_evidence,
    analyze_processing_intent,
    build_parameterized_process_plan,
    build_processing_subquestions,
    extract_processing_parameters,
    format_processing_context,
    is_public_parameter_group,
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


def verified_parameters(
    chunks: list[dict],
    intent: dict,
) -> tuple[list[dict], list[dict], list[dict]]:
    annotated = annotate_evidence(chunks, intent)
    records = extract_processing_parameters(annotated, intent)
    groups = annotate_parameter_groups(
        aggregate_parameter_evidence(records),
        annotated,
    )
    return annotated, records, groups


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
        annotated, records, groups = verified_parameters(chunks, intent)
        plan = build_parameterized_process_plan(intent, groups, annotated)

        required = {
            "product", "raw_material", "process_step", "parameter_name", "value", "unit",
            "range", "conditions", "scale", "effect_on_quality", "source_id",
            "source_chunk_id", "source_location", "confidence",
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

    def test_pectin_direct_extraction_parameters_reach_plan_and_report(self) -> None:
        intent = analyze_processing_intent(
            "实验室把柑橘果皮加工成果胶，重点验证 extraction 温度和时间。",
            {"variety": "柑橘果皮"},
        )
        chunk = evidence(
            "pectin-direct",
            "Citrus peel pectin extraction",
            (
                "Laboratory extraction of citrus peel pectin at 80°C for 60 min "
                "increased the pectin yield."
            ),
            section="Results",
            category="果胶",
            page=6,
            year=2024,
        )

        annotated, records, groups = verified_parameters([chunk], intent)
        plan = build_parameterized_process_plan(intent, groups, annotated)
        markdown = parameterized_plan_markdown(plan, groups, intent)
        extraction_row = next(row for row in plan["rows"] if row["step"] == "提取")

        self.assertEqual(intent["primary_product"], "果胶")
        self.assertIn("提取", intent["operations"])
        self.assertNotIn("破碎/榨汁", intent["operations"])
        self.assertEqual(
            {"温度", "时间"},
            {
                item["parameter_name"]
                for item in records
                if item["eligible_for_recommendation"]
            },
        )
        self.assertEqual({"温度", "时间"}, {item["name"] for item in extraction_row["parameters"]})
        self.assertEqual(plan["parameter_count"], 2)
        self.assertIn("沉淀/分离", plan["flow"])
        self.assertIn("粉碎/标准化", plan["flow"])
        self.assertTrue(plan["equipment"])
        self.assertIn("80 °C", markdown)
        self.assertIn("60 min", markdown)
        self.assertIn("Citrus peel pectin extraction", markdown)

    def test_essential_oil_has_a_dedicated_complete_route_and_retrieval_facets(self) -> None:
        intent = analyze_processing_intent(
            "柑橘果皮加工精油，比较冷压和水蒸气蒸馏路线。",
            {"variety": "柑橘果皮"},
        )
        plan = build_parameterized_process_plan(intent, [], [])
        specs = build_processing_subquestions(intent)

        self.assertEqual(intent["primary_product"], "精油")
        self.assertIn("提取", intent["operations"])
        self.assertIn("油水分离", plan["flow"])
        self.assertIn("精制/调配", plan["flow"])
        self.assertIn("质量检测", plan["flow"])
        self.assertTrue(plan["equipment"])
        self.assertIn("oil_extraction", {item["id"] for item in specs})
        self.assertIn("oil_separation", {item["id"] for item in specs})

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
        annotated, records, groups = verified_parameters(chunks, intent)
        plan = build_parameterized_process_plan(intent, groups, annotated)
        markdown = parameterized_plan_markdown(plan, groups, intent)
        visible_markdown = parameterized_plan_markdown(
            plan,
            groups,
            intent,
            include_source_metadata=False,
            include_flow=False,
        )

        self.assertEqual(intent["primary_product"], "陈皮")
        self.assertTrue(any(item["process_step"] == "干燥" for item in records))
        self.assertTrue(all(item["scale"] == "lab" for item in records))
        self.assertTrue(any(item["process_method"] == "热风" for item in records))
        self.assertIn("开皮取皮", plan["flow"])
        self.assertIn("详细操作参数", markdown)
        self.assertIn("证据来源", markdown)
        self.assertIn("chenpi-001", markdown)
        self.assertIn("chenpi-001-c1", markdown)
        self.assertIn("第3页", markdown)
        self.assertIn("详细操作参数", visible_markdown)
        self.assertIn("设备需求及替代设备", visible_markdown)
        self.assertNotIn("证据来源", visible_markdown)
        self.assertNotIn("来源定位", visible_markdown)
        self.assertNotIn("证据定位", visible_markdown)
        self.assertNotIn("chenpi-001", visible_markdown)
        self.assertNotIn("第3页", visible_markdown)
        self.assertNotIn("推荐工艺流程", visible_markdown)
        self.assertNotIn("原文条件", visible_markdown)
        self.assertNotIn("实验室采用热风干燥", visible_markdown)

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
            "evidence_level": DIRECT_EVIDENCE,
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
        plan = build_parameterized_process_plan(
            {"primary_product": "柑橘汁", "raw_material": "脐橙"},
            [group],
            [],
        )
        sterilization = next(row for row in plan["rows"] if row["step"] == "杀菌")
        self.assertEqual(sterilization["parameters"], [])

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

        plan = build_parameterized_process_plan(intent, [group], chunks)
        markdown = parameterized_plan_markdown(plan, [group], intent)
        self.assertIn("暂无可靠参数", markdown)
        self.assertNotIn("0.05 [单位缺失]", markdown)

    def test_hplc_settings_never_become_storage_parameters_or_public_numbers(self) -> None:
        intent = analyze_processing_intent(
            "茶枝柑陈皮储藏条件",
            {"origin": "新会", "variety": "茶枝柑"},
        )
        chunk = evidence(
            "storage-hplc",
            "Changes in Chenpi quality during storage",
            (
                "During storage, samples were kept at 4°C for 30 days. "
                "The method was modified from the one developed by Zeng's group. "
                "The flow rate was 0.6 mL/min, the column temperature was 25°C "
                "and the maximal pressure was 250 bar. The mobile phase was followed "
                "by a gradient elution: 0–6 min, 16–19% B."
            ),
            section="Materials and Methods",
            category="陈皮",
        )

        annotated, records, groups = verified_parameters([chunk], intent)
        public_groups = [item for item in groups if is_public_parameter_group(item)]
        plan = build_parameterized_process_plan(intent, groups, annotated)
        markdown = parameterized_plan_markdown(plan, groups, intent)
        model_context = format_processing_context(intent, groups, [chunk])

        self.assertTrue(any(item["parameter_name"] == "温度" and item["value"] == "4" for item in records))
        self.assertTrue(any(item["parameter_name"] == "时间" and item["value"] == "30" for item in records))
        self.assertFalse(any(item["value"] in {"250", "0.6"} for item in records))
        self.assertFalse(any(item.get("range") == "0–6" for item in records))
        self.assertEqual({item["parameter_name"] for item in public_groups}, {"温度", "时间"})
        for forbidden in ("250 bar", "0.6 mL/min", "0–6 min"):
            self.assertNotIn(forbidden, markdown)
            self.assertNotIn(forbidden, model_context)

    def test_storage_step_rejects_pressure_minutes_and_flow_even_without_hplc_words(self) -> None:
        intent = analyze_processing_intent(
            "茶枝柑陈皮储藏条件",
            {"origin": "新会", "variety": "茶枝柑"},
        )
        chunk = evidence(
            "bad-storage-units",
            "Chenpi storage trial",
            "Chenpi samples were stored at 250 bar for 6 min with a flow rate of 0.6 mL/min.",
            category="陈皮",
        )

        records = extract_processing_parameters([chunk], intent)
        groups = aggregate_parameter_evidence(records)
        plan = build_parameterized_process_plan(intent, groups, [chunk])
        markdown = parameterized_plan_markdown(plan, groups, intent)

        self.assertTrue(records)
        self.assertTrue(all(not item["eligible_for_recommendation"] for item in records))
        self.assertTrue(all(item.get("scope_issues") for item in records))
        self.assertTrue(all(not is_public_parameter_group(item) for item in groups))
        self.assertIn("暂无可靠参数", markdown)
        for forbidden in ("250 bar", "6 min", "0.6 mL/min"):
            self.assertNotIn(forbidden, markdown)

        legacy_groups = [
            {
                "recommendable": True,
                "conflict": False,
                "process_step": "储藏",
                "parameter_name": "压力",
                "unit": "bar",
                "recommended_range": "250 bar（单篇文献直接报告，需小试验证）",
            },
            {
                "recommendable": True,
                "conflict": False,
                "process_step": "储藏",
                "parameter_name": "时间",
                "unit": "min",
                "recommended_range": "0–6 min（单篇文献直接报告，需小试验证）",
            },
            {
                "recommendable": True,
                "conflict": False,
                "process_step": "储藏",
                "parameter_name": "流量",
                "unit": "mL/min",
                "recommended_range": "0.6 mL/min（单篇文献直接报告，需小试验证）",
            },
        ]
        self.assertTrue(all(not is_public_parameter_group(item) for item in legacy_groups))

    def test_known_raw_scale_and_required_equipment_mismatches_block_parameter(self) -> None:
        intent = analyze_processing_intent(
            "脐橙汁中试处理，现有杀菌机。",
            {"origin": "赣南", "variety": "脐橙"},
        )
        chunk = evidence(
            "mismatch",
            "Laboratory high-pressure homogenization of mandarin juice",
            "Mandarin juice was homogenized at 80 MPa in a laboratory experiment.",
            category="橙汁",
        )

        records = extract_processing_parameters([chunk], intent)
        pressure = next(item for item in records if item["parameter_name"] == "压力")
        groups = aggregate_parameter_evidence(records)
        plan = build_parameterized_process_plan(intent, groups, [chunk])
        markdown = parameterized_plan_markdown(plan, groups, intent)

        self.assertFalse(pressure["eligible_for_recommendation"])
        self.assertTrue(any("原料" in issue for issue in pressure["scope_issues"]))
        self.assertTrue(any("规模" in issue for issue in pressure["scope_issues"]))
        self.assertTrue(any("设备" in issue for issue in pressure["scope_issues"]))
        self.assertTrue(all(not is_public_parameter_group(item) for item in groups))
        self.assertNotIn("80 MPa", markdown)

    def test_same_source_duplicate_parameter_is_collapsed_before_display(self) -> None:
        record = {
            "product": "柑橘汁",
            "raw_material": "脐橙",
            "process_step": "杀菌",
            "parameter_name": "温度",
            "unit": "℃",
            "range": "85–90",
            "value": "",
            "conditions": "橙汁杀菌",
            "scale": "pilot",
            "process_method": "热处理",
            "effect_on_quality": "微生物降低。",
            "source_id": "same-paper",
            "source_location": "材料与方法，第2页",
            "confidence": 0.8,
            "eligible_for_recommendation": True,
            "evidence_level": DIRECT_EVIDENCE,
            "unit_missing": False,
            "title": "橙汁杀菌",
            "year": "2022",
        }

        group = aggregate_parameter_evidence([
            record,
            {**record, "conditions": "重复片段中的同一橙汁杀菌条件"},
        ])[0]

        self.assertEqual(group["evidence_count"], 1)
        self.assertEqual(group["duplicate_count"], 1)
        self.assertEqual(len(group["alternatives"]), 1)
        group["evidence_level"] = DIRECT_EVIDENCE
        self.assertTrue(is_public_parameter_group(group))

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

    def test_compound_route_step_uses_packaging_and_filling_evidence(self) -> None:
        intent = analyze_processing_intent("甜橙加工成果汁", {"variety": "甜橙"})
        groups = [
            {
                "recommendable": True,
                "raw_material": intent["raw_material"],
                "process_step": "包装/灌装",
                "parameter_name": "温度",
                "recommended_range": "82 °C（单篇文献直接报告，需小试验证）",
                "confidence_level": "中可信度",
                "scale": "pilot",
                "process_method": "热处理",
                "conflict": False,
                "source_ids": ["filling-paper"],
                "unit": "°C",
                "evidence_level": DIRECT_EVIDENCE,
                "public_display": True,
            }
        ]

        plan = build_parameterized_process_plan(intent, groups, [])
        filling_row = next(row for row in plan["rows"] if row["step"] == "灌装包装")

        self.assertTrue(filling_row["parameters"])
        self.assertNotIn("灌装包装", plan["unresolved_steps"])

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

    def test_deep_subquestions_include_user_operations_parameters_and_equipment(self) -> None:
        intent = analyze_processing_intent(
            "脐橙汁做高压均质，关注压力、流量和温度，现有均质机。",
            {"origin": "赣南", "variety": "脐橙"},
        )
        specs = build_processing_subquestions(intent, retrieval_mode="deep")
        combined = " ".join(str(item["query"]) for item in specs)

        self.assertEqual(specs[0]["id"], "user_focus")
        self.assertIn("高压均质", combined)
        self.assertIn("压力", combined)
        self.assertIn("流量", combined)
        self.assertIn("温度", combined)
        self.assertIn("均质机", combined)
        self.assertIn("均质", {str(item["facet"]) for item in specs})

    def test_deep_retrieval_attaches_adjacent_context_and_returns_stats(self) -> None:
        intent = analyze_processing_intent("橙汁高压均质压力参数", {"variety": "甜橙"})
        seed = evidence(
            "target",
            "Orange juice stability results",
            "Orange juice treated at 80 MPa showed improved stability.",
            section="Results",
        )
        seed["chunk_index"] = 2
        ocr = evidence(
            "ocr",
            "Orange juice pressure catalog",
            "题名：Orange juice pressure catalog。该 PDF 暂未提取到可用正文，不能据此推断研究结果。",
            section="题录（待OCR）",
        )
        wrong_product = evidence(
            "apple",
            "Apple juice pressure treatment",
            "Apple juice was processed at 70 MPa.",
            section="Materials and Methods",
        )
        background = evidence(
            "background-low",
            "Orange juice overview",
            "Orange juice is a popular beverage.",
            section="引言",
        )
        background["match_score"] = 0

        def fake_search(*args, **kwargs):
            return [ocr, wrong_product, background, seed]

        def fake_adjacent(selected, **kwargs):
            method = evidence(
                "target",
                "Orange juice homogenization method",
                "Orange juice was homogenized at 80 MPa before filling.",
                section="Materials and Methods",
                page=4,
            )
            method["chunk_id"] = "target-c0"
            method["chunk_index"] = 1
            cross_document = evidence(
                "other",
                "Other juice method",
                "Other juice was pasteurized.",
                section="Materials and Methods",
            )
            return {
                "adjacent_chunks": {seed["chunk_id"]: [method, cross_document]},
                "deep_retrieval_stats": {
                    "adjacent_candidate_count": 2,
                    "adjacent_added_count": 2,
                },
            }

        payload = retrieve_processing_evidence(
            intent,
            product_filter="柑橘",
            top_k=6,
            search_fn=fake_search,
            adjacent_fn=fake_adjacent,
            retrieval_mode="deep",
            return_metadata=True,
        )
        records = extract_processing_parameters(payload["evidence"], intent)
        pressure = [
            item
            for item in records
            if item["parameter_name"] == "压力"
            and item["value"] == "80"
            and item["eligible_for_recommendation"]
        ]
        stats = payload["deep_retrieval_stats"]

        self.assertEqual(len(payload["evidence"]), 1)
        self.assertEqual(payload["evidence"][0]["adjacent_chunks"][0]["document_id"], "target")
        self.assertTrue(pressure)
        self.assertEqual(pressure[0]["process_step"], "均质")
        self.assertTrue(pressure[0]["eligible_for_recommendation"])
        adjacent_pressure = next(
            item
            for item in records
            if item["parameter_name"] == "压力" and item["source_chunk_id"] == "target-c0"
        )
        self.assertTrue(adjacent_pressure["adjacent_context_used"])
        self.assertIn("第4页", adjacent_pressure["source_location"])
        groups = aggregate_parameter_evidence(records)
        pressure_group = next(item for item in groups if item["parameter_name"] == "压力")
        self.assertTrue(any("target-c0" in ref and "第4页" in ref for ref in pressure_group["source_refs"]))
        self.assertGreater(stats["ocr_filtered_count"], 0)
        self.assertGreater(stats["product_filtered_count"], 0)
        self.assertGreater(stats["score_filtered_count"], 0)
        self.assertEqual(stats["adjacent_candidate_count"], 2)
        self.assertEqual(stats["adjacent_added_count"], 1)
        self.assertEqual(stats["selected_count"], 1)

    def test_unresolved_steps_do_not_exhaust_parameter_limit(self) -> None:
        intent = analyze_processing_intent("橙汁杀菌参数", {"variety": "甜橙"})
        chunks = [
            evidence(
                "unknown",
                "Orange juice temperature screening",
                "Orange juice temperature values were 30°C, 40°C and 50°C.",
                section="Results",
            ),
            evidence(
                "pasteurization",
                "Orange juice pasteurization method",
                "Orange juice pasteurization used 85°C for 15 s.",
                section="Materials and Methods",
            ),
        ]

        records = extract_processing_parameters(chunks, intent, limit=2)

        self.assertEqual(len(records), 2)
        self.assertTrue(all(item["process_step"] == "杀菌" for item in records))
        self.assertEqual({item["parameter_name"] for item in records}, {"温度", "时间"})

    def test_sugar_acid_adjustment_parameters_reach_the_matching_route_step(self) -> None:
        intent = analyze_processing_intent(
            "NFC橙汁糖酸调整，关注Brix和酸度参数。",
            {"variety": "脐橙"},
        )
        chunk = evidence(
            "sugar-acid-paper",
            "Sugar-acid adjustment of NFC orange juice",
            "During sugar-acid adjustment, soluble solids were set to 12 Brix and acidity to 0.6%.",
            section="Materials and Methods",
        )

        annotated, records, groups = verified_parameters([chunk], intent)
        plan = build_parameterized_process_plan(intent, groups, annotated)
        adjustment_row = next(row for row in plan["rows"] if row["step"] == "糖酸调整")

        self.assertIn("糖酸调整", intent["operations"])
        self.assertEqual(
            {"可溶性固形物", "酸度"},
            {
                item["parameter_name"]
                for item in records
                if item["eligible_for_recommendation"]
            },
        )
        self.assertTrue(adjustment_row["parameters"])
        self.assertNotIn("糖酸调整", plan["unresolved_steps"])

    def test_deep_mode_allows_four_chunks_per_document_while_quick_keeps_two(self) -> None:
        intent = analyze_processing_intent("橙汁杀菌参数", {"variety": "甜橙"})
        chunks = []
        for index in range(4):
            item = evidence(
                "single-paper",
                "Orange juice pasteurization method",
                f"Orange juice pasteurization used {80 + index}°C for 20 s.",
                section="Materials and Methods",
            )
            item["chunk_id"] = f"single-paper-c{index}"
            item["chunk_index"] = index + 1
            item["match_score"] = 90 - index
            chunks.append(item)

        def fake_search(*args, **kwargs):
            return chunks

        def no_adjacent(*args, **kwargs):
            return {"adjacent_chunks": {}, "deep_retrieval_stats": {}}

        quick, _ = retrieve_processing_evidence(
            intent,
            top_k=6,
            search_fn=fake_search,
        )
        deep = retrieve_processing_evidence(
            intent,
            top_k=6,
            search_fn=fake_search,
            adjacent_fn=no_adjacent,
            retrieval_mode="deep",
            return_metadata=True,
        )

        self.assertEqual(len(quick), 2)
        self.assertEqual(len(deep["evidence"]), 4)
        self.assertEqual(deep["deep_retrieval_stats"]["selected_document_count"], 1)

    def test_adjacent_operation_does_not_claim_an_unlabeled_number(self) -> None:
        intent = analyze_processing_intent("橙汁清洗参数", {"variety": "甜橙"})
        seed = evidence(
            "washing-paper",
            "Orange washing method",
            "Orange fruit was washed before processing.",
            section="Materials and Methods",
        )
        neighbor = evidence(
            "washing-paper",
            "Processing results",
            "The processing time was 20 s.",
            section="Results",
        )
        neighbor["chunk_id"] = "washing-paper-c2"
        seed["adjacent_chunks"] = [neighbor]

        records = extract_processing_parameters([seed], intent)
        time_record = next(item for item in records if item["parameter_name"] == "时间")

        self.assertEqual(time_record["process_step"], "未明确单元操作")
        self.assertFalse(time_record["eligible_for_recommendation"])

    def test_multi_operation_title_does_not_assign_an_unlabeled_number(self) -> None:
        intent = analyze_processing_intent("橙汁加工时间参数", {"variety": "甜橙"})
        chunk = evidence(
            "multi-operation-paper",
            "Orange juice washing and pasteurization",
            "The processing time was 20 s.",
            section="Results",
        )

        records = extract_processing_parameters([chunk], intent)
        time_record = next(item for item in records if item["parameter_name"] == "时间")

        self.assertEqual(time_record["process_step"], "未明确单元操作")
        self.assertFalse(time_record["eligible_for_recommendation"])

    def test_table_significance_letters_are_not_read_as_days(self) -> None:
        intent = analyze_processing_intent("橙汁清洗参数", {"variety": "甜橙"})
        chunk = evidence(
            "residue-table",
            "Residual behavior during orange juice washing",
            (
                "Storage time affected orange juice quality: total phenols 0.700 d ± 0.040, "
                "while unwashed fruit was 0.771 c ± 0.032; different letters indicate "
                "significant differences. 表中字母表示差异显著性分组。"
            ),
            section="结果",
        )

        records = extract_processing_parameters([chunk], intent)

        self.assertFalse(any(item["parameter_name"] == "时间" for item in records))

    def test_invalid_search_typeerror_is_not_retried_as_legacy_signature(self) -> None:
        intent = analyze_processing_intent("橙汁怎样加工", {"variety": "甜橙"})
        calls = 0

        def broken_search(query, product_filter, top_k, **kwargs):
            nonlocal calls
            calls += 1
            raise TypeError("internal search failure")

        with self.assertRaisesRegex(TypeError, "internal search failure"):
            retrieve_processing_evidence(intent, search_fn=broken_search)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
