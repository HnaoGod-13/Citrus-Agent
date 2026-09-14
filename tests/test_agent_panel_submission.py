from io import BytesIO

from PIL import Image
from streamlit.testing.v1 import AppTest


PANEL_APP = '''
import streamlit as st
from unittest.mock import patch
from app import main
from app.ui import components

st.session_state.setdefault("product_view", "identity")
with st.sidebar:
    prompt, uploaded = components.render_agent_panel("identity")

def capture(*args, **kwargs):
    st.session_state.sent = {"prompt": args[0], "has_image": args[3],
                             "image": args[4], "mime": args[5]}

if prompt:
    with patch.object(main, "handle_prompt", side_effect=capture):
        main.submit_agent_panel_prompt(prompt, uploaded, "", "quick")
'''


def panel():
    return AppTest.from_string(PANEL_APP, default_timeout=30).run()


def send(app):
    next(button for button in app.button if button.label == "发送").click().run()
    assert not app.exception


def test_image_only_submission_reaches_vision_with_converted_image():
    app = panel()
    output = BytesIO()
    Image.new("RGB", (32, 32), (240, 120, 40)).save(output, format="PNG")
    app.get("file_uploader")[0].upload("orange.png", output.getvalue(), "image/png").run()
    assert "sent" not in app.session_state
    send(app)
    sent = app.session_state.sent
    assert sent["prompt"]
    assert sent["has_image"] is True
    assert sent["mime"] == "image/jpeg"
    assert sent["image"].startswith(b"\xff\xd8")
    assert app.query_params["view"] == ["chat"]


def test_invalid_image_keeps_page_and_does_not_start_text_only_request():
    app = panel()
    app.get("file_uploader")[0].upload("broken.png", b"not an image", "image/png").run()
    app.text_input[0].set_value("识别这张图")
    send(app)
    assert "sent" not in app.session_state
    assert app.session_state.product_view == "identity"
    assert app.error
    assert not app.query_params.get("view")


def test_text_only_submission_preserves_prompt():
    app = panel()
    app.text_input[0].set_value("  解释当前证据  ")
    send(app)
    assert app.session_state.sent["prompt"] == "解释当前证据"
    assert app.session_state.sent["has_image"] is False
    assert app.session_state.sent["image"] is None


def test_empty_submission_does_not_start_a_request():
    app = panel()
    send(app)
    assert "sent" not in app.session_state
