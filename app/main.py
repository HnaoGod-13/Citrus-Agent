from __future__ import annotations

import html
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import llm_client, orchestrator, vision_client, workflow

llm_client = importlib.reload(llm_client)
workflow = importlib.reload(workflow)
orchestrator = importlib.reload(orchestrator)
vision_client = importlib.reload(vision_client)
DEEPSEEK_MODEL = llm_client.DEEPSEEK_MODEL
DeepSeekAPIError = llm_client.DeepSeekAPIError
build_general_chat_messages = llm_client.build_general_chat_messages
chat_with_deepseek = llm_client.chat_with_deepseek
get_deepseek_api_key = llm_client.get_deepseek_api_key
get_vision_model = vision_client.get_vision_model
prepare_image_for_vision = vision_client.prepare_image_for_vision
SUPPORTED_UPLOAD_EXTENSIONS = vision_client.SUPPORTED_UPLOAD_EXTENSIONS


EXAMPLE_PROMPTS = [
    "我有一批新会茶枝柑，糖度10.5，水分18%，客户是茶饮品牌，帮我按果皮、果肉和副产物拆开判断加工方向并出报告。",
    "这批果皮完整、颜色偏成熟、无明显霉斑，农残和重金属还没做，适合做陈皮、陈皮丝还是果皮精油/果胶？",
    "产地赣南，品种脐橙，糖度12.2，酸度0.7，食品加工厂客户，优先看果肉方向，顺便评估整果和果皮利用。",
    "帮我把当前批次按整果、果肉、果皮、种子、副产物整理成质控复核清单。",
]

EXAMPLE_CARDS = [
    {
        "eyebrow": "果皮决策",
        "title": "新会茶枝柑批次分析",
        "description": "陈皮、陈皮丝、精油与果胶路线",
        "prompt": EXAMPLE_PROMPTS[0],
    },
    {
        "eyebrow": "质控边界",
        "title": "未检批次风险复核",
        "description": "农残、重金属、霉变与放行条件",
        "prompt": EXAMPLE_PROMPTS[1],
    },
    {
        "eyebrow": "果肉加工",
        "title": "赣南脐橙果汁方向",
        "description": "NFC、浓缩汁、果粒与整果利用",
        "prompt": EXAMPLE_PROMPTS[2],
    },
    {
        "eyebrow": "报告草稿",
        "title": "全链路复核清单",
        "description": "整果、果肉、果皮、种子、副产物",
        "prompt": EXAMPLE_PROMPTS[3],
    },
]


def item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


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
        }
        [data-testid="stFileUploader"] button {
            background: rgba(255, 255, 255, 0.08) !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            color: var(--agent-text-soft) !important;
            border-radius: 8px;
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
        div[data-testid="stButton"] > button:hover p,
        div[data-testid="stButton"] > button:hover span {
            color: var(--agent-text) !important;
        }
        div[data-testid="stButton"] > button:focus:not(:active) {
            border-color: rgba(217, 189, 130, 0.62);
            box-shadow: 0 0 0 1px rgba(217, 189, 130, 0.2);
        }
        .hero {
            max-width: 760px;
            margin: 0 auto;
            padding: 5.8rem 0 1.25rem;
        }
        .hero h1 {
            color: var(--agent-text);
            font-size: clamp(2.75rem, 6.1vw, 5.4rem);
            line-height: 1;
            font-weight: 420;
            letter-spacing: 0;
            margin-bottom: 1.18rem;
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
            margin: 2rem auto 0.75rem;
            color: var(--agent-faint);
            font-family: var(--agent-mono-font-family) !important;
            font-size: 0.68rem;
            letter-spacing: 0.16em;
            text-transform: uppercase;
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
            min-height: 3.85rem !important;
            background: rgba(17, 21, 29, 0.98) !important;
            border: 1px solid rgba(217, 189, 130, 0.2) !important;
            border-radius: 6px !important;
            color: var(--agent-text) !important;
            box-shadow: 0 24px 76px rgba(0, 0, 0, 0.46);
            font-size: 1rem !important;
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
                padding-top: 2.2rem;
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


def init_state() -> None:
    st.session_state.setdefault("agent_messages", [])
    st.session_state.setdefault("current_batch", None)
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("clear_sidebar_inputs", False)
    if st.session_state.clear_sidebar_inputs:
        st.session_state.pop("uploaded_citrus_image", None)
        st.session_state.pop("manual_observation", None)
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

        if st.button("＋ 新建对话", width="stretch"):
            st.session_state.agent_messages = []
            st.session_state.current_batch = None
            st.session_state.last_result = None
            st.session_state.pop("uploaded_citrus_image", None)
            st.session_state.pop("manual_observation", None)
            st.rerun()

        st.markdown('<div class="sidebar-section-title">视觉输入</div>', unsafe_allow_html=True)
        uploaded_image = st.file_uploader(
            "上传柑橘图片",
            type=list(SUPPORTED_UPLOAD_EXTENSIONS),
            key="uploaded_citrus_image",
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
                st.caption("；".join(prepared_image.notes))
                st.info("图片会在本轮分析中自动调用视觉模型识别；下方外观描述可作为人工补充。")
        st.caption("支持 JPG、PNG、WebP、BMP、GIF、TIFF、HEIC/HEIF、AVIF、JPEG 2000、ICO 等常见格式；单文件不超过 40 MB。")

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
            <div class="sidebar-section-title">计算工具</div>
            <div class="status-list">
                <div class="status-row"><span>Literature RAG</span><span class="status-pill">local chunks · evidence</span></div>
                <div class="status-row"><span>Rule Engine</span><span class="status-pill">processing score · QC risk</span></div>
                <div class="status-row"><span>Report Builder</span><span class="status-pill">markdown · audit log</span></div>
            </div>
            <div class="sidebar-section-title">工作流</div>
            <div class="status-list">
                <div class="status-row"><span>批次抽取</span><span class="status-pill">text / image / manual notes</span></div>
                <div class="status-row"><span>路线评分</span><span class="status-pill">whole · pulp · peel · seed · byproduct</span></div>
                <div class="status-row"><span>复核输出</span><span class="status-pill">risk boundary · report draft</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.divider()
        st.markdown(
            '<div class="sidebar-note">检测、放行、标签和报价仍需人工复核；Demo 输出仅作为加工决策草稿。</div>',
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
                "评分": item_value(item, "score", 0),
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
        try:
            score = int(item_value(item, "score", 0))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))
        reason_text = "；".join(reasons) or "暂无"
        risk_text = "；".join(risk_notes) or "暂无"
        rows.append(
            '<div class="score-row">'
            '<div class="score-head">'
            f'<div class="score-name" title="{direction}">{direction}</div>'
            f'<div class="score-value">{score}/100</div>'
            '</div>'
            f'<div class="score-track"><div class="score-fill" style="width: {score}%"></div></div>'
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

    if payload.get("llm_answer"):
        st.markdown(payload["llm_answer"])
    else:
        st.markdown(payload["summary"])

    if payload.get("vision_result"):
        with st.expander("图片识别结果", expanded=True):
            vision_result = payload["vision_result"]
            st.write(vision_result.get("appearance_description", ""))
            for note in vision_result.get("risk_notes", []):
                st.warning(note)
            st.json(vision_result.get("structured_observation", {}))

    with st.expander("工具调用过程", expanded=False):
        render_tool_steps(result)

    with st.expander("加工评分与质控风险", expanded=False):
        if scores:
            render_score_bars(scores)
        else:
            st.info("暂无加工方向评分。")
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
            for item in evidence:
                title = item.get("title") or "未命名文献"
                year = item.get("year") or "年份未知"
                st.markdown(f"**{title}（{year}）** · 匹配分 {item.get('match_score')}")
                st.write(item.get("chunk_text"))
                page_text = f"；页码：{item.get('page')}" if item.get("page") else ""
                doi_text = f"；DOI：{item.get('doi')}" if item.get("doi") else ""
                st.caption(f"来源：{item.get('source')}；主题：{item.get('topic')}{page_text}{doi_text}")
        else:
            st.info("没有检索到文献片段，请补充或重建文献库数据。")

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
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">CITRUS PROCESSING · RAG · QC REVIEW</div>
            <h1>与柑橘产业链对话</h1>
            <p>基于本地文献库、加工路线评分和质控边界，生成可追溯、可复核的批次决策草稿。</p>
        </div>
        <div class="prompt-grid-label">示例数据（点击后会立即作为一轮演示提交）</div>
        """,
        unsafe_allow_html=True,
    )
    if not api_key:
        st.warning("请先在 agent/llm_config.py 中填入 DeepSeek API Key；未填时仍可运行本地规则工具，但不能生成大模型总结。")

    selected_prompt = None
    left, center, right = st.columns([0.65, 2.7, 0.65])
    with center:
        for row_start in range(0, len(EXAMPLE_CARDS), 2):
            cols = st.columns(2)
            for col, card in zip(cols, EXAMPLE_CARDS[row_start : row_start + 2]):
                label = f"{card['eyebrow']}\n{card['title']}\n{card['description']}"
                if col.button(label, width="stretch"):
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
            content = str(payload.get("llm_answer") or payload.get("summary") or "").strip()
            if content:
                history.append({"role": "assistant", "content": content})
            continue
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            history.append({"role": role, "content": content})
    return history


def run_general_turn(prompt: str, api_key: str, history: list[dict[str, str]]) -> str:
    if not api_key:
        return "我可以帮你调用本地批次分析工具。若要普通大模型问答，请先在 `agent/llm_config.py` 中填入 DeepSeek API Key。"
    messages = build_general_chat_messages(history, prompt)
    try:
        return chat_with_deepseek(api_key, messages)
    except DeepSeekAPIError as error:
        return f"调用 DeepSeek 失败：{error}"


def handle_prompt(
    prompt: str,
    api_key: str,
    manual_observation: str,
    has_image: bool,
    image_bytes: bytes | None,
    image_mime_type: str,
) -> None:
    history = build_conversation_history(st.session_state.agent_messages)
    st.session_state.agent_messages.append({"role": "user", "content": prompt})

    importlib.reload(workflow)
    live_orchestrator = importlib.reload(orchestrator)
    progress_slot = st.empty()
    references_current = (
        st.session_state.current_batch is not None
        and live_orchestrator.references_current_batch(prompt)
    )
    batch_for_turn = st.session_state.current_batch if references_current else None
    previous_observation = ""
    if references_current and st.session_state.last_result:
        previous_observation = str(st.session_state.last_result.get("image_observation") or "")
    effective_observation = manual_observation.strip() or previous_observation
    missing_inputs = live_orchestrator.missing_batch_inputs(
        prompt,
        current_batch=batch_for_turn,
        manual_observation=effective_observation,
        has_image=has_image,
    )

    if live_orchestrator.should_request_batch_data(
        prompt,
        current_batch=batch_for_turn,
        manual_observation=effective_observation,
        has_image=has_image,
    ):
        answer = live_orchestrator.build_batch_data_request(missing_inputs)
        st.session_state.agent_messages.append({"role": "assistant", "content": answer})
    elif live_orchestrator.should_run_tools(
        prompt,
        has_image=has_image,
        has_current_batch=references_current,
        has_minimum_batch_data=not missing_inputs,
    ):
        def update_progress(message: str) -> None:
            render_agent_progress(progress_slot, message)

        update_progress("正在启动批次分析流程")
        try:
            payload = live_orchestrator.run_analysis_turn(
                user_prompt=prompt,
                api_key=api_key,
                history=history,
                current_batch=batch_for_turn,
                manual_observation=effective_observation,
                has_image=has_image,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                progress_callback=update_progress,
            )
        finally:
            progress_slot.empty()
        st.session_state.current_batch = payload["batch"]
        st.session_state.last_result = payload["result"]
        st.session_state.agent_messages.append({"role": "assistant", "kind": "analysis", "payload": payload})
    else:
        render_agent_progress(progress_slot, "正在连接模型并组织回答")
        try:
            answer = run_general_turn(prompt, api_key, history)
        finally:
            progress_slot.empty()
        st.session_state.agent_messages.append({"role": "assistant", "content": answer})

    st.session_state.clear_sidebar_inputs = True
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="柑橘产业链 Agent", layout="wide")
    inject_style()
    init_state()

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
    prompt = typed_prompt or selected_prompt
    if prompt:
        handle_prompt(prompt, api_key, manual_observation, has_image, image_bytes, image_mime_type)


if __name__ == "__main__":
    main()



















