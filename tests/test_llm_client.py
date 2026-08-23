from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from agent.llm_client import (
    DeepSeekAPIError,
    build_general_chat_messages,
    chat_with_deepseek,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def completion(content: str | None, *, finish_reason: str = "stop") -> FakeResponse:
    return FakeResponse(
        {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {
                        "content": content,
                        "reasoning_content": "internal reasoning must stay private",
                    },
                }
            ]
        }
    )


class DeepSeekCompletionTests(unittest.TestCase):
    def test_general_prompt_keeps_reported_values_but_blocks_parameter_recommendations(self) -> None:
        messages = build_general_chat_messages([], "介绍一篇橙汁加工研究", evidence=[])
        system_prompt = messages[0]["content"]
        self.assertIn("原文报告值", system_prompt)
        self.assertIn("推荐参数", system_prompt)
        self.assertIn("严禁改写", system_prompt)

    def test_nonempty_thinking_answer_is_returned_without_retry(self) -> None:
        with patch(
            "agent.llm_client.urllib.request.urlopen",
            return_value=completion("最终回答"),
        ) as urlopen:
            answer = chat_with_deepseek(
                "test-key",
                [{"role": "user", "content": "问题"}],
            )

        self.assertEqual("最终回答", answer)
        self.assertEqual(1, urlopen.call_count)

    def test_blank_thinking_answer_retries_without_thinking(self) -> None:
        with patch(
            "agent.llm_client.urllib.request.urlopen",
            side_effect=[
                completion("", finish_reason="length"),
                completion("基于文献的最终回答"),
            ],
        ) as urlopen:
            answer = chat_with_deepseek(
                "test-key",
                [{"role": "user", "content": "问题"}],
            )

        self.assertEqual("基于文献的最终回答", answer)
        self.assertEqual(2, urlopen.call_count)
        first_payload = json.loads(urlopen.call_args_list[0].args[0].data.decode("utf-8"))
        retry_payload = json.loads(urlopen.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertEqual({"type": "enabled"}, first_payload["thinking"])
        self.assertGreaterEqual(first_payload["max_tokens"], 8000)
        self.assertEqual({"type": "disabled"}, retry_payload["thinking"])
        self.assertNotIn("reasoning_effort", retry_payload)

    def test_two_blank_answers_raise_without_exposing_reasoning(self) -> None:
        with patch(
            "agent.llm_client.urllib.request.urlopen",
            side_effect=[completion(""), completion(None, finish_reason="length")],
        ):
            with self.assertRaises(DeepSeekAPIError) as raised:
                chat_with_deepseek(
                    "test-key",
                    [{"role": "user", "content": "问题"}],
                )

        self.assertIn("未返回可展示的最终回答", str(raised.exception))
        self.assertNotIn("internal reasoning", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
