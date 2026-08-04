import unittest

from agent import orchestrator
from app.main import EXAMPLE_CARDS, EXAMPLE_PROMPTS


class ExampleWorkflowTests(unittest.TestCase):
    def test_home_page_has_four_distinct_examples(self):
        self.assertEqual(4, len(EXAMPLE_CARDS))
        self.assertEqual(4, len(EXAMPLE_PROMPTS))
        self.assertEqual(4, len({card["title"] for card in EXAMPLE_CARDS}))
        self.assertEqual(EXAMPLE_PROMPTS, [card["prompt"] for card in EXAMPLE_CARDS])

    def test_every_example_enters_the_full_agent_workflow(self):
        for card in EXAMPLE_CARDS:
            with self.subTest(card=card["title"]):
                prompt = card["prompt"]
                missing = orchestrator.missing_batch_inputs(prompt)
                self.assertEqual([], missing)
                self.assertTrue(
                    orchestrator.should_run_tools(
                        prompt,
                        has_minimum_batch_data=not missing,
                    )
                )

    def test_every_example_explains_the_end_to_end_experience(self):
        required_terms = ("完整运行Agent工作流程", "文献", "质控", "报告")
        for card in EXAMPLE_CARDS:
            with self.subTest(card=card["title"]):
                for term in required_terms:
                    self.assertIn(term, card["prompt"])


if __name__ == "__main__":
    unittest.main()
