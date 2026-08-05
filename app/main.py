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
def get_memory_manager() -> agent_memory.MemoryManager:
    return agent_memory.MemoryManager()


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
        "description": "比较整果、果汁与果皮路线",
        "prompt": EXAMPLE_PROMPTS[0],
    },
    {
        "eyebrow": "02 · 果汁生产",
        "title": "规划脐橙果汁生产",
        "description": "梳理加工与质控流程",
        "prompt": EXAMPLE_PROMPTS[1],
    },
    {
        "eyebrow": "03 · 果皮增值",
        "title": "提升果皮利用价值",
        "description": "比较陈皮、精油与果胶路线",
        "prompt": EXAMPLE_PROMPTS[2],
    },
    {
        "eyebrow": "04 · 风险复核",
        "title": "复核批次生产风险",
        "description": "明确补检与人工放行条件",
        "prompt": EXAMPLE_PROMPTS[3],
    },
]


def item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


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
    st.markdown(
        """
        <style>
        :root {
            color-scheme: dark;
            --agent-bg: #111111;
            --agent-bg-elevated: #181818;
            --agent-bg-soft: #202020;
            --agent-bg-softer: #272727;
            --agent-line: #303030;
            --agent-line-strong: #3f3f3f;
            --agent-text: #f4f4f5;
            --agent-text-soft: #d4d4d8;
            --agent-muted: #9ca3af;
            --agent-faint: #6b7280;
            --agent-accent: #f97316;
            --agent-accent-soft: rgba(249, 115, 22, 0.16);
            --agent-shadow: 0 22px 70px rgba(0, 0, 0, 0.28);
            --agent-font-family: "Times New Roman", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", serif;
            --agent-mono-font-family: "Times New Roman", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", serif;
            --agent-chinese-font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
        }
        html {
            background: var(--agent-bg);
        }
        html, body, .stApp, [data-testid="stSidebar"], [data-testid="stChatMessage"],
        .stMarkdown, .stText, .stCaption, .stButton, .stTextInput, .stTextArea, .stFileUploader,
        button, input, textarea, select, label, p, h1, h2, h3, h4, h5, h6 {
            font-family: var(--agent-font-family) !important;
            letter-spacing: 0;
        }
        body {
            color: var(--agent-text);
            background: var(--agent-bg);
        }
        code, pre, kbd, samp {
            font-family: var(--agent-mono-font-family) !important;
        }
        #MainMenu, footer {
            visibility: hidden;
            height: 0;
        }
        header[data-testid="stHeader"] {
            background: transparent !important;
            color: var(--agent-text) !important;
            box-shadow: none !important;
        }
        header[data-testid="stHeader"] button {
            color: var(--agent-text-soft) !important;
            background: rgba(255, 255, 255, 0.055) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 8px !important;
        }
        .stApp {
            background:
                radial-gradient(circle at 78% 0%, rgba(249, 115, 22, 0.08), transparent 28rem),
                linear-gradient(180deg, #141414 0%, #101010 38%, #0d0d0d 100%);
            color: var(--agent-text);
        }
        .block-container {
            max-width: 1120px;
            padding: 3.15rem 2.4rem 8rem;
        }
        [data-testid="stSidebar"] {
            background: #1a1a1a;
            border-right: 1px solid var(--agent-line);
            box-shadow: 18px 0 44px rgba(0, 0, 0, 0.18);
        }
        [data-testid="stSidebar"] > div {
            padding: 2rem 1.15rem 1.2rem;
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stCaption {
            color: var(--agent-muted) !important;
        }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--agent-text) !important;
        }
        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.78rem;
            padding: 0.15rem 0 0.9rem;
        }
        .brand-mark {
            width: 2.55rem;
            height: 2.55rem;
            border-radius: 0.8rem;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #f97316, #facc15);
            color: #101010;
            font-weight: 800;
            font-size: 1rem;
            box-shadow: 0 12px 26px rgba(249, 115, 22, 0.28);
        }
        .brand-title {
            color: var(--agent-text);
            font-size: 1.16rem;
            font-weight: 720;
            line-height: 1.1;
        }
        .brand-subtitle {
            color: var(--agent-muted);
            font-size: 0.8rem;
            margin-top: 0.22rem;
        }
        .sidebar-section-title {
            color: #e5e7eb;
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
            margin: 1.25rem 0 0.62rem;
        }
        .status-list {
            border: 1px solid var(--agent-line);
            background: rgba(255, 255, 255, 0.035);
            border-radius: 8px;
            overflow: hidden;
        }
        .status-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
            padding: 0.72rem 0.78rem;
            color: var(--agent-text-soft);
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            font-size: 0.86rem;
        }
        .status-row:last-child {
            border-bottom: 0;
        }
        .status-pill {
            color: #f8fafc;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 999px;
            padding: 0.1rem 0.45rem;
            font-size: 0.72rem;
            white-space: nowrap;
        }
        .sidebar-note {
            color: var(--agent-muted);
            font-size: 0.82rem;
            line-height: 1.62;
            padding: 0.78rem 0.82rem;
            border: 1px solid var(--agent-line);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.03);
        }
        .agent-live-progress {
            display: flex;
            align-items: center;
            gap: 0.88rem;
            width: min(760px, 100%);
            margin: 0.35rem 0 1.2rem;
            padding: 0.92rem 1rem;
            color: var(--agent-text);
            background: rgba(17, 17, 17, 0.78);
            border: 1px solid rgba(249, 115, 22, 0.24);
            border-radius: 8px;
            box-shadow: 0 18px 46px rgba(0, 0, 0, 0.24);
        }
        .agent-live-spinner {
            width: 1.35rem;
            height: 1.35rem;
            min-width: 1.35rem;
            border-radius: 999px;
            border: 2px solid rgba(249, 115, 22, 0.18);
            border-top-color: #f97316;
            border-right-color: #facc15;
            animation: agent-spin 780ms linear infinite;
        }
        .agent-live-copy {
            min-width: 0;
        }
        .agent-live-title {
            color: var(--agent-text);
            font-size: 0.96rem;
            line-height: 1.35;
            font-weight: 650;
            overflow-wrap: anywhere;
        }
        .agent-live-subtitle {
            display: flex;
            align-items: center;
            gap: 0.42rem;
            color: var(--agent-muted);
            font-size: 0.78rem;
            line-height: 1.35;
            margin-top: 0.22rem;
        }
        .agent-live-dot {
            width: 0.28rem;
            height: 0.28rem;
            border-radius: 999px;
            background: #facc15;
            animation: agent-pulse 980ms ease-in-out infinite;
        }
        .agent-live-dot:nth-child(2) {
            animation-delay: 130ms;
        }
        .agent-live-dot:nth-child(3) {
            animation-delay: 260ms;
        }
        @keyframes agent-spin {
            to {
                transform: rotate(360deg);
            }
        }
        @keyframes agent-pulse {
            0%, 100% {
                opacity: 0.28;
                transform: translateY(0);
            }
            45% {
                opacity: 1;
                transform: translateY(-0.16rem);
            }
        }
        hr {
            border-color: var(--agent-line) !important;
        }
        .hero {
            padding: 5.1rem 0 1.2rem;
            max-width: 850px;
        }
        .hero h1 {
            color: var(--agent-text);
            font-size: clamp(2rem, 4.4vw, 4.2rem);
            line-height: 1.06;
            letter-spacing: 0;
            margin: 0 0 0.82rem;
            font-weight: 760;
        }
        .hero p {
            color: var(--agent-muted);
            font-size: 1.06rem;
            line-height: 1.7;
            margin: 0;
            max-width: 690px;
        }
        .hero-kicker {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            color: #fed7aa;
            background: var(--agent-accent-soft);
            border: 1px solid rgba(249, 115, 22, 0.24);
            border-radius: 999px;
            padding: 0.32rem 0.68rem;
            font-size: 0.8rem;
            font-weight: 650;
            margin-bottom: 1rem;
        }
        .prompt-grid-label {
            color: var(--agent-muted);
            font-size: 0.88rem;
            margin: 2.1rem 0 0.65rem;
        }
        div[data-testid="stButton"] > button {
            border-radius: 8px;
            min-height: 2.7rem;
            background: rgba(255, 255, 255, 0.055);
            border: 1px solid var(--agent-line);
            color: var(--agent-text-soft);
            white-space: normal;
            text-align: left;
            line-height: 1.52;
            transition: background 160ms ease, border-color 160ms ease, transform 160ms ease;
        }
        div[data-testid="stButton"] > button:hover {
            background: rgba(255, 255, 255, 0.085);
            border-color: var(--agent-line-strong);
            color: #ffffff;
            transform: translateY(-1px);
        }
        div[data-testid="stButton"] > button:focus:not(:active) {
            border-color: rgba(249, 115, 22, 0.55);
            box-shadow: 0 0 0 1px rgba(249, 115, 22, 0.25);
        }
        .metric-card {
            background: linear-gradient(180deg, rgba(255,255,255,0.07), rgba(255,255,255,0.035));
            border: 1px solid var(--agent-line);
            border-radius: 8px;
            padding: 1rem 1.05rem;
            min-height: 7.25rem;
            overflow: hidden;
            box-shadow: var(--agent-shadow);
        }
        .metric-label {
            color: var(--agent-muted);
            font-size: 0.8rem;
            font-weight: 640;
            line-height: 1.45;
            margin-bottom: 0.35rem;
        }
        .metric-value {
            color: var(--agent-text);
            font-size: clamp(1.35rem, 2.25vw, 2.1rem);
            line-height: 1.18;
            font-weight: 680;
            word-break: break-word;
            overflow-wrap: anywhere;
            white-space: normal;
        }
        .chat-transcript-start {
            height: 0.45rem;
        }
        .message-row {
            display: flex;
            gap: 0.75rem;
            align-items: flex-start;
            margin: 0 0 1.35rem;
            padding-top: 0.2rem;
            overflow: visible;
        }
        .message-avatar {
            width: 2.05rem;
            height: 2.05rem;
            min-width: 2.05rem;
            border-radius: 0.6rem;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #111111;
            font-weight: 780;
            line-height: 1;
            margin-top: 0.1rem;
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22);
        }
        .message-avatar.user {
            background: #f4f4f5;
        }
        .message-avatar.assistant {
            background: linear-gradient(135deg, #f97316, #facc15);
        }
        .message-bubble {
            background: var(--agent-bg-soft);
            border: 1px solid var(--agent-line);
            border-radius: 8px;
            padding: 0.75rem 0.95rem;
            line-height: 1.7;
            min-height: 2.35rem;
            overflow: visible;
            flex: 1;
            word-break: break-word;
            overflow-wrap: anywhere;
            color: var(--agent-text-soft);
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.18);
        }
        .message-row.user .message-bubble {
            background: #242424;
            border-color: #363636;
            color: #f8fafc;
        }
        .message-bubble p {
            margin: 0 0 0.35rem 0;
            line-height: 1.7;
        }
        .analysis-shell {
            margin: -0.25rem 0 1.4rem 2.8rem;
            padding: 1rem 0 0;
        }
        .stMarkdown, [data-testid="stMarkdownContainer"] {
            color: var(--agent-text-soft);
        }
        [data-testid="stMarkdownContainer"] strong {
            color: #ffffff;
        }
        [data-testid="stMarkdownContainer"] h1,
        [data-testid="stMarkdownContainer"] h2,
        [data-testid="stMarkdownContainer"] h3 {
            color: var(--agent-text) !important;
            font-weight: 720 !important;
        }
        [data-testid="stMarkdownContainer"] li {
            margin-bottom: 0.25rem;
        }
        div[data-testid="stAlert"] {
            border-radius: 8px;
            border: 1px solid var(--agent-line);
            background: rgba(255, 255, 255, 0.055);
            color: var(--agent-text-soft);
        }
        div[data-testid="stExpander"] {
            border: 1px solid var(--agent-line) !important;
            border-radius: 8px !important;
            background: rgba(255, 255, 255, 0.035) !important;
            overflow: hidden;
        }
        div[data-testid="stExpander"] summary {
            color: var(--agent-text) !important;
            font-weight: 650;
        }
        div[data-testid="stDataFrame"] {
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--agent-line);
        }
        .score-bars {
            display: grid;
            gap: 0.82rem;
            margin: 0.15rem 0 1.05rem;
        }
        .score-row {
            padding: 0.88rem 0.95rem 0.95rem;
            border: 1px solid rgba(217, 189, 130, 0.14);
            border-radius: 6px;
            background: rgba(17, 21, 29, 0.62);
        }
        .score-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.62rem;
        }
        .score-name {
            color: var(--agent-text);
            font-size: 0.94rem;
            line-height: 1.45;
            min-width: 0;
            overflow-wrap: anywhere;
        }
        .score-value {
            color: #f1dfad;
            font-family: var(--agent-mono-font-family);
            font-size: 0.9rem;
            text-align: right;
            white-space: nowrap;
        }
        .score-track {
            height: 0.42rem;
            background: rgba(217, 189, 130, 0.09);
            border-radius: 999px;
            overflow: hidden;
        }
        .score-fill {
            height: 100%;
            background: linear-gradient(90deg, #f97316, #facc15);
            border-radius: 999px;
        }
        .score-detail {
            color: var(--agent-muted);
            font-size: 0.84rem;
            line-height: 1.62;
            margin-top: 0.62rem;
            overflow-wrap: anywhere;
        }
        .score-detail + .score-detail {
            margin-top: 0.32rem;
        }
        .score-detail strong {
            color: var(--agent-text-soft);
            font-weight: 620;
        }
        .risk-list {
            display: grid;
            gap: 0.62rem;
            margin-top: 1rem;
        }
        .risk-item {
            padding: 0.78rem 0.9rem;
            border: 1px solid rgba(217, 189, 130, 0.15);
            border-left: 3px solid rgba(217, 189, 130, 0.42);
            border-radius: 6px;
            background: rgba(17, 21, 29, 0.62);
            color: var(--agent-text-soft);
            font-size: 0.86rem;
            line-height: 1.62;
            overflow-wrap: anywhere;
        }
        .risk-item.high {
            border-color: rgba(176, 86, 74, 0.28);
            border-left-color: rgba(201, 99, 82, 0.72);
            background: rgba(63, 25, 24, 0.26);
        }
        .risk-level {
            color: #f1dfad;
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.78rem;
            margin-right: 0.45rem;
        }
        .risk-empty {
            margin-top: 1rem;
            padding: 0.78rem 0.9rem;
            border: 1px solid rgba(217, 189, 130, 0.14);
            border-radius: 6px;
            background: rgba(17, 21, 29, 0.58);
            color: var(--agent-muted);
            font-size: 0.86rem;
        }
        .tool-steps {
            display: grid;
            gap: 0.72rem;
            margin: 0.2rem 0 0.25rem;
        }
        .tool-step {
            display: grid;
            grid-template-columns: 2.4rem minmax(0, 1fr);
            gap: 0.82rem;
            padding: 0.88rem 0.95rem;
            border: 1px solid rgba(217, 189, 130, 0.14);
            border-radius: 6px;
            background: rgba(17, 21, 29, 0.62);
        }
        .tool-step-index {
            width: 2.1rem;
            height: 2.1rem;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid rgba(217, 189, 130, 0.18);
            border-radius: 999px;
            color: #f1dfad;
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.82rem;
            background: rgba(217, 189, 130, 0.06);
        }
        .tool-step-title {
            color: var(--agent-text);
            font-size: 0.94rem;
            line-height: 1.5;
            overflow-wrap: anywhere;
        }
        .tool-step-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.42rem;
            margin: 0.36rem 0 0.48rem;
        }
        .tool-chip {
            display: inline-flex;
            align-items: center;
            min-height: 1.35rem;
            padding: 0.08rem 0.48rem;
            border: 1px solid rgba(217, 189, 130, 0.14);
            border-radius: 999px;
            color: var(--agent-muted);
            background: rgba(8, 10, 14, 0.6);
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.74rem;
        }
        .tool-step-note {
            color: var(--agent-text-soft);
            font-size: 0.86rem;
            line-height: 1.62;
            overflow-wrap: anywhere;
        }
        .report-anchor {
            display: none;
        }
        [data-testid="stFileUploader"] section {
            background: rgba(255, 255, 255, 0.045);
            border: 1px dashed var(--agent-line-strong);
            border-radius: 8px;
            min-height: 5.1rem;
            padding: 0.78rem 0.82rem;
        }
        [data-testid="stFileUploader"] button {
            background: rgba(255, 255, 255, 0.08) !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            color: var(--agent-text-soft) !important;
            border-radius: 8px;
            min-height: 2.3rem;
            padding: 0.55rem 0.78rem;
        }
        [data-testid="stFileUploader"] small {
            display: none !important;
        }
        [data-testid="stTextArea"] div[data-baseweb="textarea"],
        [data-testid="stTextArea"] div[data-baseweb="base-input"],
        [data-testid="stTextAreaRootElement"] {
            background: rgba(255, 255, 255, 0.055) !important;
            border-color: var(--agent-line) !important;
        }
        textarea, input {
            background: rgba(255, 255, 255, 0.055) !important;
            color: var(--agent-text) !important;
            border: 1px solid var(--agent-line) !important;
            border-radius: 8px !important;
        }
        textarea::placeholder, input::placeholder {
            color: var(--agent-faint) !important;
        }
        .stDownloadButton button {
            justify-content: center;
            text-align: center !important;
            background: rgba(17, 21, 29, 0.82) !important;
            border: 1px solid rgba(217, 189, 130, 0.18) !important;
            border-radius: 6px !important;
            color: var(--agent-text) !important;
        }
        .stDownloadButton button:hover {
            border-color: rgba(217, 189, 130, 0.34) !important;
            background: rgba(217, 189, 130, 0.08) !important;
            color: #f1dfad !important;
        }
        [data-testid="stBottom"] {
            z-index: 999;
            background: #111111 !important;
            backdrop-filter: blur(18px);
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }
        [data-testid="stBottomBlockContainer"] {
            background: #111111 !important;
            padding: 0.9rem 2.4rem 1.05rem !important;
        }
        [data-testid="stBottom"] [data-testid="stVerticalBlock"] {
            width: min(1120px, 100%) !important;
            max-width: 1120px !important;
            margin: 0 auto !important;
            padding: 0 !important;
        }
        [data-testid="stChatInput"] {
            width: 100%;
            background: transparent !important;
            border: 0 !important;
            padding: 0 !important;
            box-shadow: none !important;
        }
        [data-testid="stChatInput"] > div {
            width: 100%;
            background: transparent !important;
            border: 0 !important;
            padding: 0 !important;
        }
        [data-testid="stChatInput"] div[data-baseweb="textarea"],
        [data-testid="stChatInput"] div[data-baseweb="base-input"] {
            width: 100%;
            background: transparent !important;
            border: 0 !important;
        }
        [data-testid="stChatInput"] div {
            color: var(--agent-text) !important;
        }
        [data-testid="stChatInput"] textarea,
        [data-testid="stChatInput"] input {
            background: #222222 !important;
            border: 1px solid #3a3a3a !important;
            box-shadow: 0 18px 58px rgba(0, 0, 0, 0.32);
            min-height: 3.4rem !important;
            padding: 0.95rem 4.1rem 0.95rem 1rem !important;
        }
        [data-testid="stChatInput"] textarea:focus,
        [data-testid="stChatInput"] input:focus {
            border-color: rgba(249, 115, 22, 0.7) !important;
            box-shadow: 0 0 0 1px rgba(249, 115, 22, 0.22), 0 18px 58px rgba(0, 0, 0, 0.32);
            outline: none !important;
        }
        [data-testid="stChatInput"] button {
            background: #f4f4f5 !important;
            color: #111111 !important;
            border-radius: 999px !important;
        }
        [data-testid="stChatMessage"] {
            overflow: visible !important;
            align-items: flex-start !important;
            padding-top: 0.35rem !important;
            padding-bottom: 0.35rem !important;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
            overflow: visible !important;
            line-height: 1.65 !important;
            padding-top: 0.12rem !important;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
            line-height: 1.65 !important;
            margin-top: 0 !important;
            margin-bottom: 0.35rem !important;
            overflow: visible !important;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h1,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h2,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h3 {
            line-height: 1.35 !important;
            margin-top: 0.2rem !important;
        }
        @media (max-width: 860px) {
            .block-container {
                padding: 2rem 1rem 8rem;
            }
            .hero {
                padding-top: 1.6rem;
            }
            .message-row {
                gap: 0.55rem;
            }
            .message-avatar {
                width: 1.8rem;
                height: 1.8rem;
                min-width: 1.8rem;
            }
            .analysis-shell {
                margin-left: 0;
            }
            [data-testid="stBottom"] [data-testid="stVerticalBlock"] {
                padding-left: 1rem;
                padding-right: 1rem;
            }
        }

        /* Warm lab-console theme inspired by the reference screens. */
        :root {
            --agent-bg: #08090c;
            --agent-bg-elevated: #0d1016;
            --agent-bg-soft: #11151d;
            --agent-bg-softer: #171a22;
            --agent-line: #262b33;
            --agent-line-strong: #3a3f48;
            --agent-text: #efe7d3;
            --agent-text-soft: #ded3bb;
            --agent-muted: #89877d;
            --agent-faint: #5f625f;
            --agent-accent: #d9bd82;
            --agent-accent-soft: rgba(217, 189, 130, 0.12);
            --agent-shadow: 0 24px 72px rgba(0, 0, 0, 0.44);
            --agent-font-family: "Times New Roman", "Noto Serif SC", "Source Han Serif SC", "Songti SC", SimSun, Georgia, serif;
            --agent-mono-font-family: "Times New Roman", "Noto Serif SC", "Source Han Serif SC", "Songti SC", SimSun, Georgia, serif;
        }
        html, body, .stApp {
            background: #08090c !important;
        }
        body, .stMarkdown, [data-testid="stMarkdownContainer"], p, h1, h2, h3, h4, h5, h6, label {
            color: var(--agent-text);
            font-family: var(--agent-font-family) !important;
        }
        .stApp {
            background:
                radial-gradient(circle at 74% 3%, rgba(217, 189, 130, 0.055), transparent 25rem),
                radial-gradient(circle at 18% 92%, rgba(48, 63, 59, 0.18), transparent 34rem),
                linear-gradient(180deg, #0a0b0f 0%, #08090c 48%, #07080a 100%) !important;
        }
        .block-container {
            max-width: 1180px;
            padding: 2.9rem 3.2rem 8.4rem;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #10141b 0%, #0d1118 100%) !important;
            border-right: 1px solid #232832;
            box-shadow: 18px 0 48px rgba(0, 0, 0, 0.34);
        }
        [data-testid="stSidebar"] > div {
            padding: 2.35rem 1.35rem 1.4rem;
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label {
            font-size: 0.88rem !important;
            line-height: 1.55 !important;
        }
        [data-testid="stSidebar"] .stCaption,
        [data-testid="stSidebar"] small {
            font-size: 0.76rem !important;
            line-height: 1.45 !important;
        }
        .sidebar-brand {
            display: block;
            padding: 0 0 1.1rem;
        }
        .sidebar-brand::before,
        .sidebar-section-title::before,
        .hero-kicker::before {
            content: "";
            display: inline-block;
            width: 1.45rem;
            height: 1px;
            margin-right: 0.55rem;
            vertical-align: middle;
            background: rgba(217, 189, 130, 0.55);
        }
        .brand-mark {
            display: none;
        }
        .brand-title {
            margin-top: 0.65rem;
            color: var(--agent-text);
            font-size: 1.34rem;
            line-height: 1.15;
            font-weight: 560;
            font-style: normal;
            letter-spacing: 0;
        }
        .brand-subtitle {
            color: var(--agent-muted);
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.7rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
        }
        .sidebar-section-title {
            color: var(--agent-muted);
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.76rem;
            font-weight: 500;
            letter-spacing: 0.16em;
            margin: 1.7rem 0 0.82rem;
        }
        .status-list {
            border: 0;
            background: transparent;
            border-radius: 0;
        }
        .status-row {
            position: relative;
            display: block;
            padding: 0.78rem 0 0.9rem 1.1rem;
            border-bottom: 1px solid rgba(217, 189, 130, 0.12);
            color: var(--agent-text-soft);
            font-size: 1rem;
        }
        .status-row::before {
            content: "";
            position: absolute;
            left: 0.1rem;
            top: 1.05rem;
            width: 0.34rem;
            height: 0.34rem;
            border-radius: 999px;
            background: var(--agent-accent);
            box-shadow: 0 0 12px rgba(217, 189, 130, 0.58);
        }
        .status-pill {
            display: block;
            width: fit-content;
            margin-top: 0.34rem;
            color: var(--agent-faint);
            background: transparent;
            border: 0;
            border-radius: 0;
            padding: 0;
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.74rem;
            letter-spacing: 0;
        }
        .sidebar-note {
            border: 1px solid rgba(217, 189, 130, 0.18);
            background: rgba(17, 21, 29, 0.58);
            color: var(--agent-muted);
            font-size: 0.86rem;
            line-height: 1.75;
        }
        div[data-testid="stButton"] > button {
            min-height: 2.75rem;
            height: auto;
            padding: 0.82rem 1rem;
            background: rgba(17, 21, 29, 0.8);
            border: 1px solid rgba(217, 189, 130, 0.18);
            color: var(--agent-text-soft);
            border-radius: 6px;
            font-family: var(--agent-font-family) !important;
            white-space: pre-wrap;
            box-shadow: none;
        }
        [class*="st-key-example_card_"] div[data-testid="stButton"] > button {
            justify-content: flex-start !important;
            align-items: center !important;
            text-align: left !important;
            min-height: 4.45rem;
            padding: 0.62rem 0.9rem;
        }
        div[data-testid="stButton"] > button:hover {
            background: rgba(217, 189, 130, 0.085);
            border-color: rgba(217, 189, 130, 0.42);
            color: var(--agent-text);
        }
        div[data-testid="stButton"] > button p,
        div[data-testid="stButton"] > button span {
            color: var(--agent-text-soft) !important;
            white-space: pre-wrap !important;
            overflow: visible !important;
            text-overflow: unset !important;
            line-height: 1.45 !important;
            margin: 0 !important;
            text-align: left !important;
        }
        [class*="st-key-example_card_"] div[data-testid="stButton"] > button p,
        [class*="st-key-example_card_"] div[data-testid="stButton"] > button span {
            width: 100% !important;
        }
        div[data-testid="stButton"] > button:hover p,
        div[data-testid="stButton"] > button:hover span {
            color: var(--agent-text) !important;
        }
        div[data-testid="stButton"] > button:focus:not(:active) {
            border-color: rgba(217, 189, 130, 0.62);
            box-shadow: 0 0 0 1px rgba(217, 189, 130, 0.2);
        }
        .hero {
            max-width: 680px;
            margin: 0 auto;
            padding: 0 0 1.35rem;
            text-align: center;
        }
        .hero h1 {
            color: var(--agent-text);
            font-size: clamp(2.6rem, 5vw, 4.65rem);
            line-height: 1;
            font-weight: 420;
            letter-spacing: 0;
            margin: 0;
        }
        .hero p {
            color: var(--agent-muted);
            font-size: 1.18rem;
            line-height: 1.78;
            max-width: 730px;
        }
        .hero-kicker {
            display: block;
            width: fit-content;
            margin-bottom: 1.28rem;
            padding: 0;
            color: var(--agent-muted);
            background: transparent;
            border: 0;
            border-radius: 0;
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.68rem;
            letter-spacing: 0.18em;
            text-transform: uppercase;
        }
        .prompt-grid-label {
            max-width: 760px;
            margin: 0 auto 0.75rem;
            color: var(--agent-text-soft);
            font-family: var(--agent-font-family) !important;
            font-size: 0.92rem;
            line-height: 1.34;
            letter-spacing: 0;
            text-align: center;
        }
        section[data-testid="stAppScrollToBottomContainer"]:has([class*="st-key-empty_state_shell"]) {
            align-items: flex-start !important;
        }
        .block-container:has([class*="st-key-empty_state_shell"]) {
            box-sizing: border-box;
            height: calc(100vh - 8.4rem);
            height: calc(100dvh - 8.4rem);
            min-height: calc(100vh - 8.4rem);
            min-height: calc(100dvh - 8.4rem);
            padding-block: 2.9rem;
        }
        .block-container:has([class*="st-key-empty_state_shell"]) > div[data-testid="stVerticalBlock"] {
            height: 100%;
        }
        [data-testid="stLayoutWrapper"]:has(> [class*="st-key-empty_state_shell"]) {
            flex: 1 1 auto;
            min-height: 0;
        }
        [class*="st-key-empty_state_shell"] {
            display: flex;
            flex: 1 1 auto;
            height: 100%;
            min-height: 0;
            align-items: center;
            justify-content: center;
        }
        [class*="st-key-empty_state_shell"] > div[data-testid="stVerticalBlock"] {
            width: 100%;
            gap: 0.8rem;
        }
        [class*="st-key-empty_state_shell"] [class*="st-key-example_card_"] p,
        [class*="st-key-empty_state_shell"] [class*="st-key-example_card_"] span {
            font-size: 0.92rem !important;
            line-height: 1.34 !important;
        }
        .metric-card {
            background: rgba(17, 21, 29, 0.78);
            border: 1px solid rgba(217, 189, 130, 0.18);
            border-radius: 6px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            height: 8.9rem;
            min-height: 8.9rem;
            padding: 1.05rem 1.35rem;
            overflow: hidden;
            box-shadow: var(--agent-shadow);
        }
        .metric-label {
            color: var(--agent-muted);
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.78rem;
            line-height: 1.35;
            letter-spacing: 0.06em;
            margin-bottom: 0.72rem;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .metric-value {
            color: var(--agent-text);
            display: block;
            max-width: 100%;
            font-size: clamp(1.45rem, 1.7vw, 1.95rem);
            line-height: 1.16;
            font-weight: 440;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            word-break: normal;
            overflow-wrap: normal;
        }
        .recommendation-summary {
            width: min(44rem, 100%);
            margin: 0 0 1.85rem;
        }
        .recommendation-card {
            height: auto;
            min-height: 6.9rem;
            justify-content: flex-start;
            padding: 1.2rem 1.45rem 1.3rem;
            overflow: visible;
        }
        .recommendation-card .metric-value {
            font-size: clamp(1.55rem, 2vw, 2.25rem);
            line-height: 1.24;
            white-space: normal;
            overflow: visible;
            text-overflow: clip;
            word-break: break-word;
            overflow-wrap: anywhere;
        }
        .processing-plan {
            width: min(58rem, 100%);
            margin: 0 0 1.85rem;
            padding: 1.35rem 1.45rem 1.5rem;
            border: 1px solid rgba(249, 115, 22, 0.24);
            border-radius: 8px;
            background:
                linear-gradient(135deg, rgba(249, 115, 22, 0.08), transparent 35%),
                rgba(17, 21, 29, 0.82);
            box-shadow: var(--agent-shadow);
        }
        .processing-plan-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 1.15rem;
        }
        .processing-plan-kicker {
            color: var(--agent-accent);
            font-family: var(--agent-chinese-font-family) !important;
            font-size: 0.74rem;
            letter-spacing: 0.06em;
            margin-bottom: 0.32rem;
        }
        .processing-plan-title {
            color: var(--agent-text);
            font-size: clamp(1.22rem, 1.8vw, 1.65rem);
            line-height: 1.35;
            font-weight: 600;
        }
        .processing-plan-status {
            flex: 0 0 auto;
            max-width: 16rem;
            padding: 0.38rem 0.58rem;
            border: 1px solid rgba(249, 115, 22, 0.28);
            border-radius: 999px;
            color: #fdba74;
            background: rgba(249, 115, 22, 0.09);
            font-family: var(--agent-chinese-font-family) !important;
            font-size: 0.7rem;
            line-height: 1.35;
            text-align: center;
        }
        .processing-flow {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.42rem;
            margin-bottom: 1.15rem;
        }
        .processing-flow-step {
            padding: 0.42rem 0.58rem;
            border: 1px solid #353b45;
            border-radius: 5px;
            color: var(--agent-text-soft);
            background: #171b22;
            font-size: 0.8rem;
            line-height: 1.35;
        }
        .processing-flow-arrow {
            color: var(--agent-accent);
            font-size: 0.76rem;
        }
        .processing-stage-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.72rem;
        }
        .processing-stage {
            padding: 0.92rem 1rem;
            border: 1px solid #2c323c;
            border-radius: 6px;
            background: rgba(12, 15, 20, 0.72);
        }
        .processing-stage:last-child {
            grid-column: 1 / -1;
        }
        .processing-stage h4 {
            margin: 0 0 0.5rem;
            color: var(--agent-text);
            font-size: 0.94rem;
            line-height: 1.4;
            font-weight: 600;
        }
        .processing-stage p {
            margin: 0.32rem 0;
            color: var(--agent-muted);
            font-size: 0.82rem;
            line-height: 1.65;
        }
        .processing-stage strong {
            color: var(--agent-text-soft);
            font-weight: 600;
        }
        .processing-plan-foot {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.72rem;
            margin-top: 0.72rem;
        }
        .processing-plan-note {
            padding: 0.82rem 0.95rem;
            border-left: 2px solid rgba(249, 115, 22, 0.55);
            color: var(--agent-muted);
            background: rgba(249, 115, 22, 0.045);
            font-size: 0.8rem;
            line-height: 1.65;
        }
        .processing-plan-note strong {
            color: var(--agent-text-soft);
        }
        .processing-plan-note:last-child {
            grid-column: 1 / -1;
        }
        @media (max-width: 760px) {
            .processing-plan-head {
                flex-direction: column;
            }
            .processing-plan-status {
                max-width: 100%;
                text-align: left;
            }
            .processing-stage-grid,
            .processing-plan-foot {
                grid-template-columns: 1fr;
            }
            .processing-stage:last-child {
                grid-column: auto;
            }
            .processing-plan-note:last-child {
                grid-column: auto;
            }
        }
        .message-row {
            margin: 0 0 1.8rem;
        }
        .message-row.user {
            justify-content: flex-end;
        }
        .message-row.user .message-avatar {
            display: none;
        }
        .message-row.user .message-bubble {
            flex: 0 1 760px;
            margin-left: auto;
            background: rgba(17, 21, 29, 0.86);
            border: 1px solid #2b3039;
            color: var(--agent-text);
            border-radius: 6px;
            padding: 1.05rem 1.18rem;
            font-size: 1.12rem;
            box-shadow: none;
        }
        .user-attachment-row {
            display: flex;
            justify-content: flex-end;
            margin: 0 0 0.65rem;
        }
        .user-attachment {
            display: block;
            width: min(22rem, 58vw);
            max-height: 24rem;
            object-fit: contain;
            border: 1px solid #2b3039;
            border-radius: 8px;
            background: rgba(17, 21, 29, 0.86);
        }
        .message-row.assistant {
            display: grid;
            grid-template-columns: 6.8rem minmax(0, 1fr);
            gap: 1.45rem;
            align-items: start;
        }
        .message-row.assistant .message-avatar {
            width: auto;
            min-width: 0;
            height: auto;
            margin: 0;
            padding: 0.66rem 1.2rem 0 0;
            justify-content: flex-start;
            align-items: flex-start;
            background: transparent;
            border-radius: 0;
            color: var(--agent-accent);
            box-shadow: none;
            font-size: 0.86rem;
            line-height: 1.2;
            font-style: italic;
            font-weight: 420;
            border-right: 1px solid rgba(217, 189, 130, 0.16);
        }
        .message-row.assistant .message-bubble {
            background: transparent;
            border: 0;
            box-shadow: none;
            padding: 0;
            color: var(--agent-text);
            font-size: 1.08rem;
            line-height: 1.78;
        }
        .analysis-shell {
            margin: 0 0 1.9rem 8.25rem;
            padding-top: 0;
        }
        code, pre, kbd, samp {
            color: #e4c98e !important;
        }
        [data-testid="stMarkdownContainer"] code {
            color: #e4c98e !important;
            background: #0a0b0f !important;
            border: 1px solid rgba(217, 189, 130, 0.12);
            border-radius: 5px;
            padding: 0.12rem 0.38rem;
        }
        div[data-testid="stExpander"] {
            border-color: rgba(217, 189, 130, 0.17) !important;
            background: rgba(11, 13, 18, 0.72) !important;
            border-radius: 6px !important;
        }
        div[data-testid="stExpander"] summary {
            color: var(--agent-text) !important;
            letter-spacing: 0.04em;
            background: rgba(11, 13, 18, 0.72) !important;
            border-bottom: 1px solid transparent;
        }
        div[data-testid="stExpander"] summary:hover,
        div[data-testid="stExpander"] details[open] > summary {
            background: rgba(17, 21, 29, 0.78) !important;
            border-bottom-color: rgba(217, 189, 130, 0.14) !important;
            color: var(--agent-text) !important;
        }
        div[data-testid="stExpander"] summary * {
            color: var(--agent-text) !important;
            background: transparent !important;
        }
        div[data-testid="stExpander"] details,
        div[data-testid="stExpander"] div[role="region"] {
            background: rgba(8, 10, 14, 0.72) !important;
        }
        div[data-testid="stExpander"]:has(.score-bars) {
            border-color: rgba(217, 189, 130, 0.2) !important;
            background: rgba(8, 10, 14, 0.82) !important;
        }
        div[data-testid="stExpander"]:has(.score-bars) summary {
            background: rgba(17, 21, 29, 0.72) !important;
            border-bottom: 1px solid rgba(217, 189, 130, 0.15);
        }
        .score-fill {
            background: linear-gradient(90deg, #8f7450, #e0c286);
        }
        .score-row {
            background: rgba(17, 21, 29, 0.72);
            border-color: rgba(217, 189, 130, 0.16);
        }
        .score-track {
            background: rgba(217, 189, 130, 0.1);
        }
        div[data-testid="stExpander"]:has(.tool-steps),
        div[data-testid="stExpander"]:has(.report-anchor) {
            border-color: rgba(217, 189, 130, 0.2) !important;
            background: rgba(8, 10, 14, 0.82) !important;
        }
        .tool-step {
            background: rgba(17, 21, 29, 0.72);
            border-color: rgba(217, 189, 130, 0.16);
        }
        div[data-testid="stExpander"]:has(.report-anchor) [data-testid="stMarkdownContainer"] {
            color: var(--agent-text-soft) !important;
        }
        div[data-testid="stExpander"]:has(.report-anchor) [data-testid="stMarkdownContainer"] h1 {
            color: var(--agent-text) !important;
            font-size: clamp(2rem, 3.5vw, 3.6rem) !important;
            line-height: 1.08 !important;
            margin: 0.55rem 0 1.1rem !important;
        }
        div[data-testid="stExpander"]:has(.report-anchor) [data-testid="stMarkdownContainer"] h2 {
            color: #f1dfad !important;
            font-size: 1.24rem !important;
            line-height: 1.35 !important;
            margin-top: 1.45rem !important;
            padding-top: 1rem;
            border-top: 1px solid rgba(217, 189, 130, 0.12);
        }
        div[data-testid="stExpander"]:has(.report-anchor) [data-testid="stMarkdownContainer"] h3 {
            color: var(--agent-text) !important;
            font-size: 1.02rem !important;
        }
        div[data-testid="stExpander"]:has(.report-anchor) [data-testid="stMarkdownContainer"] p,
        div[data-testid="stExpander"]:has(.report-anchor) [data-testid="stMarkdownContainer"] li {
            color: var(--agent-text-soft) !important;
            line-height: 1.76 !important;
        }
        div[data-testid="stExpander"]:has(.report-anchor) [data-testid="stCaptionContainer"],
        div[data-testid="stExpander"]:has(.report-anchor) .stCaption {
            color: var(--agent-muted) !important;
        }
        [data-testid="stFileUploader"] section,
        [data-testid="stTextArea"] div[data-baseweb="textarea"],
        [data-testid="stTextArea"] div[data-baseweb="base-input"],
        [data-testid="stTextAreaRootElement"],
        textarea,
        input {
            background: rgba(17, 21, 29, 0.82) !important;
            border-color: rgba(217, 189, 130, 0.16) !important;
            color: var(--agent-text) !important;
            border-radius: 6px !important;
        }
        [data-testid="stBottom"],
        [data-testid="stBottomBlockContainer"] {
            background: rgba(8, 9, 12, 0.92) !important;
            border-top: 1px solid rgba(217, 189, 130, 0.08);
        }
        [data-testid="stChatInput"] textarea,
        [data-testid="stChatInput"] input {
            box-sizing: border-box !important;
            min-height: 3.85rem !important;
            background: rgba(17, 21, 29, 0.98) !important;
            border: 1px solid rgba(217, 189, 130, 0.2) !important;
            border-radius: 6px !important;
            color: var(--agent-text) !important;
            box-shadow: 0 24px 76px rgba(0, 0, 0, 0.46);
            font-size: 1rem !important;
            line-height: 1.5rem !important;
            padding: 1.1rem 4.1rem 1.1rem 1rem !important;
        }
        [data-testid="stChatInput"] textarea::placeholder,
        [data-testid="stChatInput"] input::placeholder {
            color: rgba(222, 211, 187, 0.52) !important;
            opacity: 1 !important;
        }
        [data-testid="stChatInput"] textarea:focus,
        [data-testid="stChatInput"] input:focus {
            border-color: rgba(217, 189, 130, 0.66) !important;
            box-shadow: 0 0 0 1px rgba(217, 189, 130, 0.24), 0 24px 76px rgba(0, 0, 0, 0.46);
        }
        [data-testid="stChatInput"] button {
            background: transparent !important;
            color: var(--agent-accent) !important;
        }
        @media (max-width: 860px) {
            .block-container {
                padding: 1.45rem 1rem 8.2rem;
            }
            .hero {
                padding: 1.2rem 0 0.8rem;
            }
            [class*="st-key-empty_state_shell"] {
                box-sizing: border-box;
                min-height: 0;
                padding: 1rem 0 0;
            }
            .block-container:has([class*="st-key-empty_state_shell"]) {
                padding-block: 1.45rem;
            }
            .message-row.assistant {
                grid-template-columns: 1fr;
                gap: 0.65rem;
            }
            .message-row.assistant .message-avatar {
                border-right: 0;
                border-bottom: 1px solid rgba(217, 189, 130, 0.16);
                padding-bottom: 0.45rem;
            }
            .analysis-shell {
                margin-left: 0;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
            restored = manager.restore_session_messages(user_id, session_id, project_id)
            st.session_state.agent_messages = [
                {
                    "role": item["role"],
                    "content": item["content"],
                    "message_id": item["message_id"],
                    "audit_trace": (item.get("metadata") or {}).get("audit_trace"),
                }
                for item in restored
                if item["role"] in {"user", "assistant"}
            ]
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


def init_state() -> None:
    st.session_state.setdefault("agent_messages", [])
    st.session_state.setdefault("current_batch", None)
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_vision_context", None)
    st.session_state.setdefault("clear_sidebar_inputs", False)
    st.session_state.setdefault("image_uploader_version", 0)
    initialize_memory_identity()
    if st.session_state.clear_sidebar_inputs:
        reset_sidebar_inputs()
        st.session_state.clear_sidebar_inputs = False


def render_sidebar() -> tuple[str, bool, bytes | None, str]:
    with st.sidebar:
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
        )

        st.markdown('<div class="sidebar-section-title">视觉输入</div>', unsafe_allow_html=True)
        uploader_version = int(st.session_state.image_uploader_version)
        uploaded_image = st.file_uploader(
            "上传柑橘图片",
            type=list(SUPPORTED_UPLOAD_EXTENSIONS),
            key=image_uploader_key(),
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
                st.image(prepared_image.data, caption="图片预览", width="stretch")
                st.info("图片会在本轮分析中自动调用视觉模型识别；下方外观描述可作为人工补充。")
                st.button(
                    "× 删除图片",
                    width="stretch",
                    key=f"remove_uploaded_image_{uploader_version}",
                    on_click=reset_uploaded_image,
                )

        manual_observation = st.text_area(
            "外观描述",
            placeholder="例如：果皮完整，颜色偏成熟，无明显霉斑或腐烂。",
            height=120,
            key="manual_observation",
        )

        st.divider()

        st.markdown(
            f"""
            <div class="sidebar-section-title">语言模型</div>
            <div class="status-list">
                <div class="status-row"><span>DeepSeek</span><span class="status-pill">{DEEPSEEK_MODEL}</span></div>
                <div class="status-row"><span>Qwen Vision</span><span class="status-pill">{get_vision_model()}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    image_bytes = prepared_image.data if prepared_image else None
    image_mime_type = prepared_image.mime_type if prepared_image else "image/jpeg"
    return manual_observation, prepared_image is not None, image_bytes, image_mime_type


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


def clean_assistant_text(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^(\s*\d+)[.)]\s+", r"\1. ", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
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
        st.markdown('<div class="analysis-shell">', unsafe_allow_html=True)
        render_analysis_payload(message["payload"])
        st.markdown('</div>', unsafe_allow_html=True)
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
        content = html.escape(content_text).replace("\n", "<br>")
        st.markdown(
            f'<div class="message-row user"><div class="message-bubble">{content}</div></div>',
            unsafe_allow_html=True,
        )
        return

    content = html.escape(clean_assistant_text(content_text)).replace("\n", "<br>")
    st.markdown(
        f'<div class="message-row assistant"><div class="message-avatar assistant">Citrus AI</div><div class="message-bubble">{content}</div></div>',
        unsafe_allow_html=True,
    )


def render_empty_state(api_key: str) -> str | None:
    selected_prompt = None
    with st.container(key="empty_state_shell"):
        st.markdown('<div class="hero"><h1>柑橘产业链决策</h1></div>', unsafe_allow_html=True)
        if not api_key:
            st.warning("请先在 agent/llm_config.py 中填入 DeepSeek API Key；未填时仍可运行本地规则工具，但不能生成大模型总结。")

        left, center, right = st.columns([1, 2.25, 1])
        with center:
            st.markdown('<div class="prompt-grid-label">请选择本次需要开展的工作</div>', unsafe_allow_html=True)
            for row_start in range(0, len(EXAMPLE_CARDS), 2):
                cols = st.columns(2)
                for card_index, (col, card) in enumerate(
                    zip(cols, EXAMPLE_CARDS[row_start : row_start + 2]),
                    start=row_start,
                ):
                    label = f"{card['title']}\n{card['description']}"
                    if col.button(label, width="stretch", key=f"example_card_{card_index}"):
                        selected_prompt = card["prompt"]
    return selected_prompt


def render_agent_progress(slot: Any, message: str) -> None:
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

    try:
        manager.record_message(
            user_id,
            session_id,
            project_id,
            "assistant",
            assistant_text,
            message_id=assistant_message["message_id"],
            message_type="analysis" if mode == "analysis" else "chat",
            metadata={"run_id": run_id, "audit_trace": audit_trace},
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
    progress_slot = st.empty()
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
        render_agent_progress(progress_slot, "正在读取图片并回答本轮问题")
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
        render_agent_progress(progress_slot, "正在全面检索本地文献并组织专业回答")
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
    st.set_page_config(page_title="柑橘产业链 Agent", layout="wide")
    inject_style()
    init_state()
    restore_scroll_position = bool(st.session_state.pop("restore_main_scroll_position", False))

    api_key = get_deepseek_api_key()
    manual_observation, has_image, image_bytes, image_mime_type = render_sidebar()

    if not st.session_state.agent_messages:
        selected_prompt = render_empty_state(api_key)
    else:
        selected_prompt = None
        st.markdown('<div class="chat-transcript-start"></div>', unsafe_allow_html=True)
        for message in st.session_state.agent_messages:
            render_message(message)

    typed_prompt = st.chat_input("输入问题，或粘贴批次信息开始分析...")
    render_scroll_position_manager(restore=restore_scroll_position)
    prompt = typed_prompt or selected_prompt
    if prompt:
        handle_prompt(prompt, api_key, manual_observation, has_image, image_bytes, image_mime_type)


if __name__ == "__main__":
    main()










