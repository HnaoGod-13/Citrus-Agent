from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

import pillow_heif
from PIL import Image

from agent.vision_client import (
    MAX_MODEL_IMAGE_BYTES,
    SUPPORTED_UPLOAD_EXTENSIONS,
    VisionAPIError,
    normalize_vision_result,
    prepare_image_for_vision,
)
from agent.llm_client import build_chat_messages
from agent.orchestrator import (
    build_vision_memory,
    ensure_vision_status_consistency,
    ensure_vision_follow_up_answer,
    recover_vision_memory_from_messages,
    resolve_vision_follow_up,
    run_vision_turn,
    should_answer_with_vision_only,
    should_request_batch_data,
    should_run_tools,
)


def image_bytes(image: Image.Image, image_format: str) -> bytes:
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


class ImageFormatCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rgb = Image.new("RGB", (96, 72), (242, 132, 24))
        self.rgba = Image.new("RGBA", (96, 72), (242, 132, 24, 160))

    def test_common_pillow_formats_are_normalized_to_model_jpeg(self) -> None:
        cases = {
            "JPEG": self.rgb,
            "PNG": self.rgba,
            "WEBP": self.rgba,
            "BMP": self.rgb,
            "GIF": self.rgba,
            "TIFF": self.rgba,
            "PPM": self.rgb,
            "TGA": self.rgb,
            "DDS": self.rgb,
            "PCX": self.rgb,
            "SGI": self.rgb,
            "ICO": self.rgba,
            "JPEG2000": self.rgb,
            "AVIF": self.rgba,
        }
        for image_format, image in cases.items():
            with self.subTest(image_format=image_format):
                prepared = prepare_image_for_vision(
                    image_bytes(image, image_format),
                    filename=f"sample.{image_format.lower()}",
                )
                self.assertEqual(prepared.mime_type, "image/jpeg")
                self.assertTrue(prepared.data.startswith(b"\xff\xd8"))
                self.assertLessEqual(len(prepared.data), MAX_MODEL_IMAGE_BYTES)
                if image_format == "ICO":
                    self.assertGreaterEqual(min(prepared.width, prepared.height), 10)
                else:
                    self.assertEqual((prepared.width, prepared.height), image.size)

    def test_heic_is_supported_through_server_side_conversion(self) -> None:
        output = io.BytesIO()
        pillow_heif.from_pillow(self.rgb).save(output)
        prepared = prepare_image_for_vision(
            output.getvalue(),
            filename="sample.heic",
            mime_type="image/heic",
        )
        self.assertEqual(prepared.source_format, "HEIF")
        self.assertEqual(prepared.mime_type, "image/jpeg")
        self.assertIn("已自动转为 JPEG", "；".join(prepared.notes))

    def test_animated_gif_uses_first_frame_and_reports_it(self) -> None:
        output = io.BytesIO()
        frames = [
            Image.new("RGB", (64, 64), "orange"),
            Image.new("RGB", (64, 64), "green"),
        ]
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
        )
        prepared = prepare_image_for_vision(output.getvalue(), filename="animated.gif")
        self.assertEqual(prepared.frame_count, 2)
        self.assertIn("仅分析第一帧", "；".join(prepared.notes))

    def test_invalid_or_too_small_files_are_rejected_before_model_call(self) -> None:
        with self.assertRaises(VisionAPIError):
            prepare_image_for_vision(b"not-an-image", filename="fake.png")
        with self.assertRaises(VisionAPIError):
            prepare_image_for_vision(image_bytes(Image.new("RGB", (9, 20)), "PNG"))

    def test_frontend_extension_list_covers_modern_and_legacy_formats(self) -> None:
        expected = {
            "jpg",
            "png",
            "webp",
            "bmp",
            "gif",
            "tiff",
            "heic",
            "heif",
            "avif",
            "jp2",
            "ico",
            "ppm",
            "tga",
            "dds",
            "pcx",
            "sgi",
        }
        self.assertTrue(expected.issubset(set(SUPPORTED_UPLOAD_EXTENSIONS)))

    def test_vision_result_keeps_direct_answer_to_user_question(self) -> None:
        result = normalize_vision_result(
            {
                "外观描述": "图中果实颜色偏成熟，表皮完整。",
                "针对用户问题的回答": "从图片可见信息看，未发现明显破损。",
                "风险提示": [],
            }
        )
        self.assertEqual(result["answer"], "从图片可见信息看，未发现明显破损。")
        self.assertTrue(result["image_received"])
        self.assertEqual(result["analysis_status"], "success")

    def test_variety_question_with_image_routes_only_to_vision(self) -> None:
        prompt = "看看我上传的图片属于什么柑橘品种"
        self.assertTrue(should_answer_with_vision_only(prompt, has_image=True))
        self.assertFalse(
            should_run_tools(
                prompt,
                has_image=True,
                has_minimum_batch_data=True,
            )
        )
        self.assertFalse(should_request_batch_data(prompt, has_image=True))

    def test_explicit_processing_request_with_image_keeps_decision_route(self) -> None:
        prompt = "请根据这张图片给出加工方向、完整流程和质控方案"
        self.assertFalse(should_answer_with_vision_only(prompt, has_image=True))
        self.assertTrue(
            should_run_tools(
                prompt,
                has_image=True,
                has_minimum_batch_data=True,
            )
        )

    def test_successful_vision_result_removes_false_missing_image_claim(self) -> None:
        answer = (
            "我这边没有收到针对你上传的图片做图像识别或品种分析的调用结果，因此无法判断。"
            "从外观上看果皮颜色均匀。"
        )
        corrected = ensure_vision_status_consistency(
            answer,
            {
                "answer": "该果实疑似甜橙，但无法仅凭外观确定具体品种。",
                "appearance_description": "果皮颜色均匀。",
            },
        )
        self.assertIn("图片接收状态：已接收", corrected)
        self.assertNotIn("没有收到", corrected)
        self.assertIn("果皮颜色均匀", corrected)

    def test_analysis_context_states_successful_vision_status(self) -> None:
        result = {
            "batch": {},
            "scores": [],
            "quality_risks": [],
            "evidence": [],
            "next_actions": [],
            "processing_plan": {},
            "report": "",
            "image_observation": "果皮橙色，表面完整。",
            "vision_status": "success",
            "vision_answer": "疑似甜橙，具体品种需结合产地确认。",
            "vision_error": "",
        }
        content = "\n".join(
            item["content"]
            for item in build_chat_messages(result, [], "根据图片评估加工方向")
        )
        self.assertIn("已接收图片，并已完成视觉模型分析", content)
        self.assertIn("禁止声称“未收到图片", content)

    def test_visual_variety_is_saved_and_resolves_this_variety_follow_up(self) -> None:
        result = normalize_vision_result(
            {
                "外观描述": "果实橙黄色，果皮光滑。",
                "针对用户问题的回答": "该果实疑似为普通甜橙（如纽荷尔橙），具体品系需结合来源确认。",
                "风险提示": [],
            }
        )
        memory = build_vision_memory({"vision_result": result})
        self.assertEqual(memory["variety_candidate"], "普通甜橙")

        resolved = resolve_vision_follow_up("这个品种适合怎样加工", memory)
        self.assertIn("普通甜橙", resolved)
        self.assertIn("上一轮视觉答复", resolved)
        self.assertIn("不要再次要求用户重复品种名称", resolved)

    def test_visual_memory_can_be_recovered_from_existing_chat_messages(self) -> None:
        memory = recover_vision_memory_from_messages(
            [
                {
                    "role": "user",
                    "content": "这是什么品种",
                    "image_bytes": b"test-image",
                },
                {
                    "role": "assistant",
                    "content": "图片接收状态：已接收。根据图片判断疑似为普通甜橙。",
                },
                {"role": "user", "content": "这个品种适合怎样加工"},
            ]
        )
        self.assertEqual(memory["variety_candidate"], "普通甜橙")

    def test_follow_up_answer_cannot_ask_for_the_known_candidate_again(self) -> None:
        memory = {
            "variety_candidate": "普通甜橙",
            "variety_confidence": "低",
        }
        answer = (
            "为了更好地给出加工建议，需要先明确你提到的“这个品种”具体是什么柑橘品种。"
            "请提供品种名称。"
        )
        corrected = ensure_vision_follow_up_answer(
            answer,
            "这个品种适合怎样加工",
            memory,
        )
        self.assertIn("这个品种”指候选“普通甜橙", corrected)
        self.assertNotIn("请提供品种", corrected)
        self.assertIn("仍需补充产地、糖酸、水分和检测状态", corrected)

    def test_user_interface_does_not_render_raw_vision_json(self) -> None:
        source = Path("app/main.py").read_text(encoding="utf-8-sig")
        self.assertNotIn("st.json(", source)

    @patch("agent.orchestrator.recognize_citrus_image")
    def test_direct_vision_turn_passes_the_user_question_and_uses_the_image_answer(self, recognize) -> None:
        recognize.return_value = {
            "answer": "图片显示果皮完整。",
            "appearance_description": "果皮完整，颜色偏成熟。",
            "risk_notes": [],
        }
        payload = run_vision_turn(
            "请按照图片分析外观",
            b"\xff\xd8test-image",
            "image/jpeg",
        )
        recognize.assert_called_once_with(
            b"\xff\xd8test-image",
            "image/jpeg",
            user_prompt="请按照图片分析外观",
        )
        self.assertIn("图片显示果皮完整", payload["answer"])
        self.assertIn("图片中可见外观", payload["answer"])
        self.assertIn("图片接收状态：已接收", payload["answer"])


if __name__ == "__main__":
    unittest.main()
