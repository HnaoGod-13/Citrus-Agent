from __future__ import annotations

import unittest

from agent.llm_client import build_chat_messages, build_general_chat_messages
from agent.memory import build_memory_snapshot
from agent.orchestrator import (
    build_batch_data_request,
    default_batch,
    extract_batch_from_text,
    missing_batch_inputs,
    references_current_batch,
    references_previous_evidence,
    should_request_batch_data,
    should_run_tools,
)


SPARSE_TEMPLATE = "这批果皮完整、颜色偏成熟、无明显霉斑，农残和重金属还没做，适合做陈皮、陈皮丝还是果皮精油/果胶？"
COMPLETE_BATCH = "我有一批新会茶枝柑，糖度10.5，水分18%，客户是茶饮品牌，帮我判断加工方向并出报告。"
UNRELATED_QUESTION = "黄仁勋和马斯克的关系"


class BatchInputBoundaryTests(unittest.TestCase):
    def test_default_batch_does_not_invent_business_fields(self) -> None:
        batch = default_batch()
        self.assertEqual(batch["origin"], "")
        self.assertEqual(batch["variety"], "")
        self.assertEqual(batch["customer_type"], "")
        self.assertEqual(batch["harvest_date"], "")
        self.assertIsNone(batch["pesticide"])
        self.assertIsNone(batch["heavy_metal"])

    def test_sparse_template_requests_real_identity_instead_of_scoring(self) -> None:
        missing = missing_batch_inputs(SPARSE_TEMPLATE)
        self.assertTrue(any("产地或品种" in item for item in missing))
        self.assertTrue(should_request_batch_data(SPARSE_TEMPLATE))
        self.assertFalse(
            should_run_tools(
                SPARSE_TEMPLATE,
                has_minimum_batch_data=not missing,
            )
        )

    def test_complete_batch_can_run_tools(self) -> None:
        missing = missing_batch_inputs(COMPLETE_BATCH)
        self.assertEqual(missing, [])
        self.assertFalse(should_request_batch_data(COMPLETE_BATCH))
        self.assertTrue(
            should_run_tools(
                COMPLETE_BATCH,
                has_minimum_batch_data=True,
            )
        )

    def test_extraction_starts_blank_without_user_data(self) -> None:
        batch, observation, _ = extract_batch_from_text("请分析一下")
        self.assertEqual(batch["origin"], "")
        self.assertEqual(batch["variety"], "")
        self.assertEqual(batch["customer_type"], "")
        self.assertEqual(observation, "")

    def test_data_request_explicitly_rejects_template_memory(self) -> None:
        answer = build_batch_data_request(["产地或品种"])
        self.assertIn("不会用演示模板", answer)
        self.assertIn("不会生成推荐分数或报告", answer)


class ConversationIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history = [
            {"role": "user", "content": SPARSE_TEMPLATE},
            {"role": "assistant", "content": "旧批次结论：建议陈皮丝。"},
        ]

    def test_same_conversation_keeps_recent_history_even_for_new_topic(self) -> None:
        messages = build_general_chat_messages(self.history, UNRELATED_QUESTION)
        self.assertEqual([item["role"] for item in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(messages[-1]["content"], UNRELATED_QUESTION)
        self.assertIn(SPARSE_TEMPLATE, "\n".join(item["content"] for item in messages))
        self.assertIn("新话题时只回答新问题", messages[0]["content"])

    def test_explicit_follow_up_can_use_history(self) -> None:
        messages = build_general_chat_messages(self.history, "那这个结论为什么这样？")
        self.assertGreater(len(messages), 2)
        self.assertIn(SPARSE_TEMPLATE, "\n".join(item["content"] for item in messages))

    def test_current_prompt_is_removed_if_caller_accidentally_puts_it_in_history(self) -> None:
        prompt = "继续解释这个结论"
        messages = build_general_chat_messages(
            self.history + [{"role": "user", "content": prompt}],
            prompt,
        )
        self.assertEqual(sum(item.get("content") == prompt for item in messages), 1)

    def test_new_analysis_does_not_receive_unrelated_history(self) -> None:
        result = {
            "batch": default_batch(),
            "scores": [],
            "quality_risks": [],
            "evidence": [],
            "next_actions": [],
            "report": "",
        }
        messages = build_chat_messages(result, self.history, COMPLETE_BATCH)
        all_content = "\n".join(item["content"] for item in messages)
        self.assertNotIn("旧批次结论", all_content)
        self.assertEqual(messages[-1]["content"], COMPLETE_BATCH)

    def test_only_explicit_wording_references_current_batch(self) -> None:
        self.assertTrue(references_current_batch("继续分析刚才那批"))
        self.assertFalse(references_current_batch(UNRELATED_QUESTION))


class GeneralChatRoutingTests(unittest.TestCase):
    def test_reported_literature_numbers_do_not_request_batch_data(self) -> None:
        prompt = "总结这篇橙汁文献中报告的85℃和15秒"

        self.assertFalse(references_current_batch(prompt))
        self.assertFalse(should_request_batch_data(prompt))
        self.assertFalse(
            should_run_tools(
                prompt,
                has_current_batch=True,
                has_minimum_batch_data=True,
            )
        )

    def test_literature_synthesis_variants_stay_in_general_chat(self) -> None:
        prompts = [
            "摘要一下柑橘果汁杀菌论文",
            "归纳橙汁热处理研究的主要结论",
            "整理柑橘汁巴氏杀菌文献",
            "汇总柑橘精油提取研究",
            "梳理柑橘果胶提取相关文献",
            "概括这篇论文中报告的处理条件",
        ]

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(should_request_batch_data(prompt))
                self.assertFalse(
                    should_run_tools(
                        prompt,
                        has_current_batch=True,
                        has_minimum_batch_data=True,
                    )
                )

    def test_topic_literature_request_does_not_inherit_current_batch(self) -> None:
        prompt = "列出橙汁杀菌相关文献"

        self.assertFalse(references_previous_evidence(prompt))
        self.assertFalse(references_current_batch(prompt))

    def test_parameter_recommendation_still_requests_batch_data(self) -> None:
        for prompt in [
            "推荐杀菌温度",
            "请设定杀菌温度",
            "总结相关文献并推荐杀菌温度",
        ]:
            with self.subTest(prompt=prompt):
                self.assertTrue(should_request_batch_data(prompt))

    def test_parameter_recommendation_runs_tools_when_current_batch_is_complete(self) -> None:
        prompt = "请为这批设定杀菌温度"
        batch = default_batch()
        batch.update({"origin": "赣南", "variety": "脐橙", "brix": 11.5})
        missing = missing_batch_inputs(prompt, current_batch=batch)

        self.assertEqual([], missing)
        self.assertTrue(references_current_batch(prompt))
        self.assertFalse(should_request_batch_data(prompt, current_batch=batch))
        self.assertTrue(
            should_run_tools(
                prompt,
                has_current_batch=True,
                has_minimum_batch_data=True,
            )
        )


class ControlledMemoryTests(unittest.TestCase):
    def test_demo_cases_are_not_loaded_as_long_term_facts(self) -> None:
        snapshot = build_memory_snapshot(default_batch(), "", "不限")
        self.assertNotIn("demo_case_summaries", snapshot["long_term"])
        self.assertIn("data/literature/chunks.jsonl", snapshot["long_term"]["knowledge_sources"])
        self.assertNotIn("data/cases/demo_cases.json", snapshot["long_term"]["knowledge_sources"])


if __name__ == "__main__":
    unittest.main()
