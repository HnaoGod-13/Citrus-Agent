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
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import (
    background_tasks as agent_background,
    evidence as agent_evidence,
    llm_client,
    memory as agent_memory,
    memory_config,
    orchestrator,
    process_knowledge as agent_process_knowledge,
    rag as agent_rag,
    report as agent_report,
    tools as agent_tools,
    vision_client,
    workflow,
)
from app.ui import components as ui_components
from app.ui import product_pages as ui_product_pages


def refresh_ui_modules() -> None:
    """Refresh lightweight UI code after a Streamlit Cloud hot deployment."""
    importlib.invalidate_caches()
    importlib.reload(ui_components)
    importlib.reload(ui_product_pages)

DEEPSEEK_MODEL = llm_client.DEEPSEEK_MODEL
DeepSeekAPIError = llm_client.DeepSeekAPIError
build_general_chat_messages = llm_client.build_general_chat_messages
chat_with_deepseek = llm_client.chat_with_deepseek
get_deepseek_api_key = llm_client.get_deepseek_api_key
retrieve_general_literature = llm_client.retrieve_general_literature
get_vision_model = vision_client.get_vision_model
prepare_image_for_vision = vision_client.prepare_image_for_vision
SUPPORTED_UPLOAD_EXTENSIONS = vision_client.SUPPORTED_UPLOAD_EXTENSIONS

RETRIEVAL_MODES = ("quick", "deep")
RETRIEVAL_MODE_LABELS = {
    "quick": "快速检索",
    "deep": "全库深度检索",
}
AGENT_PERSISTENCE_MAX_RETRIES = 3
AGENT_PERSISTENCE_RETRY_DELAYS = (1.0, 2.0, 5.0)
AGENT_PERSISTENCE_RETRY_LEASE_SECONDS = 35.0
_PENDING_AGENT_PERSISTENCE_LOCK = threading.RLock()


def normalize_retrieval_mode(value: Any) -> str:
    normalized = str(value or "quick").strip().lower()
    return normalized if normalized in RETRIEVAL_MODES else "quick"


def retrieval_mode_label(value: Any) -> str:
    return RETRIEVAL_MODE_LABELS[normalize_retrieval_mode(value)]


@st.cache_resource(show_spinner=False)
def _get_memory_manager(storage_version: int) -> agent_memory.MemoryManager:
    del storage_version
    return agent_memory.MemoryManager()


def get_memory_manager() -> agent_memory.MemoryManager:
    return _get_memory_manager(agent_memory.MESSAGE_STORAGE_VERSION)


def _release_agent_task_runner(runner: agent_background.TaskRunner) -> None:
    runner.shutdown()


@st.cache_resource(show_spinner=False, on_release=_release_agent_task_runner)
def get_agent_task_runner() -> agent_background.TaskRunner:
    return agent_background.TaskRunner()


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
        "description": "比较酸度、果汁与果皮路线",
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
        "title": "复核生产风险与合规",
        "title_en": "Review Risk & Compliance",
        "description": "复核批次生产风险",
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
    deep_retrieval_stats = source.get("deep_retrieval_stats") or serialized_result.get(
        "deep_retrieval_stats"
    )
    if isinstance(deep_retrieval_stats, dict):
        serialized_result["deep_retrieval_stats"] = _json_serializable(
            deep_retrieval_stats
        )
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
        "deep_retrieval_stats": _json_serializable(deep_retrieval_stats or {}),
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
    for key in ("batch", "vision_result", "deep_retrieval_stats"):
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
        if role == "assistant" and isinstance(metadata.get("deep_retrieval_stats"), dict):
            message["deep_retrieval_stats"] = _json_serializable(
                metadata["deep_retrieval_stats"]
            )
        if role == "assistant" and isinstance(metadata.get("evidence"), list):
            message["evidence"] = _json_serializable(metadata["evidence"])
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


NAVIGATION_HISTORY_SYNC_INSTALLER = r"""
(() => {
    const managerKey = "__citrusAgentNavigationHistorySync";
    const version = 1;
    const existing = window[managerKey];
    if (existing && existing.version === version) return;
    if (existing && typeof existing.handlePopState === "function") {
        window.removeEventListener("popstate", existing.handlePopState);
    }

    const handlePopState = () => {
        window.setTimeout(() => window.location.reload(), 0);
    };
    window.addEventListener("popstate", handlePopState);
    window[managerKey] = { version, handlePopState };
})();
"""


def render_navigation_history_sync() -> None:
    """Reload the Streamlit task when browser history changes its query scope."""
    installer_source = json.dumps(NAVIGATION_HISTORY_SYNC_INSTALLER)
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
                frame.style.pointerEvents = "none";
                frame.setAttribute("aria-hidden", "true");
            }}

            const host = window.parent;
            const doc = host.document;
            const loader = doc.createElement("script");
            loader.textContent = {installer_source};
            (doc.head || doc.documentElement).appendChild(loader);
            loader.remove();
        }})();
        </script>
        """,
        height=1,
        tab_index=-1,
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
            doc.removeEventListener("touchmove", manager.handleUserInput, true);
        }
        if (manager.handleRailWheel) {
            doc.removeEventListener("wheel", manager.handleRailWheel, true);
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
        manager.preservePosition = () => {};
        manager.revealOnce = () => {};
    };

    const createManager = () => {
        const manager = {
            version: 8,
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
        manager.preservePosition = (
            scrollTop,
            delays = [0, 40, 120, 280, 520, 800, 1200, 1600],
            releaseDelay = 1700
        ) => {
            const savedPosition = Number(scrollTop);
            if (!Number.isFinite(savedPosition)) return;
            const restorePosition = () => {
                const scroller = manager.scroller;
                if (!scroller) return;
                scroller.scrollTo({
                    top: savedPosition,
                    left: scroller.scrollLeft,
                    behavior: "auto",
                });
            };
            manager.scheduleMotion(
                restorePosition,
                delays,
                releaseDelay,
                manager.remember
            );
        };
        manager.handleUserInput = (event) => {
            if (event && event.isTrusted === false) return;
            manager.cancelMotion();
            manager.userScrollUntil = Date.now() + 1200;
        };
        manager.handleRailWheel = (event) => {
            if (
                !event
                || event.defaultPrevented
                || event.ctrlKey
                || window.innerWidth < 900
                || !manager.scroller
                || Math.abs(event.deltaY) <= Math.abs(event.deltaX)
            ) return;

            const target = event.target;
            if (!target || typeof target.closest !== "function") return;
            const rail = target.closest(".citrus-primary-rail");
            const sidebar = target.closest('[data-testid="stSidebar"]');
            const primaryRailWidth = Number.parseFloat(
                window.getComputedStyle(doc.documentElement)
                    .getPropertyValue("--primary-rail-width")
            ) || 0;
            const overPrimaryRail = Boolean(rail) || event.clientX <= primaryRailWidth;
            const boundary = rail || sidebar;
            if (!overPrimaryRail && !sidebar) return;

            let node = target;
            while (boundary && node && node !== boundary.parentElement) {
                const style = window.getComputedStyle(node);
                const canOwnScroll = /auto|scroll/.test(style.overflowY)
                    && node.scrollHeight > node.clientHeight + 1;
                if (canOwnScroll) {
                    const canMoveDown = event.deltaY > 0
                        && node.scrollTop + node.clientHeight < node.scrollHeight - 1;
                    const canMoveUp = event.deltaY < 0 && node.scrollTop > 1;
                    if (canMoveDown || canMoveUp) return;
                }
                if (node === boundary) break;
                node = node.parentElement;
            }

            const scroller = manager.scroller;
            const canMoveMainDown = event.deltaY > 0
                && scroller.scrollTop + scroller.clientHeight < scroller.scrollHeight - 1;
            const canMoveMainUp = event.deltaY < 0 && scroller.scrollTop > 1;
            if (!canMoveMainDown && !canMoveMainUp) return;

            event.preventDefault();
            manager.handleUserInput(event);
            scroller.scrollBy({
                top: event.deltaY,
                left: 0,
                behavior: "auto",
            });
            window.requestAnimationFrame(manager.remember);
        };
        manager.handlePointerDown = (event) => {
            if (event && event.isTrusted === false) return;
            manager.cancelMotion();
            manager.userScrollUntil = 0;
            manager.remember();
            const target = event.target;
            if (!target || typeof target.closest !== "function" || !manager.scroller) return;
            const preserveTarget = target.closest(
                '[data-testid="stExpander"] summary, [data-testid="stChatInput"]'
            );
            if (!preserveTarget) return;
            manager.preservePosition(manager.scroller.scrollTop);
        };
        manager.handleKeyDown = (event) => {
            const target = event.target;
            const isChatSubmit = event.key === "Enter"
                && !event.shiftKey
                && target
                && typeof target.matches === "function"
                && target.matches('[data-testid="stChatInputTextArea"]');
            if (isChatSubmit) {
                manager.cancelMotion();
                manager.userScrollUntil = 0;
                manager.remember();
            }

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
        if (!manager || manager.version !== 8) {
            teardown(manager);
            manager = createManager();
            window[managerKey] = manager;
        }

        doc.removeEventListener("wheel", manager.handleUserInput, true);
        doc.removeEventListener("wheel", manager.handleRailWheel, true);
        doc.removeEventListener("touchstart", manager.handleUserInput, true);
        doc.removeEventListener("touchmove", manager.handleUserInput, true);
        doc.removeEventListener("pointerdown", manager.handlePointerDown, true);
        doc.removeEventListener("keydown", manager.handleKeyDown, true);
        doc.addEventListener("wheel", manager.handleUserInput, { capture: true, passive: true });
        doc.addEventListener("wheel", manager.handleRailWheel, { capture: true, passive: false });
        doc.addEventListener("touchmove", manager.handleUserInput, { capture: true, passive: true });
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
                    [40, 120, 280, 600, 1000, 1600, 2400, 3600],
                    3800,
                    manager.remember
                );
            }
        }
    };

    install.version = 8;
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
            if (!host[installerKey] || host[installerKey].version !== 8) {{
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
            if (!host[installerKey] || host[installerKey].version !== 8) {{
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
    clear_sidebar_image_draft()
    st.session_state.image_uploader_version = (
        int(st.session_state.get("image_uploader_version", 0)) + 1
    )


def clear_sidebar_image_draft() -> None:
    st.session_state.pop("sidebar_draft_image_bytes", None)
    st.session_state.pop("sidebar_draft_image_mime_type", None)
    st.session_state.pop("sidebar_draft_image_name", None)


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


def _delete_query_value(name: str) -> None:
    try:
        if name in st.query_params:
            del st.query_params[name]
    except Exception:
        pass


def _valid_context_token(value: str) -> bool:
    return bool(re.fullmatch(r"ctx_[A-Za-z0-9_-]{32,96}", value or ""))


def _memory_identity_matches_authentication(
    user_id: str,
    authenticated_user_id: str,
) -> bool:
    """Keep anonymous and authenticated memory scopes from crossing."""
    normalized_user_id = str(user_id or "")
    normalized_authenticated_id = str(authenticated_user_id or "")
    if not normalized_user_id:
        return False
    if normalized_user_id.startswith("anon_"):
        return not normalized_authenticated_id
    return bool(normalized_authenticated_id) and normalized_user_id == normalized_authenticated_id


PRODUCT_VIEWS = {"chat", "workspace", "knowledge", "analytics", "settings"}


def current_product_view() -> str:
    query_view = _query_value("view").lower()
    state_view = str(st.session_state.get("product_view") or "").lower()
    if query_view in PRODUCT_VIEWS:
        view = query_view
    elif state_view in PRODUCT_VIEWS:
        view = state_view
        _set_query_value("view", view)
    else:
        view = "chat"
        _set_query_value("view", view)

    if state_view in PRODUCT_VIEWS and state_view != view:
        preserve_sidebar_draft()
        st.session_state.mobile_secondary_open = False
        st.session_state.reset_main_scroll_position = True
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
        clear_sidebar_image_draft()
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


def select_industry_view(view: str) -> None:
    normalized = str(view or "").strip().lower()
    if normalized not in {"production", "supply", "demand", "match"}:
        return
    st.session_state.industry_workspace_view = normalized
    st.session_state.reset_main_scroll_position = True
    _set_query_value("view", "workspace")
    _set_query_value("industry", normalized)


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
    manager = get_memory_manager()
    authenticated = _authenticated_identity()
    authenticated_user_id = (
        "user_" + hashlib.sha256(authenticated.encode("utf-8")).hexdigest()[:24]
        if authenticated
        else ""
    )

    previous_identity = (
        str(st.session_state.get("memory_user_id") or ""),
        str(st.session_state.get("memory_project_id") or ""),
        str(st.session_state.get("memory_session_id") or ""),
    )
    query_context_token = _query_value("ctx")
    state_context_token = str(st.session_state.get("memory_context_token") or "")
    resolved: dict[str, str] | None = None
    resumed = False

    # Legacy uid/sid values exposed long-lived internal identity credentials in
    # copied URLs. They are ignored and removed; URL restoration now accepts
    # only a short-lived opaque grant whose digest is stored server-side.
    _delete_query_value("uid")
    _delete_query_value("sid")

    if _valid_context_token(query_context_token):
        resolved = manager.resolve_session_access_grant(
            query_context_token,
            project_id=project_id,
        )
        if resolved and not _memory_identity_matches_authentication(
            str(resolved.get("user_id") or ""),
            authenticated_user_id,
        ):
            resolved = None
    elif query_context_token:
        # A malformed or expired credential creates a new isolated context. It
        # must never fall back to other identifiers supplied by the same URL.
        resolved = None
    elif previous_identity[0] and previous_identity[1] == project_id and previous_identity[2]:
        # A live Streamlit browser session may rerun before its query state is
        # synchronized. Reuse only a token resolving to the exact live scope.
        if _valid_context_token(state_context_token):
            live_grant = manager.resolve_session_access_grant(
                state_context_token,
                project_id=project_id,
            )
            if (
                live_grant
                and _memory_identity_matches_authentication(
                    str(live_grant.get("user_id") or ""),
                    authenticated_user_id,
                )
                and (
                    live_grant.get("user_id"),
                    live_grant.get("project_id"),
                    live_grant.get("session_id"),
                ) == previous_identity
            ):
                resolved = live_grant
                query_context_token = state_context_token

    if resolved:
        user_id = str(resolved["user_id"])
        session_id = str(resolved["session_id"])
        context_token = query_context_token
        resumed = True
    elif (
        not query_context_token
        and previous_identity[0]
        and previous_identity[1] == project_id
        and _memory_identity_matches_authentication(
            previous_identity[0],
            authenticated_user_id,
        )
    ):
        # Preserve an already-authorized live browser scope, then issue a fresh
        # opaque grant rather than putting the internal IDs back in the URL.
        user_id = authenticated_user_id or previous_identity[0]
        session_id = previous_identity[2] or f"s_{uuid4().hex}"
        context_token = ""
    else:
        user_id = authenticated_user_id or f"anon_{uuid4().hex}"
        session_id = f"s_{uuid4().hex}"
        context_token = ""

    identity_changed = bool(any(previous_identity)) and previous_identity != (
        user_id,
        project_id,
        session_id,
    )
    if identity_changed:
        clear_active_conversation_state(clear_sidebar=True)
        st.session_state.reset_main_scroll_position = True

    st.session_state.memory_user_id = user_id
    st.session_state.memory_project_id = project_id
    st.session_state.memory_session_id = session_id
    try:
        manager.ensure_session(
            user_id,
            session_id,
            project_id,
            config=session_config or None,
        )
    except agent_memory.MemoryIsolationError:
        session_id = f"s_{uuid4().hex}"
        clear_active_conversation_state(clear_sidebar=True)
        identity_changed = True
        st.session_state.reset_main_scroll_position = True
        st.session_state.memory_session_id = session_id
        context_token = ""
        manager.ensure_session(
            user_id,
            session_id,
            project_id,
            config=session_config or None,
        )

    if not context_token:
        context_token = manager.create_session_access_grant(
            user_id,
            session_id,
            project_id,
        )
        resumed = False
    st.session_state.memory_context_token = context_token
    _set_query_value("ctx", context_token)

    privacy_event_type = "session_resumed" if resumed else "session_created"
    privacy_marker = f"{privacy_event_type}:{user_id}:{project_id}:{session_id}:{context_token[-10:]}"
    if st.session_state.get("memory_privacy_event_marker") != privacy_marker:
        try:
            manager.log_privacy_event(
                privacy_event_type,
                user_id=user_id,
                project_id=project_id,
                session_id=session_id,
                details={"channel": "opaque_context_token"},
            )
        except agent_memory.MemoryManagerError:
            pass
        st.session_state.memory_privacy_event_marker = privacy_marker

    if st.session_state.get("memory_restored_session") != session_id:
        if identity_changed or not st.session_state.agent_messages:
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


def clear_active_conversation_state(*, clear_sidebar: bool = False) -> None:
    st.session_state.agent_messages = []
    st.session_state.current_batch = None
    st.session_state.last_result = None
    st.session_state.last_vision_context = None
    st.session_state.memory_restored_session = None
    st.session_state.pending_agent_persistence = {}
    if clear_sidebar:
        reset_sidebar_inputs()


def start_new_conversation() -> None:
    manager = get_memory_manager()
    user_id = str(st.session_state.get("memory_user_id") or "") or f"anon_{uuid4().hex}"
    project_id = str(st.session_state.get("memory_project_id") or "citrus-agent")
    old_session_id = str(st.session_state.get("memory_session_id") or "")
    old_context_token = str(st.session_state.get("memory_context_token") or "")
    if _valid_context_token(old_context_token) and old_session_id:
        try:
            manager.revoke_session_access_grant(
                old_context_token,
                user_id=user_id,
                session_id=old_session_id,
                project_id=project_id,
            )
        except agent_memory.MemoryManagerError:
            pass

    session_id = f"s_{uuid4().hex}"
    clear_active_conversation_state(clear_sidebar=True)
    st.session_state.active_agent_job_id = ""
    st.session_state.active_agent_progress_revealed = False
    st.session_state.active_agent_retrieval_mode = ""
    st.session_state.memory_user_id = user_id
    st.session_state.memory_project_id = project_id
    st.session_state.memory_session_id = session_id
    st.session_state.memory_restored_session = session_id
    manager.ensure_session(
        user_id,
        session_id,
        project_id,
    )
    context_token = manager.create_session_access_grant(
        user_id,
        session_id,
        project_id,
    )
    st.session_state.memory_context_token = context_token
    _set_query_value("ctx", context_token)
    _delete_query_value("uid")
    _delete_query_value("sid")
    try:
        manager.log_privacy_event(
            "session_created",
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            details={"channel": "new_conversation"},
        )
    except agent_memory.MemoryManagerError:
        pass
    st.session_state.memory_privacy_event_marker = (
        f"session_created:{user_id}:{project_id}:{session_id}:{context_token[-10:]}"
    )
    st.session_state.product_view = "chat"
    st.session_state.mobile_secondary_open = False
    st.session_state.reset_main_scroll_position = True
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
    st.session_state.setdefault("active_agent_job_id", "")
    st.session_state.setdefault("active_agent_progress_revealed", False)
    st.session_state.setdefault("active_agent_retrieval_mode", "")
    st.session_state.setdefault("pending_agent_persistence", {})
    st.session_state.setdefault("memory_context_token", "")
    st.session_state.setdefault("memory_privacy_event_marker", "")
    st.session_state.setdefault("retrieval_mode", "quick")
    st.session_state.retrieval_mode = normalize_retrieval_mode(
        st.session_state.retrieval_mode
    )
    initialize_memory_identity()
    if st.session_state.clear_sidebar_inputs:
        reset_sidebar_inputs()
        st.session_state.clear_sidebar_inputs = False


def render_product_secondary_panel(view: str) -> None:
    panel_content = {
        "workspace": {
            "eyebrow": "CITRUS AI · WORKSPACE",
            "title": "工作台",
            "description": "集中查看产业批次、供需匹配与 Agent 分析记录。",
            "items": (("批次采集", "Batch intake"), ("供需匹配", "Supply & demand"), ("报告与看板", "Reports & analytics")),
        },
        "knowledge": {
            "eyebrow": "CITRUS AI · KNOWLEDGE",
            "title": "知识库",
            "description": "检索柑橘直接证据与可迁移工艺参考。",
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
        "新建对话\nNew Chat",
        width="stretch",
        on_click=start_new_conversation,
        key=f"new_conversation_from_{view}",
    )
    if view == "workspace":
        industry_items = (
            ("production", "加工能力与生产记录", "Processing records"),
            ("supply", "供应中心", "Supply center"),
            ("demand", "需求中心", "Demand center"),
            ("match", "匹配结果", "Match results"),
        )
        active_industry = ui_product_pages.current_industry_view()
        st.markdown('<div class="secondary-section-label">页面结构</div>', unsafe_allow_html=True)
        with st.container(key="workspace_industry_nav"):
            for key, zh, en in industry_items:
                st.button(
                    f"{zh}\n{en}",
                    key=f"industry_nav_{key}",
                    type="primary" if key == active_industry else "secondary",
                    width="stretch",
                    on_click=select_industry_view,
                    args=(key,),
                )
    else:
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
    panel_note = (
        "当前为产业工作台演示数据；保存和对接操作仅保留在本次会话中。"
        if view == "workspace"
        else "页面数据为只读视图。Agent、模型配置与知识库内容不会在这里被静默修改。"
    )
    st.markdown(f'<div class="secondary-note">{panel_note}</div>', unsafe_allow_html=True)


def render_sidebar(view: str = "chat") -> tuple[str, bool, bytes | None, str, str]:
    with st.sidebar:
        if view != "chat":
            render_product_secondary_panel(view)
            return (
                "",
                False,
                None,
                "image/jpeg",
                normalize_retrieval_mode(st.session_state.get("retrieval_mode")),
            )

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
            "新建对话\nNew Chat",
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
                clear_sidebar_image_draft()
                st.error(str(error))
            else:
                st.session_state.sidebar_draft_image_bytes = prepared_image.data
                st.session_state.sidebar_draft_image_mime_type = prepared_image.mime_type
                st.session_state.sidebar_draft_image_name = str(uploaded_image.name)

        image_bytes = prepared_image.data if prepared_image else (
            st.session_state.get("sidebar_draft_image_bytes")
            if uploaded_image is None
            else None
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
                "如：果皮完整、无霉斑腐烂。\n"
                "e.g. Intact, no mold or rot."
            ),
            height=110,
            key="manual_observation",
            label_visibility="collapsed",
        )
        st.session_state.sidebar_draft_observation = manual_observation

        st.markdown(
            '<div class="sidebar-section-title retrieval-heading">检索方式<small>Search Mode</small></div>',
            unsafe_allow_html=True,
        )
        with st.container(key="retrieval_mode_shell"):
            retrieval_mode = st.segmented_control(
                "检索方式",
                options=RETRIEVAL_MODES,
                format_func=retrieval_mode_label,
                key="retrieval_mode",
                required=True,
                disabled=bool(st.session_state.get("active_agent_job_id")),
                label_visibility="collapsed",
                width="stretch",
                persist_state="session",
            )
        retrieval_mode = normalize_retrieval_mode(retrieval_mode)

        st.divider()

        st.markdown(
            f"""
            <div class="sidebar-section-title model-heading">模型协同<small>Model Collaboration</small></div>
            <div class="model-pair" aria-label="语言模型与视觉模型协同启用">
                <div class="model-pair-state">
                    <span class="model-live-dot" aria-hidden="true"></span>
                    <span>双模型协同启用</span>
                    <small>Language + Vision</small>
                </div>
                <div class="model-pair-row">
                    <span class="model-pair-role">语言</span>
                    <span class="model-pair-copy"><strong>DeepSeek</strong><small>{DEEPSEEK_MODEL}</small></span>
                </div>
                <div class="model-pair-row">
                    <span class="model-pair-role">视觉</span>
                    <span class="model-pair-copy"><strong>Qwen Vision</strong><small>{get_vision_model()}</small></span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return (
        manual_observation,
        image_bytes is not None,
        image_bytes,
        image_mime_type,
        retrieval_mode,
    )


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


def _retrieval_stat_count(stats: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = stats.get(key)
        if value in (None, "") or isinstance(value, bool):
            continue
        try:
            count = int(float(value))
        except (TypeError, ValueError):
            continue
        if count >= 0:
            return count
    return None


def render_deep_retrieval_stats(value: Any) -> None:
    if not isinstance(value, dict) or not value:
        return
    mode = str(value.get("retrieval_mode") or "").strip().lower()
    if mode and mode != "deep":
        return
    library_documents = _retrieval_stat_count(value, ("library_document_count",))
    library_chunks = _retrieval_stat_count(value, ("library_chunk_count",))
    usable_documents = _retrieval_stat_count(value, ("library_usable_document_count",))
    library_ocr_documents = _retrieval_stat_count(value, ("library_ocr_document_count",))
    fts_rows_returned = _retrieval_stat_count(
        value,
        (
            "fts_rows_returned",
            "database_rows_scanned",
        ),
    )
    selected_documents = _retrieval_stat_count(value, ("selected_document_count",))
    selected_evidence = _retrieval_stat_count(
        value,
        (
            "selected_count",
            "adopted_count",
            "used_count",
        ),
    )
    ocr_filtered = _retrieval_stat_count(value, ("ocr_filtered_count",))
    adjacent_added = _retrieval_stat_count(value, ("adjacent_added_count",))
    if all(
        count is None
        for count in (
            library_documents,
            library_chunks,
            usable_documents,
            library_ocr_documents,
            fts_rows_returned,
            selected_documents,
            selected_evidence,
            ocr_filtered,
            adjacent_added,
        )
    ) and not (
        value.get("database_available") is False
        or value.get("retrieval_complete") is False
        or bool(value.get("timed_out"))
        or str(value.get("retrieval_error") or "").strip()
    ):
        return
    metrics: list[tuple[str, str]] = []
    scope_parts = []
    if library_documents is not None:
        scope_parts.append(f"{library_documents:,} 篇")
    if library_chunks is not None:
        scope_parts.append(f"{library_chunks:,} 片段")
    if scope_parts:
        metrics.append(("全库范围", " / ".join(scope_parts)))
    if usable_documents is not None and usable_documents > 0:
        metrics.append(("正文可用文献", f"{usable_documents:,}"))
    if library_ocr_documents is not None and library_ocr_documents > 0:
        metrics.append(("库内待 OCR", f"{library_ocr_documents:,}"))
    if fts_rows_returned is not None:
        metrics.append(("FTS 返回次数", f"{fts_rows_returned:,}"))
    if selected_documents is not None:
        metrics.append(("采用文献", f"{selected_documents:,}"))
    if selected_evidence is not None:
        metrics.append(("采用证据", f"{selected_evidence:,}"))
    if ocr_filtered is not None and ocr_filtered > 0:
        metrics.append(("本轮排除题录", f"{ocr_filtered:,}"))
    if adjacent_added is not None:
        metrics.append(("相邻补充", f"{adjacent_added:,}"))
    rendered_metrics = "".join(
        '<div class="deep-retrieval-stat'
        + (' is-scope' if label == "全库范围" else '')
        + '">'
        f"<span>{html.escape(label)}</span><strong>{html.escape(count)}</strong>"
        "</div>"
        for label, count in metrics
    )
    database_unavailable = value.get("database_available") is False
    retrieval_incomplete = (
        value.get("retrieval_complete") is False or bool(value.get("timed_out"))
    )
    retrieval_error = str(value.get("retrieval_error") or "").strip()
    total_queries = _retrieval_stat_count(
        value,
        ("subquery_count", "query_count"),
    )
    completed_queries = _retrieval_stat_count(
        value,
        (
            "completed_subquery_count",
            "attempted_subquery_count",
            "completed_query_count",
        ),
    )
    if total_queries is not None and completed_queries is None:
        completed_queries = 0
    status_html = ""
    if database_unavailable:
        status_title = "全库索引不可用"
        status_class = " is-error"
    elif retrieval_incomplete:
        completion = (
            f" {completed_queries}/{total_queries}"
            if completed_queries is not None and total_queries is not None
            else ""
        )
        status_title = f"部分完成{completion}"
        status_class = " is-warning"
    elif retrieval_error:
        status_title = "检索提示"
        status_class = " is-warning"
    else:
        status_title = ""
        status_class = ""
    if status_title:
        status_detail = (
            f"<span>{html.escape(retrieval_error)}</span>" if retrieval_error else ""
        )
        status_html = (
            f'<div class="deep-retrieval-status{status_class}">'
            f"<strong>{html.escape(status_title)}</strong>{status_detail}</div>"
        )
    st.markdown(
        '<div class="deep-retrieval-stats" aria-label="全库深度检索统计">'
        '<div class="deep-retrieval-stats-heading">'
        '<div class="deep-retrieval-stats-title">全库深度检索</div>'
        f"{status_html}</div>"
        f'<div class="deep-retrieval-stats-values">{rendered_metrics}</div>'
        "</div>",
        unsafe_allow_html=True,
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
    visible_missing_data = [
        str(item)
        for item in plan.get("missing_data", [])
        if not re.search(r"文献|原文|页码|DOI|来源", str(item), flags=re.IGNORECASE)
    ]
    missing_data = "；".join(visible_missing_data) or "暂无额外业务或检测资料待补"
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


def render_processing_flow_summary(plan: dict[str, Any]) -> None:
    """Show only the decision-critical route in the default answer view."""
    flow = [str(step).strip() for step in plan.get("flow", []) if str(step).strip()]
    if not flow:
        return
    st.markdown(
        '<div class="processing-flow-summary" aria-label="核心加工流程">'
        '<span>核心流程</span>'
        f'<p>{html.escape(" → ".join(flow))}</p>'
        '</div>',
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


def _compact_analysis_narrative(value: Any) -> str:
    """Keep substantive analysis while moving source metadata into its expander."""
    hidden_sections = {
        "文献证据及其适用边界",
        "本次引用文献",
        "参考文献",
        "引用文献",
        "参考资料",
        "原文证据",
        "证据来源",
        "来源与页码",
        "参考文献及来源",
    }
    output: list[str] = []
    skipping = False
    for line in str(value or "").splitlines():
        heading_match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if heading_match:
            heading = re.sub(r"[*_`~：:\s]", "", heading_match.group(1))
            base_heading = re.sub(r"[（(][^）)]*[）)]$", "", heading)
            if base_heading in hidden_sections:
                skipping = True
                continue
            skipping = False
        if skipping:
            continue
        if re.match(r"^\s*(?:完整报告|报告路径|报告已保存到)\s*[：:].*$", line):
            continue
        output.append(re.sub(r"\s*\[文献\s*\d+\]", "", line))
    compacted = re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()
    return _compact_visible_answer(compacted)


def _compact_visible_answer(value: Any, *, max_chars: int | None = None) -> str:
    """Remove duplicate lines and citation metadata without truncating prose."""
    _ = max_chars  # Compatibility for persisted code paths from earlier deployments.
    compactor = getattr(orchestrator, "compact_primary_answer", None)
    if callable(compactor):
        try:
            return str(compactor(str(value or ""), max_chars=None))
        except TypeError:
            # An old hot-loaded module expected an integer limit. Use the local
            # compatibility cleaner until Streamlit completes its full restart.
            pass
    reference_labels = (
        "本次引用文献",
        "参考文献",
        "引用文献",
        "参考资料",
        "文献证据",
        "原文证据",
        "证据来源",
        "来源与页码",
        "参考文献及来源",
    )
    output: list[str] = []
    seen_content: set[str] = set()
    skipping_reference_section = False
    for line in str(value or "").splitlines():
        heading_match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        label_source = heading_match.group(1) if heading_match else line
        normalized_label = re.sub(r"[*_`~：:\s]", "", label_source)
        base_label = re.sub(
            r"[（(][^）)]*[）)]$",
            "",
            normalized_label,
        )
        is_reference_heading = base_label in reference_labels
        if is_reference_heading:
            skipping_reference_section = True
            continue
        if skipping_reference_section:
            if not heading_match:
                continue
            skipping_reference_section = False
        if re.match(r"^\s*(?:[-*+]\s*)?\[?文献\s*\d+", line, flags=re.IGNORECASE) and re.search(
            r"(?:第\s*\d+\s*页|页码|DOI\b|来源[：:])",
            line,
            flags=re.IGNORECASE,
        ):
            continue
        cleaned_line = re.sub(
            r"\s*[\[【（(]\s*文献\s*\d+(?:\s*[,，、-]\s*(?:文献\s*)?\d+)*\s*[\]】）)]",
            "",
            line,
            flags=re.IGNORECASE,
        )
        cleaned_line = re.sub(r"[ \t]+([，。！？；：])", r"\1", cleaned_line)
        sentence_parts = re.split(r"(?<=[。！？])", cleaned_line)
        if len(sentence_parts) > 1:
            unique_parts: list[str] = []
            seen_parts: set[str] = set()
            for part in sentence_parts:
                comparable_part = re.sub(r"[*_`~\s]", "", part).strip()
                if comparable_part and comparable_part in seen_parts:
                    continue
                if comparable_part:
                    seen_parts.add(comparable_part)
                unique_parts.append(part)
            cleaned_line = "".join(unique_parts)
        comparable = re.sub(
            r"[*_`~\s]",
            "",
            re.sub(r"^\s*(?:[-*+]\s*|\d+[.、]\s*)", "", cleaned_line),
        )
        if cleaned_line.strip() and not heading_match:
            if comparable in seen_content:
                continue
            seen_content.add(comparable)
        output.append(cleaned_line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


_EVIDENCE_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060\ufeff]"
)
_EVIDENCE_PAGE_LINE_RE = re.compile(
    r"^(?:第\s*\d{1,4}\s*页|page\s+\d{1,4}(?:\s+of\s+\d{1,4})?)$",
    flags=re.IGNORECASE,
)
_EVIDENCE_NOISE_LINE_RE = re.compile(
    r"^(?:https?://\S+|www\.\S+|downloaded\s+from\b.*|copyright\b.*|all\s+rights\s+reserved\b.*)$",
    flags=re.IGNORECASE,
)
_EVIDENCE_PARAMETER_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|°\s*[CF]|℃|K|MPa|kPa|Pa|bar|rpm|r/min|g|kg|mg|μg|ug|mL|ml|L|h|min|s|d|天|小时|分钟|秒)|"
    r"温度|时间|压力|转速|浓度|得率|产率|含量|显著|temperature|time|pressure|yield|content)",
    flags=re.IGNORECASE,
)
_EVIDENCE_METADATA_RE = re.compile(
    r"^\s*serial\s+JL\b.*\barticleinfo\b.*\bcontenttype\b.*\bdateloaded(?:txt)?\b",
    flags=re.IGNORECASE | re.DOTALL,
)
_EVIDENCE_METADATA_MESSAGE = "该片段主要是文献索引元数据，未提取到可核验的正文信息。"


def _is_evidence_metadata_blob(value: Any) -> bool:
    return bool(_EVIDENCE_METADATA_RE.search(str(value or "")))


def clean_evidence_display_text(value: Any, *, page_numbers: Any = None) -> str:
    """Clean OCR display noise without changing the stored evidence payload."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    if _is_evidence_metadata_blob(text):
        return ""
    text = _EVIDENCE_CONTROL_RE.sub("", text)
    text = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "-", text)
    page_candidates = (
        page_numbers
        if isinstance(page_numbers, (list, tuple, set))
        else [page_numbers]
    )
    known_pages = {
        str(page).strip() for page in page_candidates if page not in (None, "")
    }
    raw_lines = [
        re.sub(r"[ \t]+", " ", raw_line).strip()
        for raw_line in text.splitlines()
    ]
    nonempty_indexes = [index for index, line in enumerate(raw_lines) if line]
    drop_indexes: set[int] = set()
    for position, index in enumerate(nonempty_indexes):
        line = raw_lines[index]
        if line not in known_pages or not re.fullmatch(r"\d{1,4}", line):
            continue
        if position == 0 or position == len(nonempty_indexes) - 1:
            drop_indexes.add(index)
        elif position == 1:
            drop_indexes.add(index)
            header_index = nonempty_indexes[0]
            header = raw_lines[header_index]
            if (
                len(header) <= 80
                and not _EVIDENCE_PARAMETER_RE.search(header)
                and not re.search(r"[。.!?；;:]", header)
            ):
                drop_indexes.add(header_index)
    lines: list[str] = []
    for index, line in enumerate(raw_lines):
        if index in drop_indexes:
            continue
        if not line or _EVIDENCE_PAGE_LINE_RE.fullmatch(line):
            continue
        if re.fullmatch(r"(?:\|?\s*:?-{3,}:?\s*)+\|?", line):
            continue
        if _EVIDENCE_NOISE_LINE_RE.match(line):
            continue
        line = re.sub(r"~~([^~]+)~~", r"\1", line)
        line = re.sub(r"(^|\s)#{1,6}\s+", r"\1", line)
        lines.append(line)
    cleaned = " ".join(lines)
    cleaned = re.sub(r"\s+([,.;:!?，。；：！？、）】])", r"\1", cleaned)
    cleaned = re.sub(r"([（【])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return re.sub(r"^(?:[|¦•·▪►◆◇]+\s*)+", "", cleaned)


def full_evidence_display_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    if _is_evidence_metadata_blob(text):
        return _EVIDENCE_METADATA_MESSAGE
    return _EVIDENCE_CONTROL_RE.sub("", text).strip()


def _evidence_match_terms(value: Any) -> list[str]:
    candidates = value if isinstance(value, (list, tuple, set)) else [value]
    terms: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        term = re.sub(r"\s+", " ", str(candidate or "")).strip()
        comparable = term.casefold()
        if (
            len(term) < 2
            or comparable.startswith("concept_")
            or comparable in seen
        ):
            continue
        seen.add(comparable)
        terms.append(term)
    return sorted(terms, key=lambda item: (-len(item), item.casefold()))[:16]


def _split_evidence_sentences(text: str) -> list[str]:
    parts = re.split(
        r"(?<=[。！？!?；;])\s*|(?<=\.)\s+(?=[A-Z\u4e00-\u9fff])",
        text,
    )
    sentences = [part.strip() for part in parts if part and part.strip()]
    if len(sentences) <= 1 and text:
        clauses = re.split(r"(?<=[，,：:])\s*", text)
        sentences = [part.strip() for part in clauses if part and part.strip()]
    return sentences


def _join_evidence_text(left: str, right: str) -> str:
    if not left or not right:
        return left + right
    needs_space = (
        left[-1].isascii()
        and right[0].isascii()
        and (left[-1].isalnum() or left[-1] in ".,;:!?)%")
        and (right[0].isalnum() or right[0] in "([")
    )
    return left + (" " if needs_space else "") + right


def _crop_evidence_sentence(
    sentence: str,
    terms: list[str],
    *,
    max_chars: int,
) -> str:
    if len(sentence) <= max_chars:
        return sentence
    clauses = [
        part.strip()
        for part in re.split(r"(?<=[，,；;：:])\s*", sentence)
        if part and part.strip()
    ]
    comparable_terms = [term.casefold() for term in terms]
    hit_index = next(
        (
            index
            for index, clause in enumerate(clauses)
            if any(term in clause.casefold() for term in comparable_terms)
        ),
        0,
    )
    selected = clauses[hit_index] if clauses else sentence
    left = hit_index - 1
    right = hit_index + 1
    while clauses and (left >= 0 or right < len(clauses)):
        candidate_index = left if left >= 0 else right
        candidate = clauses[candidate_index]
        combined = (
            _join_evidence_text(candidate, selected)
            if candidate_index < hit_index
            else _join_evidence_text(selected, candidate)
        )
        if len(combined) > max_chars:
            if candidate_index < hit_index:
                left = -1
            else:
                right = len(clauses)
            continue
        selected = combined
        if candidate_index < hit_index:
            left -= 1
        else:
            right += 1
    if len(selected) > max_chars:
        lowered = selected.casefold()
        hit = min(
            (lowered.find(term) for term in comparable_terms if term in lowered),
            default=0,
        )
        start = max(0, min(hit - max_chars // 3, len(selected) - max_chars))
        end = min(len(selected), start + max_chars)
        selected = selected[start:end].strip()
    prefix = "…" if hit_index > 0 or selected != sentence[: len(selected)] else ""
    suffix = "…" if hit_index < len(clauses) - 1 or len(selected) < len(sentence) else ""
    available = max(1, max_chars - len(prefix) - len(suffix))
    if len(selected) > available:
        selected = selected[:available].rstrip()
        suffix = "…"
    return f"{prefix}{selected}{suffix}"


def build_evidence_excerpt(
    value: Any,
    matched_terms: Any = None,
    *,
    max_chars: int = 420,
    page_numbers: Any = None,
) -> str:
    """Select compact, sentence-level evidence for display."""
    if _is_evidence_metadata_blob(value):
        return _EVIDENCE_METADATA_MESSAGE
    text = clean_evidence_display_text(value, page_numbers=page_numbers)
    if not text:
        return "暂无可展示的原文片段。"
    sentences = _split_evidence_sentences(text)
    if not sentences:
        return text[:max_chars]
    terms = _evidence_match_terms(matched_terms)
    lowered_terms = [term.casefold() for term in terms]

    def sentence_score(sentence: str) -> tuple[int, int, int]:
        lowered = sentence.casefold()
        hits = [term for term in lowered_terms if term in lowered]
        parameter_bonus = 1 if _EVIDENCE_PARAMETER_RE.search(sentence) else 0
        return (len(hits), sum(len(term) for term in hits), parameter_bonus)

    ranked = sorted(
        range(len(sentences)),
        key=lambda index: (sentence_score(sentences[index]), -index),
        reverse=True,
    )
    hit_indexes = [
        index for index in ranked if sentence_score(sentences[index])[0] > 0
    ]
    primary = hit_indexes[0] if hit_indexes else (ranked[0] if ranked else 0)
    priority = list(hit_indexes[:2]) or [primary]
    priority.extend(index for index in (primary - 1, primary + 1) if 0 <= index < len(sentences))
    priority.extend(ranked)

    selected: list[int] = []
    for index in priority:
        if index in selected:
            continue
        projected = sum(len(sentences[item]) for item in selected) + len(sentences[index])
        projected += len(selected) + 2
        if projected <= max_chars:
            selected.append(index)
        elif not selected:
            selected.append(index)
        if len(selected) >= (3 if len("".join(sentences[item] for item in selected)) < 280 else 2):
            break

    def assemble(indexes: list[int]) -> str:
        ordered = sorted(indexes)
        parts: list[str] = []
        previous: int | None = None
        for index in ordered:
            if previous is not None and index > previous + 1:
                parts.append("…")
            sentence = sentences[index]
            if parts and parts[-1] != "…":
                parts[-1] = _join_evidence_text(parts[-1], sentence)
            else:
                parts.append(sentence)
            previous = index
        excerpt_value = "".join(parts).strip()
        if ordered[0] > 0:
            excerpt_value = "…" + excerpt_value
        if ordered[-1] < len(sentences) - 1:
            excerpt_value += "…"
        return excerpt_value

    excerpt = assemble(selected)
    while len(excerpt) > max_chars and len(selected) > 1:
        removable = next(
            (index for index in reversed(selected) if index != primary),
            selected[-1],
        )
        selected.remove(removable)
        excerpt = assemble(selected)
    if len(excerpt) > max_chars:
        parameter_match = _EVIDENCE_PARAMETER_RE.search(excerpt)
        crop_terms = terms or ([parameter_match.group(0)] if parameter_match else [])
        excerpt = _crop_evidence_sentence(excerpt, crop_terms, max_chars=max_chars)
    return excerpt


def highlight_evidence_excerpt(value: Any, matched_terms: Any = None) -> str:
    text = str(value or "")
    terms = _evidence_match_terms(matched_terms)
    spans: list[tuple[int, int]] = []
    for term in terms:
        for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE):
            start, end = match.span()
            if any(start < existing_end and end > existing_start for existing_start, existing_end in spans):
                continue
            spans.append((start, end))
    spans.sort()
    if not spans:
        return html.escape(text)
    fragments: list[str] = []
    cursor = 0
    for start, end in spans:
        fragments.append(html.escape(text[cursor:start]))
        fragments.append(
            '<mark class="evidence-match">' + html.escape(text[start:end]) + "</mark>"
        )
        cursor = end
    fragments.append(html.escape(text[cursor:]))
    return "".join(fragments)


def evidence_location_labels(item: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    section = str(item.get("section") or "").strip()
    if section and section.casefold() not in {"unknown", "未标注章节", "none"}:
        labels.append(f"章节：{section}")
    page_start = item.get("page_start")
    page = item.get("page")
    page_end = item.get("page_end")
    start = page_start if page_start not in (None, "") else page
    if start not in (None, ""):
        if page_end not in (None, "") and str(page_end) != str(start):
            labels.append(f"PDF 第 {start}–{page_end} 页")
        else:
            labels.append(f"PDF 第 {start} 页")
    chunk_id = item.get("chunk_id")
    chunk_index = item.get("chunk_index")
    if chunk_id not in (None, ""):
        labels.append(f"片段：{chunk_id}")
    elif chunk_index not in (None, ""):
        labels.append(f"片段序号：{chunk_index}")
    return labels


def _evidence_source_label(item: Mapping[str, Any]) -> str:
    source = item.get("source") or item.get("publication")
    if source not in (None, ""):
        source_label = str(source).strip()
        if (
            re.match(r"^(?:[A-Za-z]:[\\/]|[\\/])", source_label)
            or (re.search(r"\.(?:pdf|docx?|txt)$", source_label, flags=re.IGNORECASE) and re.search(r"[\\/]", source_label))
        ):
            return re.split(r"[\\/]", source_label)[-1] or "本地文献库"
        return source_label
    source_file = str(item.get("source_file") or "").strip()
    if source_file:
        return re.split(r"[\\/]", source_file)[-1] or "本地文献库"
    return "本地文献库"


def render_adjacent_evidence(value: Any) -> None:
    if not isinstance(value, list):
        return
    rows: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        labels = evidence_location_labels(item) or ["定位信息未标注"]
        locator = "".join(
            f"<span>{html.escape(label)}</span>" for label in labels
        )
        excerpt = build_evidence_excerpt(
            item.get("chunk_text"),
            item.get("matched_terms"),
            max_chars=300,
            page_numbers=(item.get("page"), item.get("page_start"), item.get("page_end")),
        )
        rows.append(
            '<article class="adjacent-evidence-item">'
            '<div class="adjacent-evidence-context">补充上下文</div>'
            f'<div class="adjacent-evidence-meta">{locator}</div>'
            f'<div class="adjacent-evidence-excerpt">{highlight_evidence_excerpt(excerpt, item.get("matched_terms"))}</div>'
            "</article>"
        )
    if not rows:
        return
    count = len(rows)
    st.markdown(
        '<details class="adjacent-evidence" aria-label="同篇文献补充上下文">'
        f"<summary>同篇文献补充上下文（{count}）</summary>"
        f'<div class="adjacent-evidence-list">{"".join(rows)}</div>'
        "</details>",
        unsafe_allow_html=True,
    )


def parameter_source_location(item: Mapping[str, Any]) -> str:
    sources = item.get("source_refs") or item.get("source_ids") or []
    if isinstance(sources, str):
        return sources
    return "｜".join(str(source) for source in sources if str(source).strip())


def render_key_conclusion_evidence(conclusions: list[Mapping[str, Any]]) -> None:
    """Render an explicit conclusion-to-source mapping produced by the backend."""
    if not conclusions:
        st.info("本轮没有形成可展示的关键结论证据卡。")
        return
    for index, item in enumerate(conclusions, 1):
        if not isinstance(item, Mapping):
            continue
        conclusion = html.escape(str(item.get("conclusion") or "待核验结论"))
        conclusion_type = html.escape(str(item.get("conclusion_type") or "关键结论"))
        level = str(item.get("evidence_level") or agent_evidence.INSUFFICIENT_EVIDENCE)
        reason = html.escape(str(item.get("evidence_level_reason") or "未完成证据判定"))
        applicability = html.escape(str(item.get("applicability") or "适用条件待确认"))
        references: list[str] = []
        for ref in list(item.get("evidence") or [])[:3]:
            if not isinstance(ref, Mapping):
                continue
            title = html.escape(str(ref.get("title") or "未命名文献"))
            year = html.escape(str(ref.get("year") or "年份未知"))
            doi = agent_evidence.normalize_doi(ref.get("doi"))
            url = agent_evidence.source_url(ref) or str(ref.get("url") or "")
            if url.startswith(("http://", "https://")):
                label = f"DOI {doi}" if doi else "原文链接"
                link_html = (
                    f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                    f'rel="noopener noreferrer">{html.escape(label)}</a>'
                )
            else:
                link_html = "DOI/链接未收录"
            excerpt = html.escape(str(ref.get("excerpt") or "未提供可核验原文片段"))
            ref_applicability = html.escape(
                str(ref.get("applicability") or "需回查原文确认研究对象和试验条件")
            )
            references.append(
                '<div class="key-conclusion-reference">'
                f'<div><strong>{title}</strong>（{year}；{link_html}）</div>'
                f'<div><strong>原文片段：</strong>{excerpt}</div>'
                f'<div><strong>文献适用条件：</strong>{ref_applicability}</div>'
                "</div>"
            )
        if not references:
            references.append(
                '<div class="key-conclusion-reference-empty">'
                "未绑定可核验文献；该结论不得包装为文献直接结论。"
                "</div>"
            )
        st.markdown(
            '<article class="key-conclusion-evidence-card">'
            f'<div class="key-conclusion-type">{conclusion_type} {index:02d}</div>'
            f'<div class="key-conclusion-text">{conclusion}</div>'
            f'<div class="key-conclusion-level" data-evidence-level="{html.escape(level, quote=True)}">'
            f'<strong>证据等级：</strong>{html.escape(level)}</div>'
            f'<div><strong>判定说明：</strong>{reason}</div>'
            f'<div><strong>适用条件：</strong>{applicability}</div>'
            + "".join(references)
            + "</article>",
            unsafe_allow_html=True,
        )


def render_reference_evidence(
    evidence: list[Mapping[str, Any]],
    *,
    include_adjacent: bool = False,
) -> None:
    if not evidence:
        st.info("没有检索到可用的本地资料。")
        return
    for index, item in enumerate(evidence, 1):
        if not isinstance(item, Mapping):
            continue
        title = html.escape(str(item.get("title") or "未命名文献"))
        year = html.escape(str(item.get("year") or "年份未知"))
        source = html.escape(_evidence_source_label(item))
        topic = item.get("topic") or item.get("category") or item.get("product")
        doi = agent_evidence.normalize_doi(item.get("doi"))
        url = agent_evidence.source_url(item)
        level = str(item.get("evidence_level") or agent_evidence.effective_evidence_level(item))
        level_reason = html.escape(str(item.get("evidence_level_reason") or "按保守规则自动分级"))
        applicability = html.escape(
            str(item.get("applicability") or agent_evidence.build_applicability(item))
        )
        match_score = item.get("match_score")
        labels = evidence_location_labels(item) or ["定位信息未标注"]
        locator_html = "".join(
            f"<span>{html.escape(label)}</span>" for label in labels
        )
        source_parts = [f"来源：{source}"]
        if topic not in (None, ""):
            source_parts.append(f"主题：{html.escape(str(topic))}")
        if url:
            link_label = f"DOI {doi}" if doi else "原文链接"
            source_parts.append(
                f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{html.escape(link_label)}</a>'
            )
        elif doi:
            source_parts.append(f"DOI：{html.escape(doi)}")
        score_html = (
            f'<span class="reference-evidence-score" title="检索匹配度不等于证据强度">检索匹配度 {html.escape(str(match_score))}</span>'
            if match_score not in (None, "")
            else ""
        )
        raw_text = str(item.get("chunk_text") or "")
        excerpt = build_evidence_excerpt(
            raw_text,
            item.get("matched_terms"),
            page_numbers=(item.get("page"), item.get("page_start"), item.get("page_end")),
        )
        excerpt_html = highlight_evidence_excerpt(excerpt, item.get("matched_terms"))
        full_text = full_evidence_display_text(raw_text)
        full_text_html = html.escape(full_text or "暂无可展示的原文片段。")
        st.markdown(
            '<article class="reference-evidence-item">'
            '<header class="reference-evidence-head">'
            f'<div class="reference-evidence-index">文献 {index:02d}</div>'
            '<div class="reference-evidence-title-row">'
            f'<div class="reference-evidence-title">{title}</div>'
            f'<span class="reference-evidence-year">{year}</span>'
            f'<span class="reference-evidence-level">{html.escape(level)}</span>{score_html}'
            "</div></header>"
            + f'<div class="reference-evidence-locator">{locator_html}</div>'
            + '<div class="reference-evidence-source">'
            + "<span> · </span>".join(source_parts)
            + "</div>"
            f'<div class="reference-evidence-level-reason"><strong>分级说明：</strong>{level_reason}</div>'
            f'<div class="reference-evidence-applicability"><strong>适用条件：</strong>{applicability}</div>'
            '<div class="reference-evidence-focus-label">关键信息</div>'
            f'<div class="reference-evidence-excerpt">{excerpt_html}</div>'
            '<details class="reference-evidence-full">'
            '<summary>查看完整原文片段</summary>'
            f'<div>{full_text_html}</div>'
            "</details>"
            "</article>",
            unsafe_allow_html=True,
        )
        if include_adjacent:
            render_adjacent_evidence(item.get("adjacent_chunks"))


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

    parameterized_text = ""
    if processing_plan:
        parameterized_text = agent_report.parameterized_plan_markdown(
            result.get("parameterized_plan") or {},
            result.get("parameter_groups") or [],
            result.get("processing_intent") or {},
            include_source_metadata=False,
            include_flow=False,
        )
        parameterized_text = re.sub(r"(?m)^### 5\.\d+\s+", "### ", parameterized_text)

    # The structured plan carries the workflow and parameters once; the narrative
    # that follows explains the decision without repeating those details.
    if processing_plan:
        render_processing_plan(processing_plan)
        if parameterized_text:
            st.markdown(parameterized_text)

    narrative_answer = _compact_analysis_narrative(
        orchestrator.strip_primary_processing_flow(
            orchestrator.strip_key_conclusion_evidence(answer)
        )
    )
    if narrative_answer:
        st.markdown(narrative_answer)

    if payload.get("vision_result"):
        with st.expander("图片识别结果", expanded=False):
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

    with st.expander("关键结论证据", expanded=True):
        render_key_conclusion_evidence(result.get("key_conclusions") or [])
        st.caption("证据等级由后端确定性规则生成；检索匹配度仅用于排序，不能把弱相关材料升级为直接证据。")

    with st.expander("参考依据（全部文献）", expanded=False):
        render_deep_retrieval_stats(
            result.get("deep_retrieval_stats")
            or payload.get("deep_retrieval_stats")
        )
        render_reference_evidence(evidence, include_adjacent=True)

    with st.expander("工艺参数证据", expanded=False):
        parameter_groups = [
            item
            for item in (result.get("parameter_groups") or [])
            if agent_process_knowledge.is_public_parameter_group(item)
        ]
        if parameter_groups:
            rows = []
            for item in parameter_groups:
                rows.append(
                    {
                        "步骤": item.get("process_step"),
                        "参数": item.get("parameter_name"),
                        "推荐/报告值": item.get("recommended_range"),
                        "可信度": item.get("confidence_level"),
                        "证据等级": item.get("evidence_level") or "证据不足",
                        "原料/对象": item.get("raw_material"),
                        "规模": item.get("scale"),
                        "方法": item.get("process_method"),
                        "是否冲突": "是" if item.get("conflict") else "否",
                        "来源ID": "、".join(item.get("source_ids") or []),
                        "来源定位": parameter_source_location(item),
                    }
                )
            ui_components.render_light_table(
                rows,
                "未提取到可展示的可靠工艺参数。",
                height=420,
            )
            st.caption("单篇文献值不等于通用生产参数；请展开报告核对适用条件、页码和原文片段。")
        else:
            st.info("暂无可靠参数；系统不会展示或自动补写不匹配、缺单位或分析仪器条件中的数值。")

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


def render_message_persistence_warning(message: Mapping[str, Any]) -> None:
    warning = str(message.get("persistence_warning") or "").strip()
    if warning:
        st.warning(warning)


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
        render_message_persistence_warning(message)
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
        render_message_persistence_warning(message)
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
        message_evidence = message.get("evidence")
        retrieval_stats = message.get("deep_retrieval_stats")
        if isinstance(message_evidence, list) or isinstance(retrieval_stats, dict):
            with st.expander("参考依据", expanded=False):
                render_deep_retrieval_stats(retrieval_stats)
                if isinstance(message_evidence, list):
                    render_reference_evidence(message_evidence)
        render_message_persistence_warning(message)


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
                                        <div class="task-card-icon">{ui_components.icon_svg(str(card['icon']), 24)}</div>
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


def render_agent_progress(
    slot: Any,
    message: str,
    *,
    reveal_id: str | None = None,
    retrieval_mode: str = "quick",
) -> None:
    safe_message = html.escape(message)
    normalized_mode = normalize_retrieval_mode(retrieval_mode)
    subtitle = "全库深度检索" if normalized_mode == "deep" else "Agent 正在运行"
    mode_class = " is-deep" if normalized_mode == "deep" else ""
    slot.markdown(
        f"""
        <div class="agent-live-progress" role="status" aria-live="polite">
            <div class="agent-live-spinner"></div>
            <div class="agent-live-copy">
                <div class="agent-live-title">{safe_message}</div>
                <div class="agent-live-subtitle{mode_class}">
                    <span>{subtitle}</span>
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
                history.append(
                    {
                        "role": "assistant",
                        "content": orchestrator.strip_key_conclusion_evidence(content),
                    }
                )
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
    retrieval_mode: str = "quick",
) -> tuple[str, dict[str, Any]]:
    normalized_mode = normalize_retrieval_mode(retrieval_mode)
    retrieval_result = retrieve_general_literature(
        prompt,
        top_k=24 if normalized_mode == "deep" else 10,
        history=history,
        retrieval_mode=normalized_mode,
        return_metadata=True,
    )
    if isinstance(retrieval_result, dict):
        evidence = list(retrieval_result.get("evidence") or [])
        deep_retrieval_stats = retrieval_result.get("deep_retrieval_stats") or {}
    else:
        evidence = list(retrieval_result or [])
        deep_retrieval_stats = {}
    trace_evidence = list(evidence)
    trace: dict[str, Any] = {
        "literature_ids": [
            str(item.get("chunk_id") or item.get("document_id") or item.get("source_file") or "")
            for item in trace_evidence
            if item.get("chunk_id") or item.get("document_id") or item.get("source_file")
        ],
        "model_name": DEEPSEEK_MODEL if api_key else "local-evidence-fallback",
        "model_raw_output": "",
        "model_context_manifest": {},
        "error": "",
        "deep_retrieval_stats": deep_retrieval_stats,
        "evidence": [
            {
                key: item.get(key)
                for key in (
                    "document_id",
                    "chunk_id",
                    "chunk_index",
                    "title",
                    "year",
                    "chunk_text",
                    "page",
                    "page_start",
                    "page_end",
                    "section",
                    "doi",
                    "source",
                    "source_file",
                    "publication",
                    "topic",
                    "category",
                    "product",
                    "match_score",
                    "matched_terms",
                )
                if item.get(key) not in (None, "")
            }
            for item in trace_evidence
            if isinstance(item, dict)
        ],
    }
    if not api_key:
        if evidence:
            return (
                "已找到相关本地资料，但当前未配置语言模型，暂不能安全地综合结论。"
                "原始资料已放在下方“参考依据”中。",
                trace,
            )
        return "若要普通大模型问答，请先配置 DeepSeek API Key；本轮也未检索到可直接返回的本地文献证据。", trace
    messages = build_general_chat_messages(
        history,
        prompt,
        memory_context=memory_context,
        evidence=evidence,
        retrieval_mode=normalized_mode,
    )
    trace["model_context_manifest"] = agent_memory.describe_model_messages(messages)
    try:
        answer = chat_with_deepseek(api_key, messages)
        trace["model_raw_output"] = answer
        return _compact_visible_answer(answer), trace
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


MESSAGE_PERSISTENCE_WARNING = (
    "回答已生成并保留在当前页面，但暂时未能写入对话历史。"
    "刷新或重启后这条回答可能丢失，请稍后重试或联系管理员。"
)


def _build_assistant_persistence_spec(
    *,
    user_id: str,
    session_id: str,
    project_id: str,
    assistant_message: dict[str, Any],
    assistant_text: str,
    mode: str,
    metadata: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    vision_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message_id = str(
        assistant_message.setdefault("message_id", f"msg_{uuid4().hex}")
    )
    resolved_metadata = dict(metadata or {})
    if not metadata:
        run_id = str(assistant_message.get("run_id") or "")
        audit_trace = assistant_message.get("audit_trace")
        if run_id:
            resolved_metadata["run_id"] = run_id
        if isinstance(audit_trace, dict) and audit_trace:
            resolved_metadata["audit_trace"] = audit_trace
        deep_stats = assistant_message.get("deep_retrieval_stats")
        if isinstance(deep_stats, dict) and deep_stats:
            resolved_metadata["deep_retrieval_stats"] = _json_serializable(deep_stats)
        evidence = assistant_message.get("evidence")
        if isinstance(evidence, list) and evidence:
            resolved_metadata["evidence"] = _json_serializable(evidence)
        if mode == "analysis":
            resolved_metadata["analysis_payload"] = build_persisted_analysis_payload(payload)
        elif mode == "vision" and isinstance((vision_payload or {}).get("vision_result"), dict):
            resolved_metadata["vision_result"] = _without_raw_model_output(
                (vision_payload or {})["vision_result"]
            )
    return {
        "user_id": str(user_id),
        "session_id": str(session_id),
        "project_id": str(project_id),
        "role": "assistant",
        "content": str(assistant_text),
        "message_id": message_id,
        "message_type": "analysis" if mode == "analysis" else "chat",
        "metadata": resolved_metadata,
    }


def _set_assistant_persistence_state(
    assistant_message: dict[str, Any],
    spec: dict[str, Any],
    *,
    persisted: bool,
    error: str = "",
) -> None:
    state = dict(spec)
    state["persisted"] = bool(persisted)
    state["error"] = str(error or "")
    assistant_message["_persistence"] = state
    if persisted:
        assistant_message.pop("persistence_warning", None)
    else:
        assistant_message["persistence_warning"] = MESSAGE_PERSISTENCE_WARNING


def _persist_assistant_spec(
    manager: agent_memory.MemoryManager,
    spec: Mapping[str, Any],
) -> str:
    return manager.record_message(
        str(spec.get("user_id") or ""),
        str(spec.get("session_id") or ""),
        str(spec.get("project_id") or ""),
        "assistant",
        str(spec.get("content") or ""),
        message_id=str(spec.get("message_id") or ""),
        message_type=str(spec.get("message_type") or "chat"),
        metadata=dict(spec.get("metadata") or {}),
    )


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
    run_id = str(assistant_message.setdefault("run_id", f"run_{uuid4().hex}"))
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
    assistant_message.setdefault("message_id", f"msg_{uuid4().hex}")
    assistant_message["run_id"] = run_id
    assistant_message["audit_trace"] = audit_trace
    message_metadata: dict[str, Any] = {"run_id": run_id, "audit_trace": audit_trace}
    deep_retrieval_stats = (
        general_trace.get("deep_retrieval_stats")
        or result.get("deep_retrieval_stats")
        or payload.get("deep_retrieval_stats")
    )
    if isinstance(deep_retrieval_stats, dict) and deep_retrieval_stats:
        serialized_stats = _json_serializable(deep_retrieval_stats)
        assistant_message["deep_retrieval_stats"] = serialized_stats
        message_metadata["deep_retrieval_stats"] = serialized_stats
    general_evidence = general_trace.get("evidence")
    if mode != "analysis" and isinstance(general_evidence, list) and general_evidence:
        serialized_evidence = _json_serializable(general_evidence)
        assistant_message["evidence"] = serialized_evidence
        message_metadata["evidence"] = serialized_evidence
    if mode == "analysis":
        message_metadata["analysis_payload"] = build_persisted_analysis_payload(payload)
    elif mode == "vision" and isinstance(vision_payload.get("vision_result"), dict):
        message_metadata["vision_result"] = _without_raw_model_output(
            vision_payload["vision_result"]
        )

    persistence_spec = _build_assistant_persistence_spec(
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
        assistant_message=assistant_message,
        assistant_text=assistant_text,
        mode=mode,
        metadata=message_metadata,
        payload=payload,
        vision_payload=vision_payload,
    )
    message_persisted = False
    message_persistence_error = ""
    try:
        _persist_assistant_spec(manager, persistence_spec)
        message_persisted = True
    except (agent_memory.MemoryManagerError, sqlite3.Error, OSError) as error:
        message_persistence_error = str(error)
        audit_trace["error"] = message_persistence_error

    _set_assistant_persistence_state(
        assistant_message,
        persistence_spec,
        persisted=message_persisted,
        error=message_persistence_error,
    )
    audit_trace["message_persisted"] = message_persisted
    audit_trace["message_persistence_error"] = message_persistence_error

    audit_trace["history_summarized"] = False
    if message_persisted:
        try:
            manager.summarize_history(
                session_id,
                user_id=user_id,
                project_id=project_id,
                force=False,
            )
            audit_trace["history_summarized"] = True
        except (agent_memory.MemoryManagerError, sqlite3.Error, OSError) as error:
            existing_error = str(audit_trace.get("error") or "").strip()
            audit_trace["error"] = "；".join(
                item for item in (existing_error, str(error)) if item
            )

    audit_trace["agent_run_logged"] = False
    try:
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
                "error": str(audit_trace.get("error") or error_text),
            }
        )
        audit_trace["agent_run_logged"] = True
    except (agent_memory.MemoryManagerError, sqlite3.Error, OSError) as error:
        existing_error = str(audit_trace.get("error") or "").strip()
        audit_trace["error"] = "；".join(
            item for item in (existing_error, str(error)) if item
        )
    return audit_trace



def _current_agent_scope() -> agent_background.TaskScope:
    return (
        str(st.session_state.memory_user_id),
        str(st.session_state.memory_project_id),
        str(st.session_state.memory_session_id),
    )


def _execute_agent_job(
    request: Mapping[str, Any],
    update_progress: agent_background.ProgressCallback,
) -> dict[str, Any]:
    prompt = str(request["prompt"])
    resolved_prompt = str(request["resolved_prompt"])
    api_key = str(request.get("api_key") or "")
    history = list(request.get("history") or [])
    batch_for_turn = request.get("batch_for_turn")
    effective_observation = str(request.get("effective_observation") or "")
    has_image = bool(request.get("has_image"))
    image_bytes = request.get("image_bytes")
    image_mime_type = str(request.get("image_mime_type") or "image/jpeg")
    memory_context = dict(request.get("memory_context") or {})
    missing_inputs = list(request.get("missing_inputs") or [])
    stored_image_path = str(request.get("stored_image_path") or "")
    memory_errors = list(request.get("memory_errors") or [])
    vision_memory = dict(request.get("vision_memory") or {})
    previous_result = request.get("previous_result") or {}
    retrieval_mode = normalize_retrieval_mode(request.get("retrieval_mode"))

    assistant_text = ""
    assistant_message: dict[str, Any] = {}
    mode = "chat"
    result: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    vision_payload: dict[str, Any] = {}
    general_trace: dict[str, Any] = {}
    state_updates: dict[str, Any] = {}

    try:
        if request.get("is_previous_evidence_request"):
            update_progress("正在整理上一轮使用的文献证据")
            assistant_text = orchestrator.build_previous_evidence_answer(previous_result)
            result = previous_result
            assistant_message = {"role": "assistant", "content": assistant_text}
            mode = "previous_evidence"
        elif request.get("should_run_full_analysis"):
            update_progress(
                "正在扫描全库文献"
                if retrieval_mode == "deep"
                else "正在启动批次分析流程"
            )
            try:
                payload = orchestrator.run_analysis_turn(
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
                    retrieval_mode=retrieval_mode,
                )
            except Exception as error:
                general_trace["error"] = str(error)
                assistant_text = f"本轮批次分析未能完成：{error}"
                assistant_message = {"role": "assistant", "content": assistant_text}
                mode = "analysis_error"
            else:
                result = payload["result"]
                if stored_image_path:
                    payload["stored_image_path"] = stored_image_path
                assistant_text = str(payload.get("answer") or payload.get("summary") or "").strip()
                if payload.get("vision_result"):
                    state_updates["last_vision_context"] = orchestrator.build_vision_memory(payload)
                if has_image:
                    vision_payload = payload
                assistant_message = {
                    "role": "assistant",
                    "kind": "analysis",
                    "content": assistant_text,
                    "payload": payload,
                }
                state_updates["current_batch"] = payload["batch"]
                state_updates["last_result"] = payload["result"]
                mode = "analysis"
        elif has_image and image_bytes:
            general_trace["model_name"] = get_vision_model()
            if stored_image_path:
                vision_payload["stored_image_path"] = stored_image_path
            update_progress("正在读取图片并回答本轮问题")
            try:
                vision_payload = orchestrator.run_vision_turn(
                    user_prompt=prompt,
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type,
                )
                if stored_image_path:
                    vision_payload["stored_image_path"] = stored_image_path
                assistant_text = vision_payload["answer"]
                state_updates["last_vision_context"] = orchestrator.build_vision_memory(vision_payload)
                if orchestrator.should_request_batch_data(
                    resolved_prompt,
                    current_batch=batch_for_turn,
                    manual_observation=effective_observation,
                    has_image=has_image,
                ):
                    assistant_text += (
                        "\n\n图片已经纳入本轮分析。如需进一步生成加工路线分级和报告，"
                        + orchestrator.build_batch_data_request(missing_inputs)
                    )
            except Exception as error:
                state_updates["last_vision_context"] = None
                vision_payload["vision_status"] = "failed"
                assistant_text = f"图片已经收到，但视觉模型分析失败：{error}"
                general_trace["error"] = str(error)
            assistant_message = {
                "role": "assistant",
                "content": assistant_text,
                "vision_result": vision_payload.get("vision_result") or {},
            }
            mode = "vision"
        elif orchestrator.should_request_batch_data(
            resolved_prompt,
            current_batch=batch_for_turn,
            manual_observation=effective_observation,
            has_image=has_image,
        ):
            update_progress("正在核对批次信息")
            assistant_text = orchestrator.build_batch_data_request(missing_inputs)
            assistant_message = {"role": "assistant", "content": assistant_text}
            mode = "request_inputs"
        else:
            update_progress(
                "正在扫描全库文献并组织回答"
                if retrieval_mode == "deep"
                else "正在检索本地文献并组织专业回答"
            )
            try:
                assistant_text, general_trace = run_general_turn(
                    resolved_prompt,
                    api_key,
                    history,
                    memory_context=memory_context,
                    retrieval_mode=retrieval_mode,
                )
                assistant_text = orchestrator.ensure_vision_follow_up_answer(
                    assistant_text,
                    prompt,
                    vision_memory,
                )
            except Exception as error:
                general_trace["error"] = str(error)
                assistant_text = f"本轮检索或回答生成失败：{error}"
            assistant_message = {"role": "assistant", "content": assistant_text}
    except Exception as error:
        general_trace["error"] = str(error)
        assistant_text = f"本轮 Agent 任务未能完成：{error}"
        assistant_message = {"role": "assistant", "content": assistant_text}
        mode = "background_error"

    if memory_errors:
        existing_error = str(general_trace.get("error") or "").strip()
        general_trace["error"] = "；".join(
            item for item in [existing_error, *memory_errors] if item
        )

    trace_stats = general_trace.get("deep_retrieval_stats")
    if isinstance(trace_stats, dict) and trace_stats:
        assistant_message["deep_retrieval_stats"] = _json_serializable(trace_stats)
    trace_evidence = general_trace.get("evidence")
    if isinstance(trace_evidence, list) and trace_evidence:
        assistant_message["evidence"] = _json_serializable(trace_evidence)

    assistant_message.setdefault("message_id", f"msg_{uuid4().hex}")
    fallback_persistence_spec = _build_assistant_persistence_spec(
        user_id=str(request["user_id"]),
        session_id=str(request["session_id"]),
        project_id=str(request["project_id"]),
        assistant_message=assistant_message,
        assistant_text=assistant_text,
        mode=mode,
        payload=payload,
        vision_payload=vision_payload,
    )
    try:
        manager = agent_memory.MemoryManager()
        finalize_memory_turn(
            manager=manager,
            user_id=str(request["user_id"]),
            session_id=str(request["session_id"]),
            project_id=str(request["project_id"]),
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
    except Exception as error:
        persistence_spec = dict(
            assistant_message.get("_persistence") or fallback_persistence_spec
        )
        _set_assistant_persistence_state(
            assistant_message,
            persistence_spec,
            persisted=False,
            error=str(error),
        )

    return {
        "scope": (
            str(request["user_id"]),
            str(request["project_id"]),
            str(request["session_id"]),
        ),
        "assistant_message": assistant_message,
        "assistant_text": assistant_text,
        "mode": mode,
        "message_persistence": dict(assistant_message.get("_persistence") or {}),
        "state_updates": state_updates,
    }


def _active_agent_job_snapshot() -> agent_background.TaskSnapshot | None:
    runner = get_agent_task_runner()
    scope = _current_agent_scope()
    job_id = str(st.session_state.get("active_agent_job_id") or "")
    snapshot = runner.snapshot(job_id) if job_id else None
    if snapshot is not None and snapshot.scope != scope:
        st.session_state.active_agent_job_id = ""
        st.session_state.active_agent_retrieval_mode = ""
        snapshot = None
    if snapshot is None:
        job_id = runner.active_job(scope)
        if job_id:
            st.session_state.active_agent_job_id = job_id
            snapshot = runner.snapshot(job_id)
    return snapshot


def _append_agent_job_outcome(outcome: dict[str, Any]) -> bool:
    if tuple(outcome.get("scope") or ()) != _current_agent_scope():
        return False
    assistant_message = dict(outcome.get("assistant_message") or {})
    message_id = str(assistant_message.get("message_id") or "")
    changed = False
    existing_index = next(
        (
            index
            for index, item in enumerate(st.session_state.agent_messages)
            if isinstance(item, dict)
            and message_id
            and str(item.get("message_id") or "") == message_id
        ),
        None,
    )
    if existing_index is None:
        st.session_state.agent_messages.append(assistant_message)
        changed = True
    elif st.session_state.agent_messages[existing_index] != assistant_message:
        st.session_state.agent_messages[existing_index] = assistant_message
        changed = True
    for key, value in dict(outcome.get("state_updates") or {}).items():
        if key in {"current_batch", "last_result", "last_vision_context"}:
            if st.session_state.get(key) != value:
                st.session_state[key] = value
                changed = True
    st.session_state.clear_sidebar_inputs = True
    st.session_state.restore_main_scroll_position = True
    return changed


def _persistence_spec_scope(spec: Mapping[str, Any]) -> agent_background.TaskScope:
    return (
        str(spec.get("user_id") or ""),
        str(spec.get("project_id") or ""),
        str(spec.get("session_id") or ""),
    )


def _retry_agent_outcome_persistence(
    outcome: dict[str, Any],
    *,
    expected_scope: agent_background.TaskScope | None = None,
) -> dict[str, Any]:
    updated = dict(outcome)
    assistant_message = dict(updated.get("assistant_message") or {})
    scope = tuple(updated.get("scope") or ())
    if len(scope) != 3 or (expected_scope is not None and scope != expected_scope):
        return updated
    current_state = dict(
        assistant_message.get("_persistence") or updated.get("message_persistence") or {}
    )
    if current_state.get("persisted") is True:
        return updated
    spec = dict(
        current_state
        or _build_assistant_persistence_spec(
            user_id=str(scope[0]),
            project_id=str(scope[1]),
            session_id=str(scope[2]),
            assistant_message=assistant_message,
            assistant_text=str(updated.get("assistant_text") or assistant_message.get("content") or ""),
            mode=str(updated.get("mode") or "chat"),
            payload=dict(assistant_message.get("payload") or {}),
            vision_payload={"vision_result": assistant_message.get("vision_result") or {}},
        )
    )
    if (
        _persistence_spec_scope(spec) != scope
        or str(spec.get("message_id") or "")
        != str(assistant_message.get("message_id") or "")
    ):
        _set_assistant_persistence_state(
            assistant_message,
            spec,
            persisted=False,
            error="回答持久化作用域或消息编号不一致，已拒绝写入。",
        )
        assistant_message["_persistence"]["blocked"] = True
        updated["assistant_message"] = assistant_message
        updated["message_persistence"] = dict(assistant_message["_persistence"])
        return updated
    try:
        _persist_assistant_spec(get_memory_manager(), spec)
    except Exception as error:
        _set_assistant_persistence_state(
            assistant_message,
            spec,
            persisted=False,
            error=str(error),
        )
    else:
        _set_assistant_persistence_state(
            assistant_message,
            spec,
            persisted=True,
        )
    updated["assistant_message"] = assistant_message
    updated["message_persistence"] = dict(assistant_message.get("_persistence") or {})
    return updated


def _update_ui_message_persistence(
    message_id: str,
    spec: dict[str, Any],
    *,
    persisted: bool,
    error: str = "",
) -> bool:
    for index, item in enumerate(st.session_state.agent_messages):
        if not isinstance(item, dict) or str(item.get("message_id") or "") != message_id:
            continue
        updated = dict(item)
        _set_assistant_persistence_state(
            updated,
            spec,
            persisted=persisted,
            error=error,
        )
        if updated == item:
            return False
        st.session_state.agent_messages[index] = updated
        return True
    return False


def _queue_pending_agent_persistence(
    job_id: str,
    outcome: dict[str, Any],
) -> None:
    assistant_message = dict(outcome.get("assistant_message") or {})
    spec = dict(
        assistant_message.get("_persistence")
        or outcome.get("message_persistence")
        or {}
    )
    scope = tuple(outcome.get("scope") or ())
    if (
        len(scope) != 3
        or spec.get("persisted") is True
        or spec.get("blocked") is True
        or _persistence_spec_scope(spec) != scope
    ):
        return
    st.session_state.pending_agent_persistence = {
        "job_id": str(job_id),
        "scope": scope,
        "message_id": str(assistant_message.get("message_id") or ""),
        "spec": spec,
        "attempts": 0,
        "next_retry_at": time.monotonic() + AGENT_PERSISTENCE_RETRY_DELAYS[0],
    }


def _retry_pending_agent_persistence() -> bool:
    with _PENDING_AGENT_PERSISTENCE_LOCK:
        pending = dict(st.session_state.get("pending_agent_persistence") or {})
        if not pending:
            return False
        scope = tuple(pending.get("scope") or ())
        spec = dict(pending.get("spec") or {})
        message_id = str(pending.get("message_id") or "")
        if (
            len(scope) != 3
            or scope != _current_agent_scope()
            or _persistence_spec_scope(spec) != scope
            or str(spec.get("message_id") or "") != message_id
        ):
            st.session_state.pending_agent_persistence = {}
            return True
        now = time.monotonic()
        if now < float(pending.get("next_retry_at") or 0.0):
            return False
        if (
            pending.get("retry_token")
            and now < float(pending.get("retry_lease_until") or 0.0)
        ):
            return False
        retry_token = f"retry_{uuid4().hex}"
        pending["retry_token"] = retry_token
        pending["retry_lease_until"] = now + AGENT_PERSISTENCE_RETRY_LEASE_SECONDS
        st.session_state.pending_agent_persistence = pending

    attempts = int(pending.get("attempts") or 0) + 1
    try:
        _persist_assistant_spec(get_memory_manager(), spec)
    except Exception as error:
        with _PENDING_AGENT_PERSISTENCE_LOCK:
            current = dict(st.session_state.get("pending_agent_persistence") or {})
            if current.get("retry_token") != retry_token:
                return False
            changed = _update_ui_message_persistence(
                message_id,
                spec,
                persisted=False,
                error=str(error),
            )
            if attempts >= AGENT_PERSISTENCE_MAX_RETRIES:
                st.session_state.pending_agent_persistence = {}
                return True
            current["attempts"] = attempts
            current["next_retry_at"] = time.monotonic() + AGENT_PERSISTENCE_RETRY_DELAYS[
                min(attempts, len(AGENT_PERSISTENCE_RETRY_DELAYS) - 1)
            ]
            current["retry_token"] = ""
            current["retry_lease_until"] = 0.0
            current["spec"] = dict(
                next(
                    (
                        item.get("_persistence")
                        for item in st.session_state.agent_messages
                        if isinstance(item, dict)
                        and str(item.get("message_id") or "") == message_id
                    ),
                    spec,
                )
                or spec
            )
            st.session_state.pending_agent_persistence = current
            return changed

    with _PENDING_AGENT_PERSISTENCE_LOCK:
        current = dict(st.session_state.get("pending_agent_persistence") or {})
        if current.get("retry_token") != retry_token:
            return False
        _update_ui_message_persistence(
            message_id,
            spec,
            persisted=True,
        )
        st.session_state.pending_agent_persistence = {}
        return True


def _prepare_agent_outcome_persistence(outcome: dict[str, Any]) -> dict[str, Any]:
    updated = dict(outcome)
    assistant_message = dict(updated.get("assistant_message") or {})
    existing = dict(
        assistant_message.get("_persistence")
        or updated.get("message_persistence")
        or {}
    )
    if existing:
        return updated
    scope = tuple(updated.get("scope") or ())
    if len(scope) != 3:
        return updated
    spec = _build_assistant_persistence_spec(
        user_id=str(scope[0]),
        project_id=str(scope[1]),
        session_id=str(scope[2]),
        assistant_message=assistant_message,
        assistant_text=str(updated.get("assistant_text") or assistant_message.get("content") or ""),
        mode=str(updated.get("mode") or "chat"),
        payload=dict(assistant_message.get("payload") or {}),
        vision_payload={"vision_result": assistant_message.get("vision_result") or {}},
    )
    _set_assistant_persistence_state(
        assistant_message,
        spec,
        persisted=False,
        error="等待写入对话历史。",
    )
    updated["assistant_message"] = assistant_message
    updated["message_persistence"] = dict(assistant_message["_persistence"])
    return updated


def sync_active_agent_job() -> bool:
    pending_updated = _retry_pending_agent_persistence()
    snapshot = _active_agent_job_snapshot()
    if snapshot is None or not snapshot.done:
        return pending_updated
    runner = get_agent_task_runner()
    try:
        claim = runner.claim_result(snapshot.job_id)
    except Exception:
        return pending_updated
    if claim is None:
        return pending_updated
    if claim.error:
        error_text = claim.error
        outcome = {
            "scope": snapshot.scope,
            "assistant_message": {
                "role": "assistant",
                "content": f"后台 Agent 任务未能完成：{error_text}",
                "message_id": f"msg_error_{snapshot.job_id}",
            },
            "assistant_text": f"后台 Agent 任务未能完成：{error_text}",
            "mode": "background_error",
            "state_updates": {},
        }
    else:
        outcome = claim.result
    if not isinstance(outcome, dict):
        outcome = {
            "scope": snapshot.scope,
            "assistant_message": {
                "role": "assistant",
                "content": "后台 Agent 任务返回了无法读取的结果。",
                "message_id": f"msg_error_{snapshot.job_id}",
            },
            "assistant_text": "后台 Agent 任务返回了无法读取的结果。",
            "mode": "background_error",
            "state_updates": {},
        }
    current_scope = _current_agent_scope()
    outcome_scope = tuple(outcome.get("scope") or ())
    if outcome_scope != snapshot.scope or outcome_scope != current_scope:
        runner.acknowledge_result(snapshot.job_id, claim.token)
        if str(st.session_state.get("active_agent_job_id") or "") == snapshot.job_id:
            st.session_state.active_agent_job_id = ""
            st.session_state.active_agent_progress_revealed = False
            st.session_state.active_agent_retrieval_mode = ""
        return pending_updated
    prepared_outcome = _prepare_agent_outcome_persistence(outcome)
    applied = _append_agent_job_outcome(prepared_outcome)
    prepared_state = dict(prepared_outcome.get("message_persistence") or {})
    if prepared_state.get("persisted") is False and not prepared_state.get("blocked"):
        _queue_pending_agent_persistence(snapshot.job_id, prepared_outcome)
    if not runner.acknowledge_result(snapshot.job_id, claim.token):
        return pending_updated or applied
    if str(st.session_state.get("active_agent_job_id") or "") == snapshot.job_id:
        st.session_state.active_agent_job_id = ""
        st.session_state.active_agent_progress_revealed = False
        st.session_state.active_agent_retrieval_mode = ""

    persisted_outcome = _retry_agent_outcome_persistence(
        prepared_outcome,
        expected_scope=snapshot.scope,
    )
    persistence_updated = _append_agent_job_outcome(persisted_outcome)
    persistence_state = dict(persisted_outcome.get("message_persistence") or {})
    if persistence_state.get("persisted") is False and not persistence_state.get("blocked"):
        _queue_pending_agent_persistence(snapshot.job_id, persisted_outcome)
    elif str(
        (st.session_state.get("pending_agent_persistence") or {}).get("job_id") or ""
    ) == snapshot.job_id:
        st.session_state.pending_agent_persistence = {}
    return pending_updated or applied or persistence_updated


@st.fragment(run_every=0.8)
def render_agent_job_monitor(active_view: str) -> None:
    if sync_active_agent_job():
        st.rerun()
    snapshot = _active_agent_job_snapshot()
    if snapshot is None:
        return
    if active_view == "chat":
        st.session_state.active_agent_progress_revealed = True
    with st.container(key="background_agent_progress_host"):
        render_agent_progress(
            st.empty(),
            snapshot.progress,
            retrieval_mode=str(
                st.session_state.get("active_agent_retrieval_mode") or "quick"
            ),
        )


def handle_prompt(
    prompt: str,
    api_key: str,
    manual_observation: str,
    has_image: bool,
    image_bytes: bytes | None,
    image_mime_type: str,
    retrieval_mode: str = "quick",
    progress_slot: Any | None = None,
) -> None:
    if (
        _active_agent_job_snapshot() is not None
        or st.session_state.get("pending_agent_persistence")
    ):
        return
    submitted_retrieval_mode = normalize_retrieval_mode(retrieval_mode)
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
    user_metadata: dict[str, Any] = {
        "has_image": bool(has_image and image_bytes),
        "retrieval_mode": submitted_retrieval_mode,
    }
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
        assistant_message = {
            "role": "assistant",
            "content": f"问题未能保存，Agent 任务没有启动：{error}",
            "message_id": f"msg_{uuid4().hex}",
        }
        st.session_state.agent_messages.append(assistant_message)
        st.session_state.clear_sidebar_inputs = True
        st.session_state.restore_main_scroll_position = True
        st.rerun()
        return

    live_orchestrator = orchestrator
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

    job_id = f"job_{uuid4().hex}"
    scope: agent_background.TaskScope = (user_id, project_id, session_id)
    request = MappingProxyType({
        "job_id": job_id,
        "user_id": user_id,
        "project_id": project_id,
        "session_id": session_id,
        "prompt": prompt,
        "resolved_prompt": resolved_prompt,
        "api_key": api_key,
        "history": history,
        "batch_for_turn": batch_for_turn,
        "effective_observation": effective_observation,
        "has_image": has_image,
        "image_bytes": image_bytes,
        "image_mime_type": image_mime_type,
        "memory_context": memory_context,
        "missing_inputs": missing_inputs,
        "stored_image_path": stored_image_path,
        "memory_errors": memory_errors,
        "vision_memory": vision_memory,
        "previous_result": st.session_state.last_result or {},
        "is_previous_evidence_request": is_previous_evidence_request,
        "should_run_full_analysis": should_run_full_analysis,
        "retrieval_mode": submitted_retrieval_mode,
    })
    try:
        get_agent_task_runner().submit(
            job_id,
            scope,
            lambda callback: _execute_agent_job(request, callback),
        )
    except Exception as error:
        assistant_message = {
            "role": "assistant",
            "content": f"Agent 任务未能启动：{error}",
            "message_id": f"msg_{uuid4().hex}",
        }
        st.session_state.agent_messages.append(assistant_message)
        try:
            manager.record_message(
                user_id,
                session_id,
                project_id,
                "assistant",
                assistant_message["content"],
                message_id=assistant_message["message_id"],
            )
        except agent_memory.MemoryManagerError:
            pass
    else:
        st.session_state.active_agent_job_id = job_id
        st.session_state.active_agent_progress_revealed = progress_slot is not None
        st.session_state.active_agent_retrieval_mode = submitted_retrieval_mode
        if progress_slot is not None:
            render_agent_progress(
                progress_slot,
                "正在启动 Agent 任务",
                retrieval_mode=submitted_retrieval_mode,
            )

    st.session_state.clear_sidebar_inputs = True
    st.session_state.restore_main_scroll_position = True
    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Citrus AI · 柑橘产业链决策",
        page_icon=":material/nutrition:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    refresh_ui_modules()
    inject_style()
    init_state()
    sync_active_agent_job()
    active_view = current_product_view()
    render_navigation_history_sync()
    restore_scroll_position = bool(st.session_state.pop("restore_main_scroll_position", False))
    reset_scroll_position = bool(st.session_state.pop("reset_main_scroll_position", False))
    scroll_command_id = int(st.session_state.get("scroll_manager_command_id", 0))
    if restore_scroll_position or reset_scroll_position:
        scroll_command_id += 1
        st.session_state.scroll_manager_command_id = scroll_command_id
    context_token = (
        _query_value("ctx")
        or str(st.session_state.get("memory_context_token") or "")
    )
    with st.container(key="product_shell_overlays"):
        ui_components.render_primary_navigation(
            active_view,
            context_token,
            on_view_change=select_product_view,
        )
        ui_components.render_top_actions(
            active_view,
            context_token,
            on_view_change=select_product_view,
        )
        ui_components.render_mobile_panel_toggle(
            bool(st.session_state.mobile_secondary_open),
            toggle_mobile_secondary_panel,
        )

    api_key = get_deepseek_api_key()
    (
        manual_observation,
        has_image,
        image_bytes,
        image_mime_type,
        retrieval_mode,
    ) = render_sidebar(active_view)

    if active_view == "chat":
        if not st.session_state.agent_messages:
            selected_prompt, progress_slot = render_empty_state(api_key)
        else:
            selected_prompt = None
            progress_slot = None
            st.markdown('<div class="chat-transcript-start"></div>', unsafe_allow_html=True)
            for message in st.session_state.agent_messages:
                render_message(message)

    active_job = _active_agent_job_snapshot()
    if active_job is not None or st.session_state.get("pending_agent_persistence"):
        render_agent_job_monitor(active_view)

    if active_view != "chat":
        with st.container(key="product_page_shell"):
            ui_product_pages.render_product_page(active_view)
        render_scroll_position_manager(
            restore=restore_scroll_position,
            reset_to_top=reset_scroll_position,
            command_id=scroll_command_id,
        )
        return

    clearance_state = "is-transcript" if st.session_state.agent_messages else "is-empty"
    st.markdown(
        f'<div class="mobile-composer-clearance {clearance_state}" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )

    typed_prompt = st.chat_input(
        "输入问题或粘贴批次信息…\nAsk or paste batch data…",
        disabled=(
            active_job is not None
            or bool(st.session_state.get("pending_agent_persistence"))
        ),
    )
    render_scroll_position_manager(
        restore=restore_scroll_position,
        reset_to_top=reset_scroll_position,
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
            retrieval_mode=retrieval_mode,
            progress_slot=progress_slot,
        )


if __name__ == "__main__":
    main()
