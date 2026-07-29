from __future__ import annotations

import io
import unittest

import pillow_heif
from PIL import Image

from agent.vision_client import (
    MAX_MODEL_IMAGE_BYTES,
    SUPPORTED_UPLOAD_EXTENSIONS,
    VisionAPIError,
    prepare_image_for_vision,
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


if __name__ == "__main__":
    unittest.main()
