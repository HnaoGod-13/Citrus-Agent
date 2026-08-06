from __future__ import annotations

import base64
import hashlib
import html
import importlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import (
    llm_client,
    memory as agent_memory,
    memory_config,
    orchestrator,
    rag as agent_rag,
    report as agent_report,
    tools as agent_tools,
    vision_client,
    workflow,
)
from app import ui_components

agent_memory = importlib.reload(agent_memory)
llm_client = importlib.reload(llm_client)
agent_report = importlib.reload(agent_report)
agent_tools = importlib.reload(agent_tools)
workflow = importlib.reload(workflow)
orchestrator = importlib.reload(orchestrator)
vision_client = importlib.reload(vision_client)
DEEPSEEK_MODEL = llm_client.DEEPSEEK_MODEL
DeepSeekAPIError = llm_client.DeepSeekAPIError
build_general_chat_messages = llm_client.build_general_chat_messages
chat_with_deepseek = llm_client.chat_with_deepseek
get_deepseek_api_key = llm_client.get_deepseek_api_key
retrieve_general_literature = llm_client.retrieve_general_literature
get_vision_model = vision_client.get_vision_model
get_vision_api_key = vision_client.get_vision_api_key
prepare_image_for_vision = vision_client.prepare_image_for_vision
SUPPORTED_UPLOAD_EXTENSIONS = vision_client.SUPPORTED_UPLOAD_EXTENSIONS
STYLE_DIR = Path(__file__).resolve().parent / "styles"


@st.cache_resource(show_spinner=False)
def _get_memory_manager(storage_version: int) -> agent_memory.MemoryManager:
    del storage_version
    return agent_memory.MemoryManager()


def get_memory_manager() -> agent_memory.MemoryManager:
    return _get_memory_manager(agent_memory.MESSAGE_STORAGE_VERSION)


EXAMPLE_PROMPTS = [
    "我有一批产地新会、品种茶枝柑的鲜果，共800公斤：糖度10.5°Brix、酸度0.65%、果皮水分18%，果皮完整、颜色成熟，外观初检未见质量异常；农残未超标、重金属未超标、微生物未超标、黄曲霉毒素未检出，客户是茶饮品牌。请完整运行Agent工作流程：抽取批次信息、检索本地文献、比较整果、果肉、果皮、种子和副产物加工路线、评估质控风险，给出首选与备选方案、完整加工流程和可下载报告。",
    "我有一批产地赣南、品种脐橙的鲜果，共2000公斤：糖度12.2°Brix、酸度0.7%，果实完整、成熟度较一致，外观初检未见质量异常；农残未超标、重金属未超标、微生物未超标，客户是食品加工厂，目标是生产NFC果汁。请完整运行Agent工作流程：检索果汁加工文献和参数，评估原料适配性，生成从验收到榨汁、杀菌、灌装的完整工艺，列出质控风险、待小试参数、副产物利用方案和报告。",
    "我有一批产地新会、品种茶枝柑的鲜果，共1000公斤：糖度9.8°Brix、酸度0.8%、果皮水分20%，果皮完整但果径大小不一，外观初检未见质量异常；农残未超标、重金属未超标、微生物未超标，客户希望提高果皮价值。请完整运行Agent工作流程：检索本地文献并比较陈皮、果皮精油、果胶和黄酮路线，给出路线分级、完整加工工艺、关键参数证据、质控边界、副产物去向和报告。",
    "我有一批产地广西、品种沃柑的鲜果，共1500公斤：糖度13.0°Brix、酸度0.6%，外观颜色成熟、少量机械伤，霉变状况尚未人工复核；农残尚未检测、重金属尚未检测、微生物结果未提供，客户是食品加工厂，希望尽快排产果汁和果皮副产物。请完整运行Agent工作流程：检索文献、评估路线和质控风险，明确当前能否进入生产、必须补做的检测、条件性加工方案、完整工艺、人工放行节点和报告。",
]

EXAMPLE_CARDS = [
    {
        "eyebrow": "01 · 路线选择",
        "title": "最佳加工方向",
        "description": "比较果皮、果汁与果胶等路线",
        "prompt": EXAMPLE_PROMPTS[0],
    },
    {
        "eyebrow": "02 · 果汁生产",
        "title": "橙汁生产规划",
        "description": "生成工艺参数与质量控制方案",
        "prompt": EXAMPLE_PROMPTS[1],
    },
    {
        "eyebrow": "03 · 果皮增值",
        "title": "果皮价值提升",
        "description": "评估陈皮、精油与果胶路线",
        "prompt": EXAMPLE_PROMPTS[2],
    },
    {
        "eyebrow": "04 · 风险复核",
        "title": "批次风险复核",
        "description": "检查农残、重金属和微生物风险",
        "prompt": EXAMPLE_PROMPTS[3],
    },
]


def item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


ANALYSIS_PAYLOAD_VERSION = 1


def _json_serializable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_serializable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_serializable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
    return value


def _without_raw_model_output(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _without_raw_model_output(item)
            for key, item in value.items()
            if str(key) != "_raw_model_output"
        }
    if isinstance(value, (list, tuple)):
        return [_without_raw_model_output(item) for item in value]
    return _json_serializable(value)


def build_persisted_analysis_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Serialize enough of an analysis turn to render it identically after a rerun."""
    source = payload or {}
    result = source.get("result") or {}
    try:
        serialized_result = workflow.serialize_result(result)
    except (KeyError, TypeError, ValueError):
        serialized_result = result
    serialized_result = _json_serializable(serialized_result)
    if not isinstance(serialized_result, dict):
        serialized_result = {}
    batch = source.get("batch") or serialized_result.get("batch") or {}
    return {
        "version": ANALYSIS_PAYLOAD_VERSION,
        "result": serialized_result,
        "batch": _json_serializable(batch),
        "report_path": str(
            source.get("report_path") or serialized_result.get("report_path") or ""
        ),
        "summary": str(source.get("summary") or ""),
        "answer": str(
            source.get("answer")
            or source.get("llm_answer")
            or source.get("summary")
            or ""
        ).strip(),
        "vision_result": _without_raw_model_output(source.get("vision_result") or {}),
    }


def is_valid_persisted_analysis_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        version = int(value.get("version") or 0)
    except (TypeError, ValueError):
        return False
    result = value.get("result")
    report_path = value.get("report_path")
    if (
        version != ANALYSIS_PAYLOAD_VERSION
        or not isinstance(result, dict)
        or not isinstance(result.get("report"), str)
        or not isinstance(report_path, str)
        or not report_path.strip()
    ):
        return False
    for key in ("batch", "vision_result"):
        if key in value and not isinstance(value[key], dict):
            return False
    for key in ("agent_steps", "scores", "quality_risks", "evidence", "parameter_groups"):
        if key in result and not isinstance(result[key], list):
            return False
    for key in ("processing_plan", "parameterized_plan", "processing_intent", "batch"):
        if key in result and not isinstance(result[key], dict):
            return False
    return True


def restore_flattened_markdown(value: Any) -> str:
    """Recover readable blocks from legacy rows whose whitespace was collapsed."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if text.count("\n") >= 2:
        return text

    text = re.sub(r"\s*(<!--.*?-->)\s*", r"\n\n\1\n\n", text)
    text = re.sub(r"\s+(?=#{1,6}\s)", "\n\n", text)
    heading_titles = [
        "综合结论",
        "完整加工流程（方案）",
        "加工目标与适用性判断",
        "推荐工艺流程",
        "详细操作参数",
        "设备需求及替代设备",
        "质量控制、包装储藏与副产物",
        "当前批次事实",
        "文献证据及其适用边界",
        "推荐与备选方向",
        "质控风险与下一步",
        "本次引用文献",
    ]
    titles_pattern = "|".join(re.escape(title) for title in heading_titles)
    text = re.sub(
        rf"(?m)^(#{{1,6}}\s+(?:\d+(?:\.\d+)*\s+)?(?:{titles_pattern}))\s+",
        r"\1\n\n",
        text,
    )
    text = re.sub(
        r"(?m)^(####\s+\d{2}\s+[^#\n]+?)\s+(?=-\s)",
        r"\1\n\n",
        text,
    )
    text = re.sub(
        r"\s+(?=-\s+(?:\*\*|\[[^\]\n]+\]|[\u3400-\u9fffA-Za-z]))",
        "\n",
        text,
    )
    text = re.sub(r"(?<!-)\s+(?=\*\*[^*\n]{1,80}\*\*[：:])", "\n", text)
    text = re.sub(r"\s+(?=\|(?:[^|\n]+\|){2,}\s+\|\s*:?-{3})", "\n", text)
    text = re.sub(r"\|\s+\|(?=\s*(?:---|[^|\s]))", "|\n|", text)
    text = re.sub(
        r"\s+(参数设置理由与变化影响：)\s*",
        r"\n\n\1\n",
        text,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def restore_ui_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    restored: list[dict[str, Any]] = []
    seen_message_ids: set[str] = set()
    for row in rows:
        role = str(row.get("role") or "")
        message_type = str(row.get("message_type") or "chat")
        if role not in {"user", "assistant"} or message_type not in {"chat", "analysis"}:
            continue
        message_id = str(row.get("message_id") or "")
        if message_id and message_id in seen_message_ids:
            continue
        if message_id:
            seen_message_ids.add(message_id)
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        message: dict[str, Any] = {
            "role": role,
            "content": str(row.get("content") or ""),
            "message_id": message_id,
            "message_type": message_type,
            "run_id": metadata.get("run_id"),
            "audit_trace": metadata.get("audit_trace"),
        }
        if role == "assistant" and message_type == "analysis":
            snapshot = metadata.get("analysis_payload")
            if is_valid_persisted_analysis_payload(snapshot):
                message["kind"] = "analysis"
                message["payload"] = snapshot
            else:
                message["kind"] = "analysis_legacy"
                message["content"] = restore_flattened_markdown(message["content"])
        restored.append(message)
    return restored


def recover_legacy_analysis_payload(
    manager: agent_memory.MemoryManager,
    user_id: str,
    project_id: str,
    message: dict[str, Any],
) -> dict[str, Any] | None:
    """Rebuild an old analysis UI from its audited tool result when available."""
    run_id = str(
        message.get("run_id")
        or (message.get("audit_trace") or {}).get("run_id")
        or ""
    ).strip()
    if not run_id:
        return None
    try:
        run = manager.get_agent_run(run_id, user_id=user_id, project_id=project_id)
    except agent_memory.MemoryManagerError:
        return None
    if not isinstance(run, dict):
        return None

    report_root = workflow.REPORT_DIR.resolve()
    tool_calls = run.get("tool_calls")
    if not isinstance(tool_calls, list):
        return None
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        result_name = Path(str(call.get("result_ref") or "")).name
        if not result_name.endswith(".tools.json"):
            continue
        result_path = (report_root / result_name).resolve()
        if result_path.parent != report_root or not result_path.is_file():
            continue
        try:
            if result_path.stat().st_size > 5_000_000:
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict) or not isinstance(result.get("report"), str):
            continue
        report_name = result_name.removesuffix(".tools.json") + ".md"
        report_path = (report_root / report_name).resolve()
        state_updates = run.get("state_updates")
        referenced_files = (
            state_updates.get("referenced_files")
            if isinstance(state_updates, dict)
            else None
        )
        references = (
            referenced_files.get("add")
            if isinstance(referenced_files, dict)
            else None
        )
        if isinstance(references, list):
            for reference in references:
                candidate = Path(str(reference)).resolve()
                if candidate.suffix.lower() == ".md" and candidate.parent == report_root:
                    report_path = candidate
                    break
        try:
            if str(run.get("model_name") or "") == "controlled-local":
                answer = orchestrator.build_evidence_grounded_fallback(result, report_path, [])
                answer = orchestrator.ensure_primary_processing_flow(result, answer)
                answer = orchestrator.append_used_reference_index(
                    answer,
                    result.get("evidence", []),
                )
                answer = orchestrator.ensure_vision_status_consistency(answer, None)
            else:
                answer = restore_flattened_markdown(message.get("content") or "")
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            continue
        result["answer"] = answer
        return build_persisted_analysis_payload(
            {
                "result": result,
                "batch": result.get("batch") or {},
                "report_path": report_path,
                "summary": answer,
                "answer": answer,
            }
        )
    return None


def restore_latest_analysis_state(
    messages: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, str] | None]:
    for message in reversed(messages):
        if message.get("kind") != "analysis" or not isinstance(message.get("payload"), dict):
            continue
        payload = message["payload"]
        result = payload.get("result")
        if not isinstance(result, dict):
            continue
        batch = payload.get("batch") or result.get("batch")
        if not isinstance(batch, dict):
            batch = None
        vision_context = (
            orchestrator.build_vision_memory(payload) if payload.get("vision_result") else {}
        )
        return batch, result, vision_context or None
    return None, None, None


def persist_uploaded_image(
    manager: agent_memory.MemoryManager,
    user_id: str,
    project_id: str,
    image_bytes: bytes,
    image_mime_type: str,
) -> str:
    digest = hashlib.sha256(image_bytes).hexdigest()
    extension = ".png" if image_mime_type.lower() == "image/png" else ".jpg"
    root = (manager.db_path.parent / "files").resolve()
    scope_hash = hashlib.sha256(f"{user_id}\0{project_id}".encode("utf-8")).hexdigest()[:24]
    target_dir = (root / scope_hash).resolve()
    if root != target_dir and root not in target_dir.parents:
        raise agent_memory.MemoryStorageError("图片记忆路径超出允许目录。")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}{extension}"
    if not target.exists():
        target.write_bytes(image_bytes)
    return str(target)


def inject_style() -> None:
    """Load the ordered, scoped UI style modules on every Streamlit rerun."""
    css = ui_components.load_style_bundle(STYLE_DIR)
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_scroll_position_manager(*, restore: bool) -> None:
    """Preserve the reader's main-page position across the final answer rerun."""
    restore_requested = "true" if restore else "false"
    st.iframe(
        f"""
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                overflow: hidden;
                background: transparent;
            }}
        </style>
        <script>
        (() => {{
            const frame = window.frameElement;
            if (frame) {{
                frame.style.visibility = "hidden";
                frame.style.opacity = "0";
                frame.style.border = "0";
                frame.style.background = "transparent";
                frame.style.pointerEvents = "none";
                frame.setAttribute("aria-hidden", "true");
            }}

            const host = window.parent;
            const doc = host.document;
            const scroller = doc.querySelector(
                '[data-testid="stAppScrollToBottomContainer"], [data-testid="stMain"]'
            );
            if (!scroller) return;

            const storageKey = "citrus-agent:main-scroll-top";
            const managerKey = "__citrusAgentScrollManager";
            let manager = host[managerKey];

            if (!manager || manager.version !== 1) {{
                manager = {{
                    version: 1,
                    restoring: false,
                    userScrollUntil: 0,
                    scroller: null,
                    boundScroller: null,
                }};
                host[managerKey] = manager;

                manager.remember = () => {{
                    if (manager.restoring || !manager.scroller) return;
                    try {{
                        host.sessionStorage.setItem(storageKey, String(manager.scroller.scrollTop));
                    }} catch (_) {{
                        // Storage may be unavailable in a hardened browser; scrolling still works normally.
                    }}
                }};
                manager.markUserScroll = () => {{
                    manager.userScrollUntil = Date.now() + 1200;
                }};

                doc.addEventListener("pointerdown", (event) => {{
                    manager.markUserScroll();
                    const target = event.target;
                    if (target && typeof target.closest === "function" && target.closest("button")) {{
                        manager.remember();
                    }}
                }}, true);

                doc.addEventListener("keydown", (event) => {{
                    const target = event.target;
                    const isChatSubmit = event.key === "Enter"
                        && !event.shiftKey
                        && target
                        && typeof target.matches === "function"
                        && target.matches('[data-testid="stChatInputTextArea"]');
                    if (isChatSubmit) manager.remember();

                    if (["PageUp", "PageDown", "Home", "End", "ArrowUp", "ArrowDown", " "].includes(event.key)) {{
                        manager.markUserScroll();
                        host.setTimeout(manager.remember, 0);
                    }}
                }}, true);
            }}

            manager.scroller = scroller;
            if (manager.boundScroller !== scroller) {{
                scroller.addEventListener("wheel", manager.markUserScroll, {{ passive: true }});
                scroller.addEventListener("touchstart", manager.markUserScroll, {{ passive: true }});
                scroller.addEventListener("scroll", () => {{
                    if (!manager.restoring && Date.now() <= manager.userScrollUntil) manager.remember();
                }}, {{ passive: true }});
                manager.boundScroller = scroller;
            }}
            let hasSavedPosition = false;
            try {{
                hasSavedPosition = host.sessionStorage.getItem(storageKey) !== null;
            }} catch (_) {{
                // Storage availability is checked again by manager.remember().
            }}
            if (!hasSavedPosition) manager.remember();

            if ({restore_requested}) {{
                let savedPosition = Number.NaN;
                try {{
                    savedPosition = Number(host.sessionStorage.getItem(storageKey));
                }} catch (_) {{
                    // Ignore unavailable storage and retain Streamlit's default behavior.
                }}
                if (Number.isFinite(savedPosition)) {{
                    manager.restoring = true;
                    scroller.dispatchEvent(new WheelEvent("wheel", {{ bubbles: true, deltaY: -1 }}));
                    const restorePosition = () => {{
                        scroller.scrollTo({{
                            top: savedPosition,
                            left: scroller.scrollLeft,
                            behavior: "auto",
                        }});
                    }};
                    [0, 40, 120, 280, 600, 1000].forEach((delay) => host.setTimeout(restorePosition, delay));
                    host.setTimeout(() => {{
                        manager.restoring = false;
                        manager.remember();
                    }}, 1200);
                }}
            }}
        }})();
        </script>
        """,
        height=1,
        tab_index=-1,
    )


def image_uploader_key() -> str:
    version = int(st.session_state.get("image_uploader_version", 0))
    return f"uploaded_citrus_image_{version}"


def reset_uploaded_image() -> None:
    st.session_state.pop(image_uploader_key(), None)
    st.session_state.image_uploader_version = (
        int(st.session_state.get("image_uploader_version", 0)) + 1
    )


def reset_sidebar_inputs() -> None:
    reset_uploaded_image()
    st.session_state.pop("manual_observation", None)


def _query_value(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def _set_query_value(name: str, value: str) -> None:
    try:
        st.query_params[name] = value
    except Exception:
        pass


def _valid_identity_token(value: str, prefix: str) -> bool:
    return bool(re.fullmatch(rf"{prefix}_[A-Za-z0-9_-]{{12,80}}", value or ""))


def _authenticated_identity() -> str:
    configured = os.getenv("CITRUS_USER_ID", "").strip()
    if configured:
        return configured
    try:
        user = st.user
        if bool(getattr(user, "is_logged_in", False)):
            return str(user.get("email") or user.get("sub") or "").strip()
    except Exception:
        return ""
    return ""


def initialize_memory_identity() -> None:
    project_id = os.getenv("CITRUS_PROJECT_ID", "citrus-agent").strip() or "citrus-agent"
    session_config = {
        key: value
        for key, value in {
            "company_name": os.getenv("CITRUS_COMPANY_NAME", "").strip(),
            "business_unit": os.getenv("CITRUS_BUSINESS_UNIT", "").strip(),
        }.items()
        if value
    }
    authenticated = _authenticated_identity()
    raw_user_token = _query_value("uid")
    if authenticated:
        user_id = "user_" + hashlib.sha256(authenticated.encode("utf-8")).hexdigest()[:24]
    else:
        if not _valid_identity_token(raw_user_token, "u"):
            raw_user_token = f"u_{uuid4().hex}"
            _set_query_value("uid", raw_user_token)
        user_id = "anon_" + hashlib.sha256(raw_user_token.encode("utf-8")).hexdigest()[:24]

    session_id = str(st.session_state.get("memory_session_id") or _query_value("sid"))
    if not _valid_identity_token(session_id, "s"):
        session_id = f"s_{uuid4().hex}"
        _set_query_value("sid", session_id)

    st.session_state.memory_user_id = user_id
    st.session_state.memory_project_id = project_id
    st.session_state.memory_session_id = session_id
    manager = get_memory_manager()
    try:
        manager.ensure_session(
            user_id,
            session_id,
            project_id,
            config=session_config or None,
        )
    except agent_memory.MemoryIsolationError:
        session_id = f"s_{uuid4().hex}"
        st.session_state.memory_session_id = session_id
        _set_query_value("sid", session_id)
        manager.ensure_session(
            user_id,
            session_id,
            project_id,
            config=session_config or None,
        )

    if st.session_state.get("memory_restored_session") != session_id:
        if not st.session_state.agent_messages:
            rows = manager.restore_session_messages(user_id, session_id, project_id)
            restored = restore_ui_messages(rows)
            for message in restored:
                if message.get("kind") != "analysis_legacy":
                    continue
                try:
                    recovered_payload = recover_legacy_analysis_payload(
                        manager,
                        user_id,
                        project_id,
                        message,
                    )
                except (agent_memory.MemoryManagerError, OSError, TypeError, ValueError):
                    recovered_payload = None
                if recovered_payload:
                    message["kind"] = "analysis"
                    message["payload"] = recovered_payload
            st.session_state.agent_messages = restored
            current_batch, last_result, last_vision_context = restore_latest_analysis_state(
                restored
            )
            st.session_state.current_batch = current_batch
            st.session_state.last_result = last_result
            st.session_state.last_vision_context = last_vision_context
        st.session_state.memory_restored_session = session_id


def start_new_conversation() -> None:
    session_id = f"s_{uuid4().hex}"
    st.session_state.memory_session_id = session_id
    st.session_state.memory_restored_session = session_id
    _set_query_value("sid", session_id)
    get_memory_manager().ensure_session(
        st.session_state.get("memory_user_id", "anonymous"),
        session_id,
        st.session_state.get("memory_project_id", "citrus-agent"),
    )
    st.session_state.agent_messages = []
    st.session_state.current_batch = None
    st.session_state.last_result = None
    st.session_state.last_vision_context = None
    st.session_state.agent_progress_events = []
    reset_sidebar_inputs()


def init_state() -> None:
    st.session_state.setdefault("agent_messages", [])
    st.session_state.setdefault("current_batch", None)
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_vision_context", None)
    st.session_state.setdefault("clear_sidebar_inputs", False)
    st.session_state.setdefault("image_uploader_version", 0)
    st.session_state.setdefault("agent_progress_events", [])
    initialize_memory_identity()
    if st.session_state.clear_sidebar_inputs:
        reset_sidebar_inputs()
        st.session_state.clear_sidebar_inputs = False


def literature_database_ready() -> bool:
    return Path(agent_rag.LITERATURE_DB_PATH).exists()


def render_topbar(api_key: str) -> None:
    st.markdown(
        ui_components.topbar_html(
            task_name=ui_components.current_task_label(st.session_state.agent_messages),
            literature_ready=literature_database_ready(),
            text_model_ready=bool(api_key),
            vision_model_ready=bool(get_vision_api_key()),
        ),
        unsafe_allow_html=True,
    )


def render_sidebar(api_key: str) -> None:
    """Render navigation and truthful system status without input widgets."""
    with st.sidebar:
        with st.container(key="sidebar_brand"):
            st.markdown(ui_components.sidebar_brand_html(), unsafe_allow_html=True)

        with st.container(key="sidebar_new_task"):
            st.button(
                "＋ 新建对话",
                width="stretch",
                key="new_conversation",
                on_click=start_new_conversation,
            )

        with st.container(key="sidebar_nav"):
            st.markdown(
                ui_components.sidebar_navigation_html(
                    recent_tasks=ui_components.recent_task_labels(
                        st.session_state.agent_messages
                    ),
                    literature_ready=literature_database_ready(),
                ),
                unsafe_allow_html=True,
            )

        with st.container(key="sidebar_footer"):
            st.markdown(
                ui_components.sidebar_system_status_html(
                    text_model=DEEPSEEK_MODEL,
                    text_model_ready=bool(api_key),
                    vision_model=get_vision_model(),
                    vision_model_ready=bool(get_vision_api_key()),
                ),
                unsafe_allow_html=True,
            )


def render_attachment_controls(
    container_key: str,
) -> tuple[str, bool, bytes | None, str]:
    """Render the existing upload contract beside the active composer."""
    prepared_image = None
    uploader_version = int(st.session_state.image_uploader_version)
    has_pending_upload = bool(st.session_state.get(image_uploader_key()))

    with st.container(key=container_key):
        with st.popover(
            "图片已添加" if has_pending_upload else "图片与外观说明",
            icon=":material/attach_file:",
            key=f"{container_key}_popover",
        ):
            st.markdown(
                """
                <div class="attachment-panel-title">图片与外观说明</div>
                <div class="attachment-panel-help">
                    支持单张柑橘图片。图片仅在提交本轮任务后调用视觉模型，
                    外观描述会作为人工观察一并纳入分析。
                </div>
                """,
                unsafe_allow_html=True,
            )
            uploaded_image = st.file_uploader(
                "上传柑橘图片",
                type=list(SUPPORTED_UPLOAD_EXTENSIONS),
                key=image_uploader_key(),
            )
            if uploaded_image:
                try:
                    prepared_image = prepare_image_for_vision(
                        uploaded_image.getvalue(),
                        filename=uploaded_image.name,
                        mime_type=uploaded_image.type,
                    )
                except vision_client.VisionAPIError as error:
                    st.error(str(error))
                else:
                    st.image(prepared_image.data, caption="图片预览", width="stretch")
                    st.markdown(
                        '<div class="attachment-preview-meta">'
                        "已完成本地格式与尺寸校验；提交后将调用 Qwen Vision。"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    st.button(
                        "删除图片",
                        width="stretch",
                        key=f"remove_uploaded_image_{uploader_version}",
                        on_click=reset_uploaded_image,
                    )

            manual_observation = st.text_area(
                "图片外观描述（可选）",
                placeholder="例如：果皮完整，颜色偏成熟，无明显霉斑或腐烂。",
                height=104,
                key="manual_observation",
            )

    image_bytes = prepared_image.data if prepared_image else None
    image_mime_type = prepared_image.mime_type if prepared_image else "image/jpeg"
    return (
        manual_observation,
        prepared_image is not None,
        image_bytes,
        image_mime_type,
    )



def render_tool_steps(result: dict[str, Any]) -> None:
    rows = []
    for index, step in enumerate(result.get("agent_steps", []), 1):
        name = html.escape(str(item_value(step, "name", "未命名步骤")))
        tool = html.escape(str(item_value(step, "tool", "未记录工具")))
        status = html.escape(str(item_value(step, "status", "未记录状态")))
        observation = html.escape(str(item_value(step, "observation", "暂无观察结果")))
        rows.append(
            '<div class="tool-step">'
            f'<div class="tool-step-index">{index}</div>'
            '<div>'
            f'<div class="tool-step-title">{name}</div>'
            '<div class="tool-step-meta">'
            f'<span class="tool-chip">{tool}</span>'
            f'<span class="tool-chip">{status}</span>'
            '</div>'
            f'<div class="tool-step-note">{observation}</div>'
            '</div>'
            '</div>'
        )

    if rows:
        st.markdown('<div class="tool-steps">' + "".join(rows) + "</div>", unsafe_allow_html=True)
    else:
        st.info("暂无工具调用轨迹。")


def render_score_bars(scores: list[Any], limit: int = 8) -> None:
    rows = []
    for item in scores[:limit]:
        direction = html.escape(str(item_value(item, "direction", "未命名方向")))
        reasons = [
            html.escape(str(reason))
            for reason in item_value(item, "reasons", [])
            if str(reason).strip()
        ]
        risk_notes = [
            html.escape(str(note))
            for note in item_value(item, "risk_notes", [])
            if str(note).strip()
        ]
        match_level = html.escape(str(item_value(item, "match_level", "待评估")))
        evidence_support = html.escape(str(item_value(item, "evidence_support", "未评估")))
        data_confidence = html.escape(str(item_value(item, "data_confidence", "低")))
        reason_text = "；".join(reasons) or "暂无"
        risk_text = "；".join(risk_notes) or "暂无"
        rows.append(
            '<div class="score-row">'
            '<div class="score-head">'
            f'<div class="score-name" title="{direction}">{direction}</div>'
            f'<div class="score-value">{match_level}</div>'
            '</div>'
            f'<div class="score-detail"><strong>文献支持：</strong>{evidence_support}</div>'
            f'<div class="score-detail"><strong>数据置信度：</strong>{data_confidence}</div>'
            f'<div class="score-detail"><strong>主要原因：</strong>{reason_text}</div>'
            f'<div class="score-detail"><strong>风险提示：</strong>{risk_text}</div>'
            '</div>'
        )

    if rows:
        st.markdown("<div class=\"score-bars\">" + "".join(rows) + "</div>", unsafe_allow_html=True)


def render_processing_plan(
    plan: dict[str, Any],
    *,
    anchor_suffix: str = "",
) -> None:
    if plan:
        st.markdown(
            ui_components.processing_plan_html(
                plan,
                anchor_suffix=anchor_suffix,
            ),
            unsafe_allow_html=True,
        )



def resolve_processing_plan(result: dict[str, Any]) -> dict[str, Any]:
    """Return the stored plan or rebuild it for analysis results created before this feature."""
    stored_plan = result.get("processing_plan")
    if isinstance(stored_plan, dict) and stored_plan.get("stages"):
        return stored_plan

    scores = result.get("scores", [])
    top = scores[0] if scores else None
    direction = item_value(top, "direction", "")
    if not direction:
        return {}

    rebuilt_plan = agent_report.build_processing_plan(
        result.get("batch", {}),
        str(direction),
        result.get("quality_risks", []),
        str(result.get("image_observation") or ""),
        result.get("evidence", []),
    )
    result["processing_plan"] = rebuilt_plan
    return rebuilt_plan


def _vision_value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    text = str(value or "").strip()
    return text or "无法判断"


def render_vision_result(vision_result: dict[str, Any]) -> None:
    st.success("图片已接收，并已完成视觉模型分析。")
    direct_answer = str(vision_result.get("answer") or "").strip()
    if direct_answer:
        st.markdown("**针对本轮问题**")
        st.write(direct_answer)

    appearance = str(vision_result.get("appearance_description") or "").strip()
    if appearance:
        st.markdown("**图片中可见外观**")
        st.write(appearance)

    structured = vision_result.get("structured_observation") or {}
    field_labels = [
        ("品种候选", "品种候选（仅外观初筛）"),
        ("品种判断置信度", "品种判断置信度"),
        ("颜色成熟度", "颜色与成熟度"),
        ("果皮完整度", "果皮完整度"),
        ("疑似霉斑", "是否见疑似霉斑"),
        ("疑似腐烂", "是否见疑似腐烂"),
        ("机械伤", "机械伤"),
        ("表面状态", "表面状态"),
    ]
    detail_lines = [
        f"- **{label}**：{_vision_value_text(structured.get(key))}"
        for key, label in field_labels
        if key in structured
    ]
    if detail_lines:
        st.markdown("**可见特征记录**\n\n" + "\n".join(detail_lines))

    for note in vision_result.get("risk_notes", []):
        st.warning(str(note))


def render_analysis_payload(
    payload: dict[str, Any],
    *,
    ui_key: str,
    anchor_suffix: str = "",
) -> None:
    result = payload.get("result") or {}
    report_path = Path(str(payload.get("report_path") or "analysis-report.md"))
    scores = result.get("scores", [])
    risks = result.get("quality_risks", [])
    evidence = result.get("evidence", [])
    processing_plan = resolve_processing_plan(result)

    summary = str(payload.get("summary") or "")
    if processing_plan and "完整加工流程（方案）" not in summary:
        summary = orchestrator.summarize_result(result, report_path)
    llm_answer = str(payload.get("llm_answer") or "").strip()
    if llm_answer.startswith("DeepSeek 总结失败"):
        llm_answer = ""
    answer = str(payload.get("answer") or llm_answer or summary).strip()
    answer = orchestrator.ensure_primary_processing_flow(result, answer)

    with st.container(key=f"analysis_layout_{ui_key}"):
        report_column, evidence_column = st.columns([3.35, 1], gap="large")

        with report_column:
            st.markdown(
                ui_components.decision_summary_html(
                    result,
                    processing_plan,
                    anchor_suffix=anchor_suffix,
                ),
                unsafe_allow_html=True,
            )

            if processing_plan:
                render_processing_plan(
                    processing_plan,
                    anchor_suffix=anchor_suffix,
                )
                parameterized_text = agent_report.parameterized_plan_markdown(
                    result.get("parameterized_plan") or {},
                    result.get("parameter_groups") or [],
                    result.get("processing_intent") or {},
                )
                parameterized_text = re.sub(
                    r"(?m)^### 5\.\d+\s+",
                    "### ",
                    parameterized_text,
                )
                with st.container(key=f"parameter_section_{ui_key}"):
                    st.markdown(
                        f'<span id="parameter-evidence{anchor_suffix}" '
                        'class="report-anchor"></span>'
                        '<div class="section-eyebrow">关键工艺参数</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(parameterized_text)

            narrative_answer = orchestrator.strip_primary_processing_flow(answer)
            if narrative_answer:
                with st.container(key=f"analysis_narrative_{ui_key}"):
                    st.markdown(narrative_answer)

            if payload.get("vision_result"):
                with st.expander("图片识别结果", expanded=True):
                    render_vision_result(payload["vision_result"])

            st.markdown(
                f'<span id="task-record{anchor_suffix}" '
                'class="report-anchor"></span>',
                unsafe_allow_html=True,
            )
            with st.expander("任务执行记录", expanded=False):
                render_tool_steps(result)

            st.markdown(
                f'<span id="risk-evidence{anchor_suffix}" '
                'class="report-anchor"></span>',
                unsafe_allow_html=True,
            )
            with st.expander("质量控制、风险与边界条件", expanded=False):
                if scores:
                    render_score_bars(scores)
                else:
                    st.info("暂无加工方向分级结果。")
                if risks:
                    risk_rows = []
                    for risk in risks:
                        level = html.escape(str(item_value(risk, "level", "提示")))
                        item_name = html.escape(str(item_value(risk, "item", "质控项")))
                        suggestion = html.escape(str(item_value(risk, "suggestion", "")))
                        severity_class = " high" if level == "高" else ""
                        risk_rows.append(
                            f'<div class="risk-item{severity_class}">'
                            f'<span class="risk-level">[{level}]</span>'
                            f"{item_name}：{suggestion}</div>"
                        )
                    st.markdown(
                        '<div class="risk-list">'
                        + "".join(risk_rows)
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="risk-empty">'
                        "暂未触发结构化高风险项，生产放行仍需人工复核。"
                        "</div>",
                        unsafe_allow_html=True,
                    )

            st.markdown(
                f'<span id="evidence-detail{anchor_suffix}" '
                'class="report-anchor"></span>',
                unsafe_allow_html=True,
            )
            with st.expander("文献与标准证据", expanded=False):
                if evidence:
                    for index, item in enumerate(evidence, 1):
                        title = item.get("title") or "未命名文献"
                        year = item.get("year") or "年份未知"
                        st.markdown(
                            f"**[证据 {index}] {title}（{year}）**"
                            f" · 匹配分 {item.get('match_score')}"
                        )
                        st.write(item.get("chunk_text"))
                        page_text = (
                            f"；页码：{item.get('page')}" if item.get("page") else ""
                        )
                        doi_text = (
                            f"；DOI：{item.get('doi')}" if item.get("doi") else ""
                        )
                        st.caption(
                            f"来源：{item.get('source')}；"
                            f"主题：{item.get('topic')}{page_text}{doi_text}"
                        )
                else:
                    st.info("没有检索到文献片段，请补充或重建文献库数据。")

            with st.expander("工艺参数证据", expanded=False):
                parameter_groups = result.get("parameter_groups") or []
                if parameter_groups:
                    rows = []
                    for item in parameter_groups:
                        rows.append(
                            {
                                "步骤": item.get("process_step"),
                                "参数": item.get("parameter_name"),
                                "推荐/报告值": item.get("recommended_range"),
                                "可信度": item.get("confidence_level"),
                                "原料/对象": item.get("raw_material"),
                                "规模": item.get("scale"),
                                "方法": item.get("process_method"),
                                "是否冲突": "是" if item.get("conflict") else "否",
                                "来源ID": "、".join(item.get("source_ids") or []),
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(rows),
                        width="stretch",
                        hide_index=True,
                    )
                    st.caption(
                        "单篇文献值不等于通用生产参数；请展开报告核对"
                        "适用条件、页码和原文片段。"
                    )
                else:
                    st.info(
                        "未提取到单位、适用条件和来源均完整的可靠工艺参数；"
                        "系统不会自动补写数值。"
                    )

            with st.expander("完整报告与导出", expanded=False):
                st.markdown(
                    '<span class="report-anchor"></span>',
                    unsafe_allow_html=True,
                )
                st.markdown(result.get("report") or "暂无报告内容。")
                st.download_button(
                    "下载 Markdown 报告",
                    data=result.get("report") or "",
                    file_name=report_path.name,
                    mime="text/markdown",
                    width="stretch",
                    key=f"download_{ui_key}_{report_path.name}",
                )
                st.caption(f"报告已保存到：{report_path}")

        with evidence_column:
            with st.container(key=f"analysis_evidence_panel_{ui_key}"):
                st.markdown(
                    ui_components.evidence_panel_html(
                        payload,
                        anchor_suffix=anchor_suffix,
                    ),
                    unsafe_allow_html=True,
                )



def _message_ui_key(message: dict[str, Any], message_index: int) -> str:
    source = "|".join(
        [
            str(message_index),
            str(message.get("message_id") or ""),
            str(message.get("kind") or ""),
            str(message.get("content") or "")[:500],
        ]
    )
    return f"{message_index}_{hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]}"


def render_message(
    message: dict[str, Any],
    *,
    message_index: int = 0,
    is_current_analysis: bool = True,
) -> None:
    role = message["role"]
    content_text = str(message.get("content", ""))
    ui_key = _message_ui_key(message, message_index)

    if message.get("kind") == "analysis":
        payload = message.get("payload") or {}
        result = payload.get("result") or {}
        detail_parts = ["已完成分析"]
        if payload.get("vision_result"):
            detail_parts.append("使用图像")
        if result.get("batch"):
            detail_parts.append("批次数据")
        if result.get("evidence"):
            detail_parts.append("文献证据")
        with st.container(key=f"analysis_message_{ui_key}"):
            st.markdown(
                '<div class="message-shell analysis-message-shell">'
                + ui_components.assistant_identity_html(
                    detail=" · ".join(detail_parts)
                )
                + "</div>",
                unsafe_allow_html=True,
            )
            render_analysis_payload(
                payload,
                ui_key=ui_key,
                anchor_suffix="" if is_current_analysis else f"-{ui_key}",
            )
        return

    if message.get("kind") == "analysis_legacy":
        with st.container(key=f"analysis_legacy_{ui_key}"):
            st.markdown(
                '<div class="message-shell analysis-message-shell">'
                + ui_components.assistant_identity_html(detail="历史分析记录")
                + "</div>",
                unsafe_allow_html=True,
            )
            st.markdown(restore_flattened_markdown(content_text))
        return

    if role == "user":
        attachment_markup = ""
        image_bytes = message.get("image_bytes")
        if image_bytes:
            image_mime_type = html.escape(
                str(message.get("image_mime_type") or "image/jpeg")
            )
            image_data = base64.b64encode(image_bytes).decode("ascii")
            attachment_markup = (
                '<div class="user-attachment-row">'
                f'<img class="user-attachment" '
                f'src="data:{image_mime_type};base64,{image_data}" '
                'alt="本轮上传图片">'
                "</div>"
            )
        content = html.escape(content_text).replace("\n", "<br>")
        st.markdown(
            '<div class="message-shell user-message-shell">'
            + attachment_markup
            + f'<div class="user-message-bubble">{content}</div>'
            + "</div>",
            unsafe_allow_html=True,
        )
        return

    with st.container(key=f"assistant_message_{ui_key}"):
        st.markdown(
            '<div class="message-shell assistant-message-shell">'
            + ui_components.assistant_identity_html()
            + "</div>",
            unsafe_allow_html=True,
        )
        # Keep ordinary assistant text on Streamlit's safe Markdown path.
        st.markdown(content_text)



def render_empty_state(
    api_key: str,
) -> tuple[
    str | None,
    str | None,
    tuple[str, bool, bytes | None, str],
    Any,
]:
    selected_prompt = None
    with st.container(key="welcome_view"):
        st.markdown(
            """
            <section class="welcome-shell">
                <div class="welcome-hero">
                    <div class="welcome-eyebrow">Citrus Decision Workspace</div>
                    <h1>柑橘产业链决策助手</h1>
                    <p>
                        基于图像、批次数据和文献证据，<br>
                        生成可追溯的加工与质量控制方案。
                    </p>
                </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

        if not api_key:
            st.warning(
                "DeepSeek API Key 尚未配置。仍可运行本地规则工具，"
                "但不能生成大模型总结。"
            )

        with st.container(key="welcome_composer"):
            attachment_values = render_attachment_controls(
                "welcome_attachment_bar"
            )
            typed_prompt = st.chat_input(
                "输入批次信息、生产目标或需要复核的问题…",
                key="welcome_chat_input",
            )
            st.markdown(
                """
                <div class="composer-mode-row">
                    <span>支持图片与外观说明</span>
                    <span><i></i>自动判断分析模式</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        progress_slot = st.empty()

        st.markdown(
            """
            <div class="task-section-header">
                <div>
                    <h2>常用任务</h2>
                    <p>从标准任务开始，提交前仍可补充批次信息。</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.container(key="task_grid"):
            for row_start in range(0, len(EXAMPLE_CARDS), 2):
                columns = st.columns(2, gap="medium")
                for card_index, (column, card) in enumerate(
                    zip(columns, EXAMPLE_CARDS[row_start : row_start + 2]),
                    start=row_start,
                ):
                    with column:
                        with st.container(key=f"task_card_{card_index}"):
                            st.markdown(
                                ui_components.task_card_html(
                                    card_index,
                                    title=card["title"],
                                    description=card["description"],
                                ),
                                unsafe_allow_html=True,
                            )
                            if st.button(
                                "开始任务",
                                width="stretch",
                                key=f"example_card_{card_index}",
                            ):
                                selected_prompt = card["prompt"]

    return selected_prompt, typed_prompt, attachment_values, progress_slot


def render_agent_progress(
    slot: Any,
    message: str,
    *,
    mode: str = "analysis",
) -> None:
    events = st.session_state.setdefault("agent_progress_events", [])
    normalized = str(message or "").strip()
    if normalized and (not events or events[-1] != normalized):
        events.append(normalized)
    slot.markdown(
        ui_components.agent_progress_html(events, mode=mode),
        unsafe_allow_html=True,
    )



def build_conversation_history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for item in messages:
        role = item.get("role")
        if item.get("kind") == "analysis":
            payload = item.get("payload") or {}
            content = str(
                payload.get("answer") or payload.get("llm_answer") or payload.get("summary") or ""
            ).strip()
            if content:
                history.append({"role": "assistant", "content": content})
            continue
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            history.append({"role": role, "content": content})
    return history


def run_general_turn(
    prompt: str,
    api_key: str,
    history: list[dict[str, str]],
    memory_context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    evidence = retrieve_general_literature(prompt, top_k=10, history=history)
    trace: dict[str, Any] = {
        "literature_ids": [
            str(item.get("chunk_id") or item.get("document_id") or item.get("source_file") or "")
            for item in evidence
            if item.get("chunk_id") or item.get("document_id") or item.get("source_file")
        ],
        "model_name": DEEPSEEK_MODEL if api_key else "local-evidence-fallback",
        "model_raw_output": "",
        "model_context_manifest": {},
        "error": "",
    }
    if not api_key:
        if evidence:
            lines = []
            for index, item in enumerate(evidence, 1):
                page = item.get("page") or item.get("page_start") or "未标注"
                excerpt = re.sub(r"\s+", " ", str(item.get("chunk_text") or "")).strip()
                lines.append(
                    f"{index}. {item.get('title') or '未命名文献'}（{item.get('year') or '年份未知'}，第{page}页）："
                    f"{excerpt[:260]}{'…' if len(excerpt) > 260 else ''}"
                )
            answer = (
                "已完成本地文献检索，但当前没有配置 DeepSeek API Key，因此先返回可回查的原文证据片段，"
                "暂不做超出片段的综合推断：\n\n" + "\n\n".join(lines)
            )
            return answer, trace
        return "若要普通大模型问答，请先配置 DeepSeek API Key；本轮也未检索到可直接返回的本地文献证据。", trace
    messages = build_general_chat_messages(
        history,
        prompt,
        memory_context=memory_context,
        evidence=evidence,
    )
    trace["model_context_manifest"] = agent_memory.describe_model_messages(messages)
    try:
        answer = chat_with_deepseek(api_key, messages)
        trace["model_raw_output"] = answer
        return answer, trace
    except DeepSeekAPIError as error:
        trace["error"] = str(error)
        return f"调用 DeepSeek 失败：{error}", trace

def build_working_memory_updates(
    prompt: str,
    missing_inputs: list[str],
    *,
    result: dict[str, Any] | None = None,
    vision_payload: dict[str, Any] | None = None,
    report_path: str = "",
) -> dict[str, Any]:
    result = result or {}
    batch = result.get("batch") or {}
    entities = {
        key: value
        for key, value in {
            "batch_id": batch.get("batch_id"),
            "origin": batch.get("origin"),
            "variety": batch.get("variety"),
            "customer_type": batch.get("customer_type"),
            "processing_goal": prompt[:500],
        }.items()
        if value not in (None, "")
    }
    vision_memory = orchestrator.build_vision_memory(vision_payload or {})
    if vision_memory.get("variety_candidate"):
        entities["vision_variety_candidate"] = vision_memory["variety_candidate"]
        entities.setdefault("variety", vision_memory["variety_candidate"])
        entities["vision_variety_confidence"] = vision_memory.get("variety_confidence")

    steps = result.get("agent_steps") or []
    tool_summaries = [
        f"{item_value(step, 'tool', '工具')}：{item_value(step, 'observation', '')}"
        for step in steps[-8:]
        if str(item_value(step, "observation", "")).strip()
    ]
    completed_steps = [
        str(item_value(step, "name", ""))
        for step in steps
        if str(item_value(step, "status", "")) in {"完成", "success", "completed"}
    ]
    constraints = [
        f"{item_value(risk, 'item', '风险项')}：{item_value(risk, 'suggestion', '需复核')}"
        for risk in (result.get("quality_risks") or [])[:8]
    ]
    constraints.extend(str(item) for item in (result.get("guardrail_issues") or [])[:8])
    references = [report_path] if report_path else []
    if result.get("tool_result_path"):
        references.append(str(result["tool_result_path"]))
    stored_image_path = str((vision_payload or {}).get("stored_image_path") or "")
    if stored_image_path:
        references.append(stored_image_path)
    references.extend(
        str(item.get("source_file") or item.get("doi") or item.get("document_id") or "")
        for item in (result.get("evidence") or [])[:12]
        if item.get("source_file") or item.get("doi") or item.get("document_id")
    )
    confirmed = []
    if re.search(r"(我确认|确认采用|决定采用|最终选择|就按这个|同意这个方案)", prompt):
        confirmed.append(prompt[:800])

    return {
        "current_goal": prompt[:1000],
        "current_stage": "等待补充输入" if missing_inputs else "本轮回答已完成",
        "domain": "柑橘",
        "entities": entities,
        "constraints": {"set": constraints},
        "confirmed_decisions": {"add": confirmed},
        "completed_steps": {"add": completed_steps},
        "pending_steps": {"set": [str(item) for item in (result.get("next_actions") or [])[:10]]},
        "required_inputs": {"set": list(missing_inputs)},
        "recent_tool_results": {"set": tool_summaries},
        "referenced_files": {"add": references},
    }


def finalize_memory_turn(
    *,
    manager: agent_memory.MemoryManager,
    user_id: str,
    session_id: str,
    project_id: str,
    prompt: str,
    assistant_message: dict[str, Any],
    assistant_text: str,
    mode: str,
    memory_context: dict[str, Any],
    missing_inputs: list[str],
    result: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    vision_payload: dict[str, Any] | None = None,
    general_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = result or {}
    payload = payload or {}
    general_trace = general_trace or {}
    sample_image_path = str(
        (vision_payload or {}).get("stored_image_path")
        or payload.get("stored_image_path")
        or ""
    )
    run_id = f"run_{uuid4().hex}"
    tool_calls: list[dict[str, Any]] = []
    batch_id = str((result.get("batch") or {}).get("batch_id") or "")

    for step in (result.get("agent_steps") or []) if mode == "analysis" else []:
        call = {
            "tool": str(item_value(step, "tool", "未命名工具")),
            "status": str(item_value(step, "status", "未记录")),
            "parameters": {"batch_id": batch_id} if batch_id else {},
            "result_summary": str(item_value(step, "observation", ""))[:1400],
            "result_ref": str(result.get("tool_result_path") or ""),
        }
        tool_calls.append(call)
        try:
            manager.record_message(
                user_id,
                session_id,
                project_id,
                "tool",
                call["result_summary"] or call["tool"],
                message_type="tool_result",
                tool_name=call["tool"],
                tool_result_id=f"tool_{uuid4().hex}",
                metadata={"run_id": run_id, "status": call["status"]},
            )
        except agent_memory.MemoryManagerError:
            pass

    if vision_payload:
        vision_result = vision_payload.get("vision_result") or {}
        vision_call = {
            "tool": "Qwen Vision",
            "status": vision_payload.get("vision_status") or "success",
            "parameters": {
                "input": str(vision_payload.get("stored_image_path") or "uploaded_image"),
                "question": prompt[:500],
            },
            "result_summary": str(vision_result.get("answer") or "")[:1400],
        }
        tool_calls.append(vision_call)
        try:
            manager.record_message(
                user_id,
                session_id,
                project_id,
                "tool",
                vision_call["result_summary"] or "视觉模型未返回可用摘要",
                message_type="tool_result",
                tool_name="Qwen Vision",
                tool_result_id=f"tool_{uuid4().hex}",
                metadata={"run_id": run_id, "status": vision_call["status"]},
            )
        except agent_memory.MemoryManagerError:
            pass

    report_path = str(payload.get("report_path") or "")
    state_updates = build_working_memory_updates(
        prompt,
        missing_inputs,
        result=result,
        vision_payload=vision_payload or payload,
        report_path=report_path,
    )
    saved_memory_ids: list[str] = []
    saved_sample_ids: list[str] = []
    memory_error = ""
    try:
        working = manager.update_working_memory(
            session_id,
            state_updates,
            user_id=user_id,
            project_id=project_id,
        )
        saved = manager.capture_long_term_from_turn(
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
            user_input=prompt,
            source_id=run_id,
        )
        saved_memory_ids.extend(str(item.get("memory_id")) for item in saved if item.get("memory_id"))

        scores = result.get("scores") or []
        batch = result.get("batch") or {}
        if mode == "analysis" and scores and (batch.get("origin") or batch.get("variety")):
            top = scores[0]
            tool_memory = manager.save_memory(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "project_id": project_id,
                    "memory_type": "tool_result",
                    "content": (
                        f"批次 {batch.get('batch_id') or '未命名'} 的加工分析："
                        f"首选方向为 {item_value(top, 'direction', '未确定')}；"
                        f"适配等级 {item_value(top, 'match_level', '待评估')}；"
                        f"报告位置 {report_path or '未保存'}。"
                    ),
                    "keywords": [
                        batch.get("origin"),
                        batch.get("variety"),
                        item_value(top, "direction", ""),
                    ],
                    "importance": 7,
                    "source": "agent_tool_result",
                    "source_id": run_id,
                    "metadata": {"batch_id": batch.get("batch_id"), "confirmed": False},
                }
            )
            if tool_memory.get("memory_id"):
                saved_memory_ids.append(str(tool_memory["memory_id"]))

            metrics = {
                key: batch.get(key)
                for key in [
                    "weight_kg",
                    "brix",
                    "acidity",
                    "moisture",
                    "pesticide_status",
                    "heavy_metal_status",
                    "microbe_status",
                    "aflatoxin_status",
                ]
                if batch.get(key) not in (None, "")
            }
            sample = manager.save_sample(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "project_id": project_id,
                    "variety": batch.get("variety"),
                    "origin": batch.get("origin"),
                    "time": batch.get("harvest_date"),
                    "maturity": (result.get("image_observation") or "")[:300],
                    "image_paths": [sample_image_path] if sample_image_path else [],
                    "disease_or_quality": "；".join(
                        (state_updates.get("constraints") or {}).get("set", [])
                    )[:1200],
                    "processing_goal": prompt[:1000],
                    "metrics": metrics,
                    "solution": (
                        f"{item_value(top, 'direction', '未确定')}；"
                        + orchestrator.summarize_processing_plan(result.get("processing_plan") or {})
                    )[:3000],
                    "outcome": "Agent 分析建议，实际生产结果尚未回填。",
                    "source": "agent_analysis_pending",
                    "confidence": 0.65 if len(metrics) >= 3 else 0.5,
                }
            )
            if sample.get("sample_id"):
                saved_sample_ids.append(str(sample["sample_id"]))
    except (agent_memory.MemoryManagerError, sqlite3.Error, OSError) as error:
        working = {}
        memory_error = str(error)

    literature_ids = [
        str(item.get("chunk_id") or item.get("document_id") or item.get("source_file") or "")
        for item in (result.get("evidence") or [])
        if item.get("chunk_id") or item.get("document_id") or item.get("source_file")
    ]
    literature_ids.extend(str(item) for item in general_trace.get("literature_ids") or [])
    literature_ids = list(dict.fromkeys(item for item in literature_ids if item))
    parameter_ids = list(
        dict.fromkeys(
            str(item.get("parameter_id") or "")
            for item in (result.get("process_parameters") or [])
            if item.get("parameter_id")
        )
    )
    memory_ids = list(
        dict.fromkeys(
            [
                *(memory_context.get("manifest", {}).get("memory_ids") or []),
                *saved_memory_ids,
            ]
        )
    )
    sample_ids = list(
        dict.fromkeys(
            [
                *(memory_context.get("manifest", {}).get("sample_ids") or []),
                *saved_sample_ids,
            ]
        )
    )
    model_context_manifest = (
        payload.get("model_context_manifest")
        or general_trace.get("model_context_manifest")
        or {}
    )
    context_manifest = {
        "memory": memory_context.get("manifest") or {},
        "model_messages": model_context_manifest,
        "context_token_budgets": memory_context.get("token_budgets") or {},
        "context_token_usage": memory_context.get("token_usage") or {},
        "mode": mode,
        "processing_subquestions": result.get("processing_subquestions") or [],
        "processing_intent": result.get("processing_intent") or {},
        "processing_parameter_ids": parameter_ids,
    }
    models: list[str] = []
    if general_trace.get("model_name"):
        models.append(str(general_trace["model_name"]))
    if payload.get("llm_answer") or payload.get("model_context_manifest"):
        models.append(DEEPSEEK_MODEL)
    if vision_payload:
        models.append(get_vision_model())
    model_name = " + ".join(dict.fromkeys(models)) or "controlled-local"
    raw_outputs = {
        key: value
        for key, value in {
            "general_text_model": general_trace.get("model_raw_output"),
            "analysis_text_model": payload.get("llm_answer"),
            "vision_model": ((vision_payload or {}).get("vision_result") or {}).get("_raw_model_output"),
        }.items()
        if value
    }
    model_raw_output = json.dumps(raw_outputs, ensure_ascii=False, default=str) if raw_outputs else ""
    error_text = str(general_trace.get("error") or memory_error or "")
    audit_trace = {
        "run_id": run_id,
        "model": model_name,
        "memory_ids": memory_ids,
        "sample_ids": sample_ids,
        "literature_ids": literature_ids,
        "parameter_ids": parameter_ids,
        "tool_count": len(tool_calls),
        "estimated_context_tokens": model_context_manifest.get("estimated_tokens", 0),
        "error": error_text,
    }
    assistant_message["message_id"] = f"msg_{uuid4().hex}"
    assistant_message["run_id"] = run_id
    assistant_message["audit_trace"] = audit_trace
    message_metadata: dict[str, Any] = {"run_id": run_id, "audit_trace": audit_trace}
    if mode == "analysis":
        message_metadata["analysis_payload"] = build_persisted_analysis_payload(payload)

    try:
        manager.record_message(
            user_id,
            session_id,
            project_id,
            "assistant",
            assistant_text,
            message_id=assistant_message["message_id"],
            message_type="analysis" if mode == "analysis" else "chat",
            metadata=message_metadata,
        )
        manager.summarize_history(
            session_id,
            user_id=user_id,
            project_id=project_id,
            force=False,
        )
        manager.log_agent_run(
            {
                "run_id": run_id,
                "user_id": user_id,
                "session_id": session_id,
                "project_id": project_id,
                "original_input": prompt,
                "system_prompt_version": memory_config.MEMORY_PROMPT_VERSION,
                "model_name": model_name,
                "context_manifest": context_manifest,
                "retrieved_memory_ids": memory_ids,
                "retrieved_literature_ids": literature_ids,
                "retrieved_sample_ids": sample_ids,
                "tool_calls": tool_calls,
                "model_raw_output": model_raw_output,
                "final_output": assistant_text,
                "state_updates": state_updates,
                "error": error_text,
            }
        )
    except (agent_memory.MemoryManagerError, sqlite3.Error, OSError) as error:
        audit_trace["error"] = str(error)
    return audit_trace



def handle_prompt(
    prompt: str,
    api_key: str,
    manual_observation: str,
    has_image: bool,
    image_bytes: bytes | None,
    image_mime_type: str,
    progress_slot: Any | None = None,
) -> None:
    manager = get_memory_manager()
    user_id = str(st.session_state.memory_user_id)
    session_id = str(st.session_state.memory_session_id)
    project_id = str(st.session_state.memory_project_id)
    history = build_conversation_history(st.session_state.agent_messages)
    user_message_id = f"msg_{uuid4().hex}"
    user_message: dict[str, Any] = {
        "role": "user",
        "content": prompt,
        "message_id": user_message_id,
    }
    memory_errors: list[str] = []
    stored_image_path = ""
    user_metadata: dict[str, Any] = {"has_image": bool(has_image and image_bytes)}
    if has_image and image_bytes:
        user_message["image_bytes"] = image_bytes
        user_message["image_mime_type"] = image_mime_type
        user_metadata.update(
            {
                "image_mime_type": image_mime_type,
                "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
                "image_size": len(image_bytes),
            }
        )
        try:
            stored_image_path = persist_uploaded_image(
                manager,
                user_id,
                project_id,
                image_bytes,
                image_mime_type,
            )
            user_metadata["stored_image_path"] = stored_image_path
        except (OSError, agent_memory.MemoryManagerError) as error:
            memory_errors.append(str(error))
    st.session_state.agent_messages.append(user_message)
    try:
        manager.record_message(
            user_id,
            session_id,
            project_id,
            "user",
            prompt,
            message_id=user_message_id,
            metadata=user_metadata,
        )
    except agent_memory.MemoryManagerError as error:
        memory_errors.append(str(error))

    importlib.reload(workflow)
    live_orchestrator = importlib.reload(orchestrator)
    if progress_slot is None:
        progress_slot = st.empty()
    st.session_state.agent_progress_events = []
    vision_memory = st.session_state.last_vision_context or live_orchestrator.recover_vision_memory_from_messages(
        st.session_state.agent_messages
    )
    if vision_memory:
        st.session_state.last_vision_context = vision_memory
    resolved_prompt = (
        prompt
        if has_image
        else live_orchestrator.resolve_vision_follow_up(prompt, vision_memory)
    )
    if has_image:
        st.session_state.last_vision_context = None
    references_current = (
        st.session_state.current_batch is not None
        and live_orchestrator.references_current_batch(resolved_prompt)
    )
    batch_for_turn = st.session_state.current_batch if references_current else None
    previous_observation = ""
    if references_current and st.session_state.last_result:
        previous_observation = str(st.session_state.last_result.get("image_observation") or "")
    effective_observation = manual_observation.strip() or previous_observation
    missing_inputs = live_orchestrator.missing_batch_inputs(
        resolved_prompt,
        current_batch=batch_for_turn,
        manual_observation=effective_observation,
        has_image=has_image,
    )
    should_answer_with_vision = live_orchestrator.should_answer_with_vision_only(
        resolved_prompt,
        has_image=has_image,
    )

    should_run_full_analysis = (
        not should_answer_with_vision
        and live_orchestrator.should_run_tools(
            resolved_prompt,
            has_image=has_image,
            has_current_batch=references_current,
            has_minimum_batch_data=not missing_inputs,
        )
    )

    is_previous_evidence_request = bool(
        references_current
        and st.session_state.last_result
        and live_orchestrator.references_previous_evidence(resolved_prompt)
    )

    # Mark the active task before retrieval so the model can resolve phrases such as
    # “这个品种” against both persisted state and recent raw turns.
    try:
        manager.update_working_memory(
            session_id,
            {
                "current_goal": prompt[:1000],
                "current_stage": "正在处理当前问题",
                "domain": "柑橘",
                "required_inputs": {"set": list(missing_inputs)},
            },
            user_id=user_id,
            project_id=project_id,
        )
        memory_context = manager.load_context(
            user_id,
            session_id,
            project_id,
            resolved_prompt,
            recent_messages=history,
        )
    except agent_memory.MemoryManagerError as error:
        memory_errors.append(str(error))
        memory_context = {}

    assistant_message: dict[str, Any]
    assistant_text = ""
    mode = "chat"
    result: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    vision_payload: dict[str, Any] = {}
    general_trace: dict[str, Any] = {}

    if is_previous_evidence_request:
        progress_slot.empty()
        assistant_text = live_orchestrator.build_previous_evidence_answer(st.session_state.last_result)
        result = st.session_state.last_result or {}
        assistant_message = {"role": "assistant", "content": assistant_text}
        mode = "previous_evidence"
    elif should_run_full_analysis:
        def update_progress(message: str) -> None:
            render_agent_progress(progress_slot, message)

        update_progress("正在启动批次分析流程")
        try:
            payload = live_orchestrator.run_analysis_turn(
                user_prompt=resolved_prompt,
                api_key=api_key,
                history=history,
                current_batch=batch_for_turn,
                manual_observation=effective_observation,
                has_image=has_image,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                progress_callback=update_progress,
                memory_context=memory_context,
            )
        except Exception as error:
            general_trace["error"] = str(error)
            assistant_text = f"本轮批次分析未能完成：{error}"
            assistant_message = {"role": "assistant", "content": assistant_text}
            mode = "analysis_error"
            progress_slot.empty()
        else:
            progress_slot.empty()
            st.session_state.current_batch = payload["batch"]
            st.session_state.last_result = payload["result"]
            result = payload["result"]
            if stored_image_path:
                payload["stored_image_path"] = stored_image_path
            assistant_text = str(payload.get("answer") or payload.get("summary") or "").strip()
            if payload.get("vision_result"):
                st.session_state.last_vision_context = live_orchestrator.build_vision_memory(payload)
            if has_image:
                vision_payload = payload
            assistant_message = {
                "role": "assistant",
                "kind": "analysis",
                "content": assistant_text,
                "payload": payload,
            }
            mode = "analysis"
    elif has_image and image_bytes:
        general_trace["model_name"] = get_vision_model()
        if stored_image_path:
            vision_payload["stored_image_path"] = stored_image_path
        render_agent_progress(
            progress_slot,
            "正在读取图片并回答本轮问题",
            mode="vision",
        )
        try:
            vision_payload = live_orchestrator.run_vision_turn(
                user_prompt=prompt,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            )
            if stored_image_path:
                vision_payload["stored_image_path"] = stored_image_path
            assistant_text = vision_payload["answer"]
            st.session_state.last_vision_context = live_orchestrator.build_vision_memory(vision_payload)
            if live_orchestrator.should_request_batch_data(
                resolved_prompt,
                current_batch=batch_for_turn,
                manual_observation=effective_observation,
                has_image=has_image,
            ):
                assistant_text += (
                    "\n\n图片已经纳入本轮分析。如需进一步生成加工路线分级和报告，"
                    + live_orchestrator.build_batch_data_request(missing_inputs)
                )
        except Exception as error:
            st.session_state.last_vision_context = None
            vision_payload["vision_status"] = "failed"
            assistant_text = f"图片已经收到，但视觉模型分析失败：{error}"
            general_trace["error"] = str(error)
        finally:
            progress_slot.empty()
        assistant_message = {
            "role": "assistant",
            "content": assistant_text,
            "vision_result": vision_payload.get("vision_result") or {},
        }
        mode = "vision"
    elif live_orchestrator.should_request_batch_data(
        resolved_prompt,
        current_batch=batch_for_turn,
        manual_observation=effective_observation,
        has_image=has_image,
    ):
        assistant_text = live_orchestrator.build_batch_data_request(missing_inputs)
        assistant_message = {"role": "assistant", "content": assistant_text}
        mode = "request_inputs"
    else:
        render_agent_progress(
            progress_slot,
            "正在全面检索本地文献并组织专业回答",
            mode="research",
        )
        try:
            assistant_text, general_trace = run_general_turn(
                resolved_prompt,
                api_key,
                history,
                memory_context=memory_context,
            )
            assistant_text = live_orchestrator.ensure_vision_follow_up_answer(
                assistant_text,
                prompt,
                vision_memory,
            )
        except Exception as error:
            general_trace["error"] = str(error)
            assistant_text = f"本轮检索或回答生成失败：{error}"
        finally:
            progress_slot.empty()
        assistant_message = {"role": "assistant", "content": assistant_text}

    if memory_errors:
        existing_error = str(general_trace.get("error") or "").strip()
        general_trace["error"] = "；".join(
            item for item in [existing_error, *memory_errors] if item
        )
    st.session_state.agent_messages.append(assistant_message)
    finalize_memory_turn(
        manager=manager,
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
        prompt=prompt,
        assistant_message=assistant_message,
        assistant_text=assistant_text,
        mode=mode,
        memory_context=memory_context,
        missing_inputs=missing_inputs,
        result=result,
        payload=payload,
        vision_payload=vision_payload,
        general_trace=general_trace,
    )

    st.session_state.clear_sidebar_inputs = True
    st.session_state.restore_main_scroll_position = True
    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="柑橘产业决策",
        page_icon="🍊",
        layout="wide",
        initial_sidebar_state="auto",
        menu_items={
            "Get Help": None,
            "Report a bug": None,
            "About": None,
        },
    )
    inject_style()
    init_state()
    restore_scroll_position = bool(
        st.session_state.pop("restore_main_scroll_position", False)
    )

    api_key = get_deepseek_api_key()
    render_sidebar(api_key)
    render_topbar(api_key)

    if not st.session_state.agent_messages:
        (
            selected_prompt,
            typed_prompt,
            attachment_values,
            progress_slot,
        ) = render_empty_state(api_key)
    else:
        selected_prompt = None
        progress_slot = None
        with st.container(key="conversation_stream"):
            st.markdown(
                '<span id="conversation-start" '
                'class="chat-transcript-start"></span>',
                unsafe_allow_html=True,
            )
            analysis_indices = [
                index
                for index, message in enumerate(st.session_state.agent_messages)
                if message.get("kind") == "analysis"
            ]
            current_analysis_index = (
                analysis_indices[-1] if analysis_indices else None
            )
            for message_index, message in enumerate(
                st.session_state.agent_messages
            ):
                render_message(
                    message,
                    message_index=message_index,
                    is_current_analysis=(
                        message_index == current_analysis_index
                    ),
                )

        attachment_values = render_attachment_controls(
            "composer_attachment_bar"
        )
        typed_prompt = st.chat_input(
            "输入问题，或粘贴批次信息开始分析…",
            key="conversation_chat_input",
        )

    (
        manual_observation,
        has_image,
        image_bytes,
        image_mime_type,
    ) = attachment_values
    render_scroll_position_manager(restore=restore_scroll_position)
    prompt = typed_prompt or selected_prompt
    if prompt:
        handle_prompt(
            prompt,
            api_key,
            manual_observation,
            has_image,
            image_bytes,
            image_mime_type,
            progress_slot=progress_slot,
        )



if __name__ == "__main__":
    main()
