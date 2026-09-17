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


PANEL_WITH_HISTORY_APP = '''
import streamlit as st
from app.ui import components

st.session_state.industry_context_messages = [
    {"role": "user", "content": "还缺哪些资料？", "contextual": True},
    {"role": "assistant", "content": "请先补充产品类型与原料信息。", "contextual": True},
]
with st.sidebar:
    components.render_agent_panel("intake")
'''


CONTEXT_SCOPE_APP = '''
import streamlit as st
from app import main

st.session_state.product_view = "intake"
st.session_state.industry_task_context = {}
st.session_state.agent_messages = [
    {"role": "user", "content": "intake", "contextual": True, "context_view": "intake"},
    {"role": "assistant", "content": "decision", "contextual": True, "context_view": "decision"},
    {"role": "assistant", "content": "legacy", "contextual": True},
]
main.sync_industry_context_messages("intake")
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


def test_history_is_rendered_inside_conversation_below_agent_header():
    app = AppTest.from_string(PANEL_WITH_HISTORY_APP, default_timeout=30).run()
    assert not app.exception
    markup = "\n".join(str(item.value) for item in app.markdown)
    assert markup.index("agent-panel-brand") < markup.index("agent-context-card")
    assert markup.index("agent-context-card") < markup.index("agent-panel-conversation")
    assert "agent-inline-history" not in markup
    assert "agent-panel-message user" in markup
    assert "agent-panel-message assistant" in markup


def test_contextual_history_is_isolated_to_the_active_page():
    app = AppTest.from_string(CONTEXT_SCOPE_APP, default_timeout=30).run()
    assert not app.exception
    messages = app.session_state.industry_context_messages
    assert [message["content"] for message in messages] == ["intake"]
