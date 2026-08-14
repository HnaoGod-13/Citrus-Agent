from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "main.py"


def sample_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 32), (240, 120, 40)).save(output, format="PNG")
    return output.getvalue()


class SidebarImageResetTests(unittest.TestCase):
    def run_app(self) -> AppTest:
        app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
        self.assertEqual([], list(app.exception))
        return app

    def upload_image(self, app: AppTest) -> None:
        app.get("file_uploader")[0].upload(
            "orange.png",
            sample_png(),
            "image/png",
        ).run()
        self.assertEqual([], list(app.exception))
        self.assertIsNotNone(app.get("file_uploader")[0].value)

    def test_delete_button_rebuilds_the_file_uploader(self) -> None:
        app = self.run_app()
        self.upload_image(app)

        app.button(key="remove_uploaded_image_0").click().run()

        self.assertEqual([], list(app.exception))
        self.assertIsNone(app.get("file_uploader")[0].value)
        self.assertNotIn("remove_uploaded_image_0", [button.key for button in app.button])

    def test_new_conversation_also_clears_the_uploaded_image(self) -> None:
        app = self.run_app()
        self.upload_image(app)
        app.session_state.last_vision_context = {
            "variety_candidate": "普通甜橙",
            "variety_confidence": "低",
        }
        new_chat_index = next(
            index
            for index, button in enumerate(app.button)
            if button.label == "＋ 新建对话"
        )

        app.button[new_chat_index].click().run()

        self.assertEqual([], list(app.exception))
        self.assertIsNone(app.get("file_uploader")[0].value)
        self.assertIsNone(app.session_state.last_vision_context)
        self.assertNotIn("remove_uploaded_image_0", [button.key for button in app.button])

    def test_completed_message_reset_clears_the_uploaded_image(self) -> None:
        app = self.run_app()
        self.upload_image(app)

        app.session_state.clear_sidebar_inputs = True
        app.run()

        self.assertEqual([], list(app.exception))
        self.assertIsNone(app.get("file_uploader")[0].value)
        self.assertNotIn("remove_uploaded_image_0", [button.key for button in app.button])

    def test_invalid_replacement_does_not_reuse_the_previous_image(self) -> None:
        app = self.run_app()
        self.upload_image(app)

        app.get("file_uploader")[0].upload(
            "broken.png",
            b"not-a-valid-image",
            "image/png",
        ).run()

        self.assertEqual([], list(app.exception))
        self.assertNotIn("sidebar_draft_image_bytes", app.session_state)
        self.assertNotIn("sidebar_draft_image_mime_type", app.session_state)
        self.assertNotIn("sidebar_draft_image_name", app.session_state)
        self.assertNotIn("remove_uploaded_image_0", [button.key for button in app.button])


if __name__ == "__main__":
    unittest.main()
