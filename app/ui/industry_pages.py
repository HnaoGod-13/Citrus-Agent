"""Session-scoped industry demo, inside the unchanged Citrus AI product shell.

The isolated component owns only its canvas. It cannot publish real listings,
contact counterparties, or mutate Agent/knowledge data.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_ASSETS = Path(__file__).parent / "industry_workspace"


def current_industry_view() -> str:
    allowed = {"production", "supply", "demand", "match"}
    query = st.query_params.get("industry", "")
    if isinstance(query, list):
        query = query[0] if query else ""
    query = str(query).strip().lower()
    saved = st.session_state.get("industry_workspace_view", "production")
    selected = query if query in allowed else saved if saved in allowed else "production"
    st.session_state.industry_workspace_view = selected
    return selected


def _save_snapshot() -> None:
    snapshot = st.session_state.get("industry_workspace_canvas", {}).get("snapshot")
    if isinstance(snapshot, dict):
        st.session_state.industry_ui_model = snapshot


def render_industry_workspace() -> None:
    # Register in the active runtime, including a fresh AppTest or hot reload.
    # Registering an identical definition is idempotent in Streamlit 1.61.
    canvas = st.components.v2.component(
        "citrus_industry_workspace_v3",
        html='<div class="iw" data-industry-canvas="v3"></div>',
        css=(_ASSETS / "workspace.css").read_text(encoding="utf-8"),
        js=(_ASSETS / "workspace.js").read_text(encoding="utf-8"),
        isolate_styles=True,
    )
    canvas(
        key="industry_workspace_canvas",
        data={
            "view": current_industry_view(),
            "model": st.session_state.get("industry_ui_model", {}),
            "photo": "app/static/industry/supply-reference.png",
        },
        on_snapshot_change=_save_snapshot,
        height="content",
        width="stretch",
    )


__all__ = ["current_industry_view", "render_industry_workspace"]
