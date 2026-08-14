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
from app.ui import components as ui_components
from app.ui.product_pages import render_product_page

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
prepare_image_for_vision = vision_client.prepare_image_for_vision
SUPPORTED_UPLOAD_EXTENSIONS = vision_client.SUPPORTED_UPLOAD_EXTENSIONS


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
        "title": "评估最佳加工方向",
        "title_en": "Evaluate Optimal Processing Direction",
        "description": "比较整果、果汁与果皮路线",
        "description_en": "Compare acidity, juice and peel routes",
        "icon": "activity",
        "prompt": EXAMPLE_PROMPTS[0],
    },
    {
        "eyebrow": "02 · 果汁生产",
        "title": "规划生产流程",
        "title_en": "Plan Production Process",
        "description": "规划阶段原料生产",
        "description_en": "Raw material planning and processing flow",
        "icon": "factory",
        "prompt": EXAMPLE_PROMPTS[1],
    },
    {
        "eyebrow": "03 · 果皮增值",
        "title": "提升果皮利用价值",
        "title_en": "Improve Peel Utilization Value",
        "description": "比较陈皮、精油与果胶路线",
        "description_en": "Compare dried peel, essential oil and pectin routes",
        "icon": "circle-yen",
        "prompt": EXAMPLE_PROMPTS[2],
    },
    {
        "eyebrow": "04 · 风险复核",
        "title": "复核批次生产风险",
        "title_en": "Review Risk & Compliance",
        "description": "明确补检与人工放行条件",
        "description_en": "Identify risk and ensure compliance",
        "icon": "shield",
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


def _restore_scoped_message_image(
    manager: agent_memory.MemoryManager,
    user_id: str,
    project_id: str,
    metadata: dict[str, Any],
) -> tuple[bytes, str] | None:
    """Read a persisted attachment only from this user's scoped file directory."""
    stored_path = str(metadata.get("stored_image_path") or "").strip()
    if not stored_path:
        return None
    try:
        root = (manager.db_path.parent / "files").resolve()
        scope_hash = hashlib.sha256(f"{user_id}\0{project_id}".encode("utf-8")).hexdigest()[:24]
        scoped_root = (root / scope_hash).resolve()
        candidate = Path(stored_path).resolve(strict=True)
        if scoped_root != candidate.parent and scoped_root not in candidate.parents:
            return None
        file_size = candidate.stat().st_size
        if file_size <= 0 or file_size > vision_client.MAX_UPLOAD_BYTES:
            return None
        expected_size = int(metadata.get("image_size") or 0)
        if expected_size and expected_size != file_size:
            return None
        image_bytes = candidate.read_bytes()
        expected_digest = str(metadata.get("image_sha256") or "").strip().lower()
        if expected_digest and hashlib.sha256(image_bytes).hexdigest() != expected_digest:
            return None
        mime_type = str(metadata.get("image_mime_type") or "").strip().lower()
        if mime_type not in {"image/jpeg", "image/png"}:
            mime_type = "image/png" if candidate.suffix.lower() == ".png" else "image/jpeg"
        return image_bytes, mime_type
    except (OSError, TypeError, ValueError):
        return None


def restore_ui_messages(
    rows: list[dict[str, Any]],
    *,
    manager: agent_memory.MemoryManager | None = None,
    user_id: str = "",
    project_id: str = "",
) -> list[dict[str, Any]]:
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
        if role == "user" and bool(metadata.get("has_image")):
            restored_image = (
                _restore_scoped_message_image(manager, user_id, project_id, metadata)
                if manager is not None and user_id and project_id
                else None
            )
            if restored_image:
                message["image_bytes"], message["image_mime_type"] = restored_image
            else:
                message["attachment_missing"] = True
        if role == "assistant" and isinstance(metadata.get("vision_result"), dict):
            message["vision_result"] = _without_raw_model_output(metadata["vision_result"])
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
    latest_batch: dict[str, Any] | None = None
    latest_result: dict[str, Any] | None = None
    latest_vision_context: dict[str, str] | None = None
    for message in reversed(messages):
        if latest_vision_context is None:
            if message.get("kind") == "analysis" and isinstance(message.get("payload"), dict):
                vision_source = message["payload"]
            elif isinstance(message.get("vision_result"), dict):
                vision_source = message["vision_result"]
            else:
                vision_source = {}
            if vision_source:
                recovered_vision = orchestrator.build_vision_memory(vision_source)
                latest_vision_context = recovered_vision or None

        if (
            latest_result is None
            and message.get("kind") == "analysis"
            and isinstance(message.get("payload"), dict)
        ):
            payload = message["payload"]
            result = payload.get("result")
            if isinstance(result, dict):
                batch = payload.get("batch") or result.get("batch")
                latest_batch = batch if isinstance(batch, dict) else None
                latest_result = result
        if latest_result is not None and latest_vision_context is not None:
            break
    return latest_batch, latest_result, latest_vision_context


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
    """Load the single product-wide visual system."""
    stylesheet = ROOT / "app" / "ui" / "design_system.css"
    st.markdown(
        f"<style>{stylesheet.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )


SCROLL_POSITION_MANAGER_INSTALLER = r"""
(() => {
    const installerKey = "__citrusAgentInstallScrollManager";
    const managerKey = "__citrusAgentScrollManager";
    const storageKey = "citrus-agent:main-scroll-top";
    const doc = window.document;

    const teardown = (manager) => {
        if (!manager) return;
        if (Array.isArray(manager.motionTimers)) {
            manager.motionTimers.forEach((timer) => window.clearTimeout(timer));
        }
        const boundScroller = manager.boundScroller || manager.scroller;
        if (boundScroller && manager.handleScroll) {
            boundScroller.removeEventListener("scroll", manager.handleScroll);
        }
        if (boundScroller && manager.markUserScroll) {
            boundScroller.removeEventListener("wheel", manager.markUserScroll);
            boundScroller.removeEventListener("touchstart", manager.markUserScroll);
        }
        if (manager.markUserScroll) {
            doc.removeEventListener("wheel", manager.markUserScroll, true);
            doc.removeEventListener("touchstart", manager.markUserScroll, true);
        }
        if (manager.handleUserInput) {
            doc.removeEventListener("wheel", manager.handleUserInput, true);
            doc.removeEventListener("touchstart", manager.handleUserInput, true);
        }
        if (manager.handlePointerDown) {
            doc.removeEventListener("pointerdown", manager.handlePointerDown, true);
        }
        if (manager.handleKeyDown) {
            doc.removeEventListener("keydown", manager.handleKeyDown, true);
        }

        manager.emptyResetActive = false;
        manager.restoring = false;
        manager.scroller = null;
        manager.boundScroller = null;
        manager.markUserScroll = () => {};
        manager.remember = () => {};
        manager.cancelMotion = () => {};
        manager.revealOnce = () => {};
    };

    const createManager = () => {
        const manager = {
            version: 4,
            restoring: false,
            userScrollUntil: 0,
            scroller: null,
            boundScroller: null,
            motionToken: 0,
            motionTimers: [],
            lastRevealId: null,
        };

        manager.cancelMotion = () => {
            manager.motionToken += 1;
            manager.motionTimers.forEach((timer) => window.clearTimeout(timer));
            manager.motionTimers = [];
            manager.restoring = false;
        };
        manager.scheduleMotion = (callback, delays, releaseDelay, onRelease = null) => {
            manager.cancelMotion();
            const token = manager.motionToken;
            manager.restoring = true;
            manager.motionTimers = delays.map((delay) => window.setTimeout(() => {
                if (manager.motionToken !== token || !manager.restoring) return;
                callback();
            }, delay));
            manager.motionTimers.push(window.setTimeout(() => {
                if (manager.motionToken !== token) return;
                manager.restoring = false;
                manager.motionTimers = [];
                if (typeof onRelease === "function") onRelease();
            }, releaseDelay));
        };
        manager.remember = () => {
            if (manager.restoring || !manager.scroller) return;
            try {
                window.sessionStorage.setItem(storageKey, String(manager.scroller.scrollTop));
            } catch (_) {
                // Storage may be unavailable in a hardened browser; scrolling still works normally.
            }
        };
        manager.handleUserInput = (event) => {
            if (event && event.isTrusted === false) return;
            manager.cancelMotion();
            manager.userScrollUntil = Date.now() + 1200;
        };
        manager.handlePointerDown = (event) => {
            manager.handleUserInput(event);
            const target = event.target;
            if (target && typeof target.closest === "function" && target.closest("button")) {
                manager.remember();
            }
        };
        manager.handleKeyDown = (event) => {
            const target = event.target;
            const isChatSubmit = event.key === "Enter"
                && !event.shiftKey
                && target
                && typeof target.matches === "function"
                && target.matches('[data-testid="stChatInputTextArea"]');
            if (isChatSubmit) manager.remember();

            if (["PageUp", "PageDown", "Home", "End", "ArrowUp", "ArrowDown", " "].includes(event.key)) {
                manager.handleUserInput(event);
                window.setTimeout(() => manager.remember(), 0);
            }
        };
        manager.handleScroll = () => {
            if (!manager.restoring && Date.now() <= manager.userScrollUntil) manager.remember();
        };
        manager.revealOnce = (revealId, selector) => {
            const marker = String(revealId || "");
            if (!marker || manager.lastRevealId === marker) return;
            manager.lastRevealId = marker;

            const reveal = () => {
                const scroller = manager.scroller || doc.querySelector(
                    '[data-testid="stAppScrollToBottomContainer"], [data-testid="stMain"]'
                );
                const target = selector ? doc.querySelector(selector) : null;
                if (!scroller || !target) return;

                const scrollerRect = scroller.getBoundingClientRect();
                const targetRect = target.getBoundingClientRect();
                const composer = doc.querySelector('[data-testid="stBottom"]');
                const composerRect = composer ? composer.getBoundingClientRect() : null;
                const topBoundary = Math.max(scrollerRect.top + 16, 64);
                const composerTop = composerRect && composerRect.top > scrollerRect.top
                    ? composerRect.top
                    : scrollerRect.bottom;
                const bottomBoundary = Math.min(scrollerRect.bottom, composerTop) - 16;
                const availableHeight = Math.max(0, bottomBoundary - topBoundary);
                let delta = 0;

                if (targetRect.height > availableHeight || targetRect.top < topBoundary) {
                    delta = targetRect.top - topBoundary;
                } else if (targetRect.bottom > bottomBoundary) {
                    delta = targetRect.bottom - bottomBoundary;
                }

                if (Math.abs(delta) > 1) {
                    scroller.scrollTo({
                        top: Math.max(0, scroller.scrollTop + delta),
                        left: scroller.scrollLeft,
                        behavior: "auto",
                    });
                }
            };

            manager.scheduleMotion(reveal, [0, 40, 120], 180, manager.remember);
        };
        return manager;
    };

    const install = ({ restore = false, resetToTop = false } = {}) => {
        const scroller = doc.querySelector(
            '[data-testid="stAppScrollToBottomContainer"], [data-testid="stMain"]'
        );
        if (!scroller) return;

        let manager = window[managerKey];
        if (!manager || manager.version !== 4) {
            teardown(manager);
            manager = createManager();
            window[managerKey] = manager;
        }

        doc.removeEventListener("wheel", manager.handleUserInput, true);
        doc.removeEventListener("touchstart", manager.handleUserInput, true);
        doc.removeEventListener("pointerdown", manager.handlePointerDown, true);
        doc.removeEventListener("keydown", manager.handleKeyDown, true);
        doc.addEventListener("wheel", manager.handleUserInput, { capture: true, passive: true });
        doc.addEventListener("touchstart", manager.handleUserInput, { capture: true, passive: true });
        doc.addEventListener("pointerdown", manager.handlePointerDown, true);
        doc.addEventListener("keydown", manager.handleKeyDown, true);

        if (manager.boundScroller) {
            manager.boundScroller.removeEventListener("scroll", manager.handleScroll);
        }
        manager.scroller = scroller;
        manager.boundScroller = scroller;
        scroller.addEventListener("scroll", manager.handleScroll, { passive: true });

        if (resetToTop) {
            try {
                window.sessionStorage.removeItem(storageKey);
            } catch (_) {
                // Empty-state positioning must not depend on storage availability.
            }
            const resetTop = () => scroller.scrollTo({
                top: 0,
                left: scroller.scrollLeft,
                behavior: "auto",
            });
            resetTop();
            manager.scheduleMotion(resetTop, [40, 120, 280, 600, 1000], 1100);
            return;
        }

        manager.cancelMotion();
        let hasSavedPosition = false;
        try {
            hasSavedPosition = window.sessionStorage.getItem(storageKey) !== null;
        } catch (_) {
            // Storage availability is checked again by manager.remember().
        }
        if (!hasSavedPosition) manager.remember();

        if (restore) {
            let savedPosition = Number.NaN;
            try {
                savedPosition = Number(window.sessionStorage.getItem(storageKey));
            } catch (_) {
                // Ignore unavailable storage and retain Streamlit's default behavior.
            }
            if (Number.isFinite(savedPosition)) {
                const restorePosition = () => scroller.scrollTo({
                    top: savedPosition,
                    left: scroller.scrollLeft,
                    behavior: "auto",
                });
                restorePosition();
                manager.scheduleMotion(
                    restorePosition,
                    [40, 120, 280, 600, 1000],
                    1200,
                    manager.remember
                );
            }
        }
    };

    install.version = 4;
    window[installerKey] = install;
})();
"""


def render_scroll_position_manager(
    *,
    restore: bool,
    reset_to_top: bool = False,
    command_id: int = 0,
) -> None:
    """Preserve the reader's main-page position across the final answer rerun."""
    restore_requested = "true" if restore else "false"
    reset_requested = "true" if reset_to_top else "false"
    command_marker = max(0, int(command_id))
    installer_source = json.dumps(SCROLL_POSITION_MANAGER_INSTALLER)
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
            const commandId = {command_marker};
            const installerKey = "__citrusAgentInstallScrollManager";
            if (!host[installerKey] || host[installerKey].version !== 4) {{
                const loader = doc.createElement("script");
                loader.textContent = {installer_source};
                (doc.head || doc.documentElement).appendChild(loader);
                loader.remove();
            }}

            const install = host[installerKey];
            if (typeof install === "function") {{
                install({{
                    restore: {restore_requested},
                    resetToTop: {reset_requested},
                    commandId,
                }});
            }}
        }})();
        </script>
        """,
        height=1,
        tab_index=-1,
    )


AGENT_PROGRESS_SELECTOR = '[class*="st-key-agent_progress_host"] .agent-live-progress'


def render_progress_reveal(reveal_id: str) -> None:
    """Reveal the first empty-state progress update without fighting user scrolling."""
    installer_source = json.dumps(SCROLL_POSITION_MANAGER_INSTALLER)
    reveal_marker = json.dumps(str(reveal_id))
    selector_marker = json.dumps(AGENT_PROGRESS_SELECTOR)
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
            const installerKey = "__citrusAgentInstallScrollManager";
            const managerKey = "__citrusAgentScrollManager";
            if (!host[installerKey] || host[installerKey].version !== 4) {{
                const loader = doc.createElement("script");
                loader.textContent = {installer_source};
                (doc.head || doc.documentElement).appendChild(loader);
                loader.remove();
            }}

            const install = host[installerKey];
            if (typeof install === "function") {{
                install({{ restore: false, resetToTop: false }});
            }}
            const manager = host[managerKey];
            if (manager && typeof manager.revealOnce === "function") {{
                manager.revealOnce({reveal_marker}, {selector_marker});
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
    st.session_state.pop("sidebar_draft_image_bytes", None)
    st.session_state.pop("sidebar_draft_image_mime_type", None)
    st.session_state.pop("sidebar_draft_image_name", None)
    st.session_state.image_uploader_version = (
        int(st.session_state.get("image_uploader_version", 0)) + 1
    )


def reset_sidebar_inputs() -> None:
    reset_uploaded_image()
    st.session_state.pop("manual_observation", None)
    st.session_state.pop("sidebar_draft_observation", None)


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


PRODUCT_VIEWS = {"chat", "workspace", "knowledge", "analytics", "settings"}


def current_product_view() -> str:
    state_view = str(st.session_state.get("product_view") or "").lower()
    if state_view in PRODUCT_VIEWS:
        return state_view
    query_view = _query_value("view").lower()
    view = query_view if query_view in PRODUCT_VIEWS else "chat"
    st.session_state.product_view = view
    return view


def preserve_sidebar_draft() -> None:
    """Keep unsent visual input alive while navigating within the product shell."""
    observation = st.session_state.get("manual_observation")
    if isinstance(observation, str):
        st.session_state.sidebar_draft_observation = observation

    uploaded_image = st.session_state.get(image_uploader_key())
    if uploaded_image is None:
        return
    try:
        prepared = prepare_image_for_vision(
            uploaded_image.getvalue(),
            filename=getattr(uploaded_image, "name", "uploaded-image"),
            mime_type=getattr(uploaded_image, "type", ""),
        )
    except (AttributeError, vision_client.VisionAPIError):
        return
    st.session_state.sidebar_draft_image_bytes = prepared.data
    st.session_state.sidebar_draft_image_mime_type = prepared.mime_type
    st.session_state.sidebar_draft_image_name = str(
        getattr(uploaded_image, "name", "uploaded-image")
    )


def select_product_view(view: str) -> None:
    normalized = str(view or "").lower()
    if normalized not in PRODUCT_VIEWS:
        return
    preserve_sidebar_draft()
    st.session_state.product_view = normalized
    st.session_state.mobile_secondary_open = False
    st.session_state.reset_main_scroll_position = True
    _set_query_value("view", normalized)


def toggle_mobile_secondary_panel() -> None:
    st.session_state.mobile_secondary_open = not bool(
        st.session_state.get("mobile_secondary_open", False)
    )


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
            restored = restore_ui_messages(
                rows,
                manager=manager,
                user_id=user_id,
                project_id=project_id,
            )
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
    reset_sidebar_inputs()
    st.session_state.product_view = "chat"
    _set_query_value("view", "chat")


def init_state() -> None:
    st.session_state.setdefault("agent_messages", [])
    st.session_state.setdefault("current_batch", None)
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_vision_context", None)
    st.session_state.setdefault("clear_sidebar_inputs", False)
    st.session_state.setdefault("image_uploader_version", 0)
    st.session_state.setdefault("sidebar_draft_observation", "")
    st.session_state.setdefault("mobile_secondary_open", False)
    initialize_memory_identity()
    if st.session_state.clear_sidebar_inputs:
        reset_sidebar_inputs()
        st.session_state.clear_sidebar_inputs = False


def render_product_secondary_panel(view: str) -> None:
    panel_content = {
        "workspace": {
            "eyebrow": "CITRUS AI · WORKSPACE",
            "title": "工作台",
            "description": "集中查看最近任务、历史分析与保存方案。",
            "items": (("最近任务", "Recent tasks"), ("历史分析", "Analysis history"), ("批次与方案", "Batches & plans")),
        },
        "knowledge": {
            "eyebrow": "CITRUS AI · KNOWLEDGE",
            "title": "知识库",
            "description": "检索可追溯的柑橘加工文献与参数来源。",
            "items": (("全部文献", "All literature"), ("加工分类", "Categories"), ("索引状态", "Index status")),
        },
        "analytics": {
            "eyebrow": "CITRUS AI · ANALYTICS",
            "title": "分析",
            "description": "基于真实运行与文献索引的决策概览。",
            "items": (("使用概览", "Usage overview"), ("知识覆盖", "Knowledge coverage"), ("运行质量", "Run quality")),
        },
        "settings": {
            "eyebrow": "CITRUS AI · SETTINGS",
            "title": "设置",
            "description": "查看模型、数据与隐私边界的当前配置。",
            "items": (("常规", "General"), ("模型与能力", "Models"), ("数据与隐私", "Data & privacy")),
        },
    }[view]
    ui_components.render_secondary_intro(
        panel_content["eyebrow"],
        panel_content["title"],
        panel_content["description"],
    )
    st.button(
        "＋ 新建对话",
        width="stretch",
        on_click=start_new_conversation,
        key=f"new_conversation_from_{view}",
    )
    rows = "".join(
        '<div class="secondary-nav-row">'
        f'<span>{html.escape(zh)}</span><small>{html.escape(en)}</small>'
        "</div>"
        for zh, en in panel_content["items"]
    )
    st.markdown(
        f'<div class="secondary-section-label">页面结构</div><div class="secondary-nav-stack">{rows}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="secondary-note">页面数据为只读视图。Agent、模型配置与知识库内容不会在这里被静默修改。</div>',
        unsafe_allow_html=True,
    )


def render_sidebar(view: str = "chat") -> tuple[str, bool, bytes | None, str]:
    with st.sidebar:
        if view != "chat":
            render_product_secondary_panel(view)
            return "", False, None, "image/jpeg"

        st.markdown(
            f"""
            <div class="sidebar-brand">
                <div>
                    <div class="brand-subtitle">CITRUS AI · DECISION LAB</div>
                    <div class="brand-title">Citrus Assistant</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.button(
            "＋ 新建对话",
            width="stretch",
            on_click=start_new_conversation,
            key="new_conversation",
        )

        st.markdown(
            '<div class="sidebar-section-title">视觉输入<small>Visual Input</small></div>',
            unsafe_allow_html=True,
        )
        uploader_version = int(st.session_state.image_uploader_version)
        st.markdown(
            '<div class="secondary-field-heading upload-field"><span>上传柑橘图片</span><small>Upload Citrus Image</small></div>',
            unsafe_allow_html=True,
        )
        uploaded_image = st.file_uploader(
            "上传柑橘图片",
            type=list(SUPPORTED_UPLOAD_EXTENSIONS),
            key=image_uploader_key(),
            label_visibility="collapsed",
        )
        prepared_image = None
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
                st.session_state.sidebar_draft_image_bytes = prepared_image.data
                st.session_state.sidebar_draft_image_mime_type = prepared_image.mime_type
                st.session_state.sidebar_draft_image_name = str(uploaded_image.name)

        image_bytes = prepared_image.data if prepared_image else st.session_state.get(
            "sidebar_draft_image_bytes"
        )
        image_mime_type = (
            prepared_image.mime_type
            if prepared_image
            else str(st.session_state.get("sidebar_draft_image_mime_type") or "image/jpeg")
        )
        if image_bytes:
            caption = "图片预览" if prepared_image else "已保留的待发送图片"
            st.image(image_bytes, caption=caption, width="stretch")
            st.info("图片会在本轮分析中自动调用视觉模型识别；下方外观描述可作为人工补充。")
            st.button(
                "× 删除图片",
                width="stretch",
                key=f"remove_uploaded_image_{uploader_version}",
                on_click=reset_uploaded_image,
            )

        st.markdown(
            '<div class="secondary-field-heading appearance-field"><span>外观描述</span><small>Appearance Description</small></div>',
            unsafe_allow_html=True,
        )
        if "manual_observation" not in st.session_state:
            st.session_state.manual_observation = str(
                st.session_state.get("sidebar_draft_observation") or ""
            )
        manual_observation = st.text_area(
            "外观描述",
            placeholder=(
                "例如：果皮完整，颜色偏成熟，无明显霉斑或腐烂。\n"
                "e.g., peel intact, color slightly ripe, no obvious mold or rot."
            ),
            height=110,
            key="manual_observation",
            label_visibility="collapsed",
        )
        st.session_state.sidebar_draft_observation = manual_observation

        st.divider()

        st.markdown(
            f"""
            <div class="sidebar-section-title model-heading">语言模型<small>Language Model</small></div>
            <div class="status-list">
                <div class="status-row"><span>DeepSeek</span><span class="status-pill">{DEEPSEEK_MODEL}</span></div>
                <div class="status-row"><span>Qwen Vision</span><span class="status-pill">{get_vision_model()}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return manual_observation, image_bytes is not None, image_bytes, image_mime_type


def score_table(result: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "加工方向": item_value(item, "direction"),
                "适配等级": item_value(item, "match_level", "待评估"),
                "文献支持": item_value(item, "evidence_support", "未评估"),
                "数据置信度": item_value(item, "data_confidence", "低"),
                "主要原因": "；".join(item_value(item, "reasons", [])),
                "风险提示": "；".join(item_value(item, "risk_notes", [])) or "暂无",
            }
            for item in result.get("scores", [])
        ]
    )


def step_table(result: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "步骤": index,
                "任务": item_value(step, "name"),
                "调用工具": item_value(step, "tool"),
                "状态": item_value(step, "status"),
                "观察结果": item_value(step, "observation"),
            }
            for index, step in enumerate(result.get("agent_steps", []), 1)
        ]
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


def render_processing_plan(plan: dict[str, Any]) -> None:
    if not plan:
        return

    def safe_text(value: Any) -> str:
        return html.escape(str(value or ""))

    flow_parts = []
    for index, step in enumerate(plan.get("flow", [])):
        if index:
            flow_parts.append('<span class="processing-flow-arrow">→</span>')
        flow_parts.append(f'<span class="processing-flow-step">{safe_text(step)}</span>')

    stage_parts = []
    for stage in plan.get("stages", []):
        stage_parts.append(
            '<article class="processing-stage">'
            f'<h4>{safe_text(stage.get("name"))}</h4>'
            f'<p><strong>对应工序：</strong>{safe_text(" → ".join(stage.get("steps", [])))}</p>'
            f'<p><strong>操作要点：</strong>{safe_text(stage.get("operation"))}</p>'
            f'<p><strong>质控要求：</strong>{safe_text(stage.get("control"))}</p>'
            f'<p><strong>必留记录：</strong>{safe_text(stage.get("record"))}</p>'
            "</article>"
        )

    basis = "；".join(str(item) for item in plan.get("basis", []))
    pilot_parameters = "；".join(str(item) for item in plan.get("pilot_parameters", []))
    release_checks = "；".join(str(item) for item in plan.get("release_checks", []))
    missing_data = "；".join(str(item) for item in plan.get("missing_data", []))
    risk_controls = "；".join(str(item) for item in plan.get("risk_controls", []))
    st.markdown(
        f"""
        <section class="processing-plan" aria-label="完整加工流程方案">
            <div class="processing-plan-head">
                <div>
                    <div class="processing-plan-kicker">完整加工流程（方案）</div>
                    <div class="processing-plan-title">{safe_text(plan.get("product_form"))}</div>
                </div>
                <div class="processing-plan-status">{safe_text(plan.get("status"))}</div>
            </div>
            <div class="processing-flow">{"".join(flow_parts)}</div>
            <div class="processing-stage-grid">{"".join(stage_parts)}</div>
            <div class="processing-plan-foot">
                <div class="processing-plan-note"><strong>当前方案依据：</strong>{safe_text(basis)}</div>
                <div class="processing-plan-note"><strong>待小试定参：</strong>{safe_text(pilot_parameters)}</div>
                <div class="processing-plan-note"><strong>成品放行复核：</strong>{safe_text(release_checks)}</div>
                <div class="processing-plan-note"><strong>当前待补：</strong>{safe_text(missing_data)}</div>
                <div class="processing-plan-note"><strong>风险边界：</strong>{safe_text(risk_controls)}</div>
            </div>
        </section>
        """,
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


def render_analysis_payload(payload: dict[str, Any]) -> None:
    result = payload["result"]
    report_path = Path(str(payload["report_path"]))
    scores = result.get("scores", [])
    top = scores[0] if scores else None
    risks = result.get("quality_risks", [])
    evidence = result.get("evidence", [])

    recommendation = html.escape(str(item_value(top, "direction", "暂无")))
    st.markdown(
        f"""
        <div class="recommendation-summary">
            <div class="metric-card recommendation-card">
                <div class="metric-label">推荐方向</div>
                <div class="metric-value">{recommendation}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    processing_plan = resolve_processing_plan(result)
    summary = str(payload.get("summary") or "")
    if processing_plan and "完整加工流程（方案）" not in summary:
        summary = orchestrator.summarize_result(result, report_path)
    llm_answer = str(payload.get("llm_answer") or "").strip()
    if llm_answer.startswith("DeepSeek 总结失败"):
        llm_answer = ""
    answer = str(payload.get("answer") or llm_answer or summary).strip()
    answer = orchestrator.ensure_primary_processing_flow(result, answer)

    # The recommendation must be followed by an executable route regardless of
    # how the summarization model phrases its answer.  Render directly from the
    # structured tool result; this also repairs older stored analysis payloads.
    if processing_plan:
        render_processing_plan(processing_plan)
        parameterized_text = agent_report.parameterized_plan_markdown(
            result.get("parameterized_plan") or {},
            result.get("parameter_groups") or [],
            result.get("processing_intent") or {},
        )
        parameterized_text = re.sub(r"(?m)^### 5\.\d+\s+", "### ", parameterized_text)
        st.markdown(parameterized_text)

    narrative_answer = orchestrator.strip_primary_processing_flow(answer)
    if narrative_answer:
        st.markdown(narrative_answer)

    if payload.get("vision_result"):
        with st.expander("图片识别结果", expanded=True):
            render_vision_result(payload["vision_result"])

    with st.expander("工具调用过程", expanded=False):
        render_tool_steps(result)

    with st.expander("加工路线分级与质控风险", expanded=False):
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
                    f'<span class="risk-level">[{level}]</span>{item_name}：{suggestion}'
                    '</div>'
                )
            st.markdown('<div class="risk-list">' + "".join(risk_rows) + "</div>", unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="risk-empty">暂未触发高风险项，但仍需人工复核。</div>',
                unsafe_allow_html=True,
            )

    with st.expander("文献证据", expanded=False):
        if evidence:
            for index, item in enumerate(evidence, 1):
                title = item.get("title") or "未命名文献"
                year = item.get("year") or "年份未知"
                st.markdown(f"**[文献{index}] {title}（{year}）** · 匹配分 {item.get('match_score')}")
                st.write(item.get("chunk_text"))
                page_text = f"；页码：{item.get('page')}" if item.get("page") else ""
                doi_text = f"；DOI：{item.get('doi')}" if item.get("doi") else ""
                st.caption(f"来源：{item.get('source')}；主题：{item.get('topic')}{page_text}{doi_text}")
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
            ui_components.render_light_table(
                rows,
                "未提取到可展示的可靠工艺参数。",
                height=420,
            )
            st.caption("单篇文献值不等于通用生产参数；请展开报告核对适用条件、页码和原文片段。")
        else:
            st.info("未提取到单位、适用条件和来源均完整的可靠工艺参数；系统不会自动补写数值。")

    with st.expander("报告草稿", expanded=False):
        st.markdown('<span class="report-anchor"></span>', unsafe_allow_html=True)
        st.markdown(result["report"])
        st.download_button(
            "下载 Markdown 报告",
            data=result["report"],
            file_name=report_path.name,
            mime="text/markdown",
            width="stretch",
            key=f"download_{report_path.name}",
        )
        st.caption(f"报告已保存到：{report_path}")


def render_message(message: dict[str, Any]) -> None:
    role = message["role"]
    content_text = str(message.get("content", ""))
    if message.get("kind") == "analysis":
        st.markdown(
            '<div class="message-row assistant"><div class="message-avatar assistant">Citrus AI</div><div class="message-bubble">已完成批次分析，工具调用结果如下。</div></div>',
            unsafe_allow_html=True,
        )
        payload = message["payload"]
        shell_identity = str(
            message.get("message_id")
            or payload.get("report_path")
            or payload.get("run_id")
            or content_text
            or id(message)
        )
        shell_key = hashlib.sha256(shell_identity.encode("utf-8")).hexdigest()[:12]
        with st.container(key=f"analysis_shell_{shell_key}"):
            render_analysis_payload(payload)
        return

    if message.get("kind") == "analysis_legacy":
        st.markdown(
            '<div class="message-row assistant"><div class="message-avatar assistant">Citrus AI</div><div class="message-bubble">已完成批次分析，工具调用结果如下。</div></div>',
            unsafe_allow_html=True,
        )
        shell_identity = str(
            message.get("message_id") or message.get("run_id") or content_text or id(message)
        )
        shell_key = hashlib.sha256(shell_identity.encode("utf-8")).hexdigest()[:12]
        with st.container(key=f"analysis_shell_{shell_key}"):
            st.markdown(restore_flattened_markdown(content_text))
        return

    if role == "user":
        image_bytes = message.get("image_bytes")
        if image_bytes:
            image_mime_type = html.escape(str(message.get("image_mime_type") or "image/jpeg"))
            image_data = base64.b64encode(image_bytes).decode("ascii")
            st.markdown(
                f'<div class="user-attachment-row"><img class="user-attachment" src="data:{image_mime_type};base64,{image_data}" alt="本轮上传图片"></div>',
                unsafe_allow_html=True,
            )
        elif message.get("attachment_missing"):
            st.markdown(
                '<div class="user-attachment-missing">图片附件不可用或已被移除</div>',
                unsafe_allow_html=True,
            )
        content = html.escape(content_text).replace("\n", "<br>")
        st.markdown(
            f'<div class="message-row user"><div class="message-bubble">{content}</div></div>',
            unsafe_allow_html=True,
        )
        return

    label_column, content_column = st.columns([1.15, 8.85], gap="medium")
    with label_column:
        st.markdown(
            '<div class="assistant-markdown-label">Citrus AI</div>',
            unsafe_allow_html=True,
        )
    with content_column:
        st.markdown(content_text)


def render_empty_state(api_key: str) -> tuple[str | None, Any]:
    selected_prompt = None
    with st.container(key="empty_state_shell"):
        with st.container(key="welcome_content"):
            st.markdown(
                f"""
                <div class="hero">
                    <div class="hero-symbol">{ui_components.icon_svg("decision", 26)}</div>
                    <h1>柑橘产业链决策</h1>
                    <div class="hero-english">CITRUS INDUSTRY CHAIN DECISION MAKING</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if not api_key:
                st.warning("请先在 agent/llm_config.py 中填入 DeepSeek API Key；未填时仍可运行本地规则工具，但不能生成大模型总结。")

            st.markdown(
                '<div class="prompt-grid-label">请选择本次需要开展的工作'
                '<small>Please select the task you would like to proceed with</small></div>',
                unsafe_allow_html=True,
            )
            for row_start in range(0, len(EXAMPLE_CARDS), 2):
                cols = st.columns(2)
                for card_index, (col, card) in enumerate(
                    zip(cols, EXAMPLE_CARDS[row_start : row_start + 2]),
                    start=row_start,
                ):
                    with col:
                        with st.container(key=f"task_card_shell_{card_index}"):
                            st.markdown(
                                f"""
                                <article class="task-card">
                                    <div class="task-card-head">
                                        <div class="task-card-icon">{ui_components.icon_svg(str(card['icon']), 20)}</div>
                                        <div class="task-card-copy">
                                            <div class="task-card-title">{html.escape(str(card['title']))}</div>
                                            <div class="task-card-title-en">{html.escape(str(card['title_en']))}</div>
                                        </div>
                                    </div>
                                    <div class="task-card-description">{html.escape(str(card['description']))}</div>
                                    <div class="task-card-description-en">{html.escape(str(card['description_en']))}</div>
                                </article>
                                """,
                                unsafe_allow_html=True,
                            )
                            if st.button(
                                str(card["title"]),
                                width="stretch",
                                key=f"example_card_{card_index}",
                            ):
                                selected_prompt = card["prompt"]
        with st.container(key="agent_progress_host"):
            progress_slot = st.empty()
    return selected_prompt, progress_slot


def render_agent_progress(slot: Any, message: str, *, reveal_id: str | None = None) -> None:
    safe_message = html.escape(message)
    slot.markdown(
        f"""
        <div class="agent-live-progress" role="status" aria-live="polite">
            <div class="agent-live-spinner"></div>
            <div class="agent-live-copy">
                <div class="agent-live-title">{safe_message}</div>
                <div class="agent-live-subtitle">
                    <span>Agent 正在运行</span>
                    <span class="agent-live-dot"></span>
                    <span class="agent-live-dot"></span>
                    <span class="agent-live-dot"></span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if reveal_id:
        render_progress_reveal(reveal_id)


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
    elif mode == "vision" and isinstance(vision_payload.get("vision_result"), dict):
        message_metadata["vision_result"] = _without_raw_model_output(
            vision_payload["vision_result"]
        )

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
    should_reveal_progress = progress_slot is not None
    if progress_slot is None:
        progress_slot = st.empty()
    progress_revealed = False

    def update_progress(message: str) -> None:
        nonlocal progress_revealed
        reveal_id = user_message_id if should_reveal_progress and not progress_revealed else None
        render_agent_progress(progress_slot, message, reveal_id=reveal_id)
        progress_revealed = True

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
        update_progress("正在读取图片并回答本轮问题")
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
        update_progress("正在全面检索本地文献并组织专业回答")
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
        page_title="Citrus AI · 柑橘产业链决策",
        page_icon="◌",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_style()
    init_state()
    restore_scroll_position = bool(st.session_state.pop("restore_main_scroll_position", False))
    reset_scroll_position = bool(st.session_state.pop("reset_main_scroll_position", False))
    scroll_command_id = int(st.session_state.get("scroll_manager_command_id", 0))
    if restore_scroll_position or reset_scroll_position:
        scroll_command_id += 1
        st.session_state.scroll_manager_command_id = scroll_command_id
    active_view = current_product_view()
    uid = _query_value("uid")
    sid = _query_value("sid")
    with st.container(key="product_shell_overlays"):
        ui_components.render_primary_navigation(
            active_view,
            uid,
            sid,
            on_view_change=select_product_view,
        )
        ui_components.render_top_actions(
            active_view,
            uid,
            sid,
            on_view_change=select_product_view,
        )
        ui_components.render_mobile_panel_toggle(
            bool(st.session_state.mobile_secondary_open),
            toggle_mobile_secondary_panel,
        )

    api_key = get_deepseek_api_key()
    manual_observation, has_image, image_bytes, image_mime_type = render_sidebar(active_view)

    if active_view != "chat":
        with st.container(key="product_page_shell"):
            render_product_page(active_view)
        render_scroll_position_manager(
            restore=restore_scroll_position,
            reset_to_top=reset_scroll_position,
            command_id=scroll_command_id,
        )
        return

    if not st.session_state.agent_messages:
        selected_prompt, progress_slot = render_empty_state(api_key)
    else:
        selected_prompt = None
        progress_slot = None
        st.markdown('<div class="chat-transcript-start"></div>', unsafe_allow_html=True)
        for message in st.session_state.agent_messages:
            render_message(message)

    clearance_state = "is-transcript" if st.session_state.agent_messages else "is-empty"
    st.markdown(
        f'<div class="mobile-composer-clearance {clearance_state}" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )

    typed_prompt = st.chat_input("输入问题或粘贴批次信息… · Ask or paste batch data…")
    render_scroll_position_manager(
        restore=restore_scroll_position,
        reset_to_top=reset_scroll_position or not bool(st.session_state.agent_messages),
        command_id=scroll_command_id,
    )
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
