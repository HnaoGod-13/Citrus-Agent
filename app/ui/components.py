from __future__ import annotations

import html
from collections.abc import Callable
from urllib.parse import urlencode

import streamlit as st


NAV_ITEMS = (
    ("chat", "message-circle", "对话", "Chat"),
    ("workspace", "layout-grid", "工作台", "Workspace"),
    ("knowledge", "book-open", "知识库", "Knowledge"),
    ("analytics", "chart-no-axes", "分析", "Analytics"),
    ("settings", "settings", "设置", "Settings"),
)


_ICON_PATHS: dict[str, str] = {
    "citrus": (
        '<path d="M12 2.75a9.25 9.25 0 1 0 9.25 9.25"/>'
        '<path d="M12 6.25A5.75 5.75 0 1 0 17.75 12"/>'
        '<path d="M12 9.75A2.25 2.25 0 1 0 14.25 12"/>'
    ),
    "message-circle": '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3v-7a4 4 0 0 1-1-2.65V7a4 4 0 0 1 4-4h11a4 4 0 0 1 4 4z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',
    "layout-grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/>',
    "book-open": '<path d="M2 4.5A2.5 2.5 0 0 1 4.5 2H11v18H4.5A2.5 2.5 0 0 0 2 22z"/><path d="M22 4.5A2.5 2.5 0 0 0 19.5 2H13v18h6.5A2.5 2.5 0 0 1 22 22z"/>',
    "chart-no-axes": '<path d="M4 19V9"/><path d="M10 19V5"/><path d="M16 19v-7"/><path d="M22 19V3"/>',
    "settings": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.09a2 2 0 0 1-1-1.74v-.51a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "help-circle": '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 1 1 5.83 1c0 2-3 2-3 4"/><path d="M12 18h.01"/>',
    "panel-left": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "file-text": '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="8" x2="16" y1="13" y2="13"/><line x1="8" x2="16" y1="17" y2="17"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3z"/><path d="m9 12 2 2 4-4"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
}


def icon_svg(name: str, size: int = 20, *, class_name: str = "") -> str:
    """Return a small, monochrome Lucide-style inline SVG."""
    paths = _ICON_PATHS.get(name, _ICON_PATHS["file-text"])
    safe_class = html.escape(class_name, quote=True)
    return (
        f'<svg class="{safe_class}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{paths}</svg>'
    )


def _view_url(view: str, uid: str, sid: str) -> str:
    values = {"view": view}
    if uid:
        values["uid"] = uid
    if sid:
        values["sid"] = sid
    return "?" + urlencode(values)


def render_primary_navigation(
    active_view: str,
    uid: str = "",
    sid: str = "",
    *,
    on_view_change: Callable[[str], None] | None = None,
) -> None:
    """Render the product-level rail used by every page."""
    passive_link = ' tabindex="-1" aria-hidden="true"' if on_view_change else ""
    items = []
    mobile_items = []
    for view, icon, zh_label, en_label in NAV_ITEMS:
        active = " is-active" if view == active_view else ""
        current = ' aria-current="page"' if view == active_view else ""
        href = html.escape(_view_url(view, uid, sid), quote=True)
        item_icon = icon_svg(icon, 20)
        items.append(
            f'<a class="primary-nav-item{active}" href="{href}"{current}{passive_link}>'
            f'<span class="primary-nav-icon">{item_icon}</span>'
            f'<span class="primary-nav-copy"><span>{html.escape(zh_label)}</span>'
            f'<small>{html.escape(en_label)}</small></span></a>'
        )
        mobile_items.append(
            f'<a class="mobile-nav-item{active}" href="{href}"{current}{passive_link}>'
            f'{item_icon}<span>{html.escape(zh_label)}</span></a>'
        )

    chat_href = html.escape(_view_url("chat", uid, sid), quote=True)
    settings_href = html.escape(_view_url("settings", uid, sid), quote=True)
    st.markdown(
        f"""
        <nav class="citrus-primary-rail" aria-label="产品导航">
            <a class="primary-brand" href="{chat_href}" aria-label="Citrus AI 首页"{passive_link}>
                <span class="primary-brand-mark">{icon_svg("citrus", 28)}</span>
                <span class="primary-brand-word">CITRUS AI</span>
            </a>
            <div class="primary-nav-list">{"".join(items)}</div>
            <a class="primary-user" href="{settings_href}"{passive_link}>
                <span class="primary-user-avatar">CA</span>
                <span class="primary-user-copy"><span>Citrus AI</span><small>Decision Lab · Pro</small></span>
                {icon_svg("chevron-down", 15)}
            </a>
        </nav>
        <nav class="citrus-mobile-nav" aria-label="移动端产品导航">{"".join(mobile_items)}</nav>
        """,
        unsafe_allow_html=True,
    )
    if on_view_change is not None:
        with st.container(key="product_brand_action"):
            st.button(
                "Citrus AI 首页",
                key="product_brand_button",
                on_click=on_view_change,
                args=("chat",),
            )
        with st.container(key="product_nav_actions"):
            for view, _icon, zh_label, en_label in NAV_ITEMS:
                st.button(
                    f"{zh_label} · {en_label}",
                    key=f"product_nav_button_{view}",
                    on_click=on_view_change,
                    args=(view,),
                )
        with st.container(key="product_user_action"):
            st.button(
                "Citrus AI 设置",
                key="product_user_button",
                on_click=on_view_change,
                args=("settings",),
            )


def render_top_actions(
    active_view: str,
    uid: str = "",
    sid: str = "",
    *,
    on_view_change: Callable[[str], None] | None = None,
) -> None:
    settings_href = html.escape(_view_url("settings", uid, sid), quote=True)
    passive_link = ' tabindex="-1" aria-hidden="true"' if on_view_change else ""
    st.markdown(
        f"""
        <div class="citrus-top-actions">
            <a href="{settings_href}" aria-label="帮助与系统信息"{passive_link}>{icon_svg("help-circle", 18)}<span>Help</span></a>
            <span class="top-status"><i></i>System ready</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if on_view_change is not None:
        with st.container(key="top_help_action"):
            st.button(
                "帮助与系统信息",
                key="top_help_button",
                on_click=on_view_change,
                args=("settings",),
            )


def render_mobile_panel_toggle(
    is_open: bool,
    on_toggle: Callable[[], None],
) -> None:
    """Render the mobile-only control and scrim for the secondary panel drawer."""
    state = "is-open" if is_open else "is-closed"
    st.markdown(
        f'<span class="mobile-panel-state {state}" aria-hidden="true"></span>',
        unsafe_allow_html=True,
    )
    with st.container(key="mobile_panel_toggle"):
        st.button(
            "关闭功能面板" if is_open else "打开功能面板",
            key="mobile_panel_toggle_button",
            on_click=on_toggle,
        )
    if is_open:
        with st.container(key="mobile_panel_scrim_action"):
            st.button(
                "关闭功能面板",
                key="mobile_panel_scrim_button",
                on_click=on_toggle,
            )


def render_secondary_intro(eyebrow: str, title: str, description: str = "") -> None:
    description_html = (
        f'<p class="secondary-description">{html.escape(description)}</p>' if description else ""
    )
    st.markdown(
        f"""
        <div class="secondary-intro">
            <div class="secondary-eyebrow">{html.escape(eyebrow)}</div>
            <h2>{html.escape(title)}</h2>
            {description_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(
    eyebrow: str,
    title: str,
    description: str,
    *,
    icon: str = "file-text",
) -> None:
    st.markdown(
        f"""
        <header class="product-page-header">
            <div class="page-header-icon">{icon_svg(icon, 20)}</div>
            <div class="page-header-eyebrow">{html.escape(eyebrow)}</div>
            <h1>{html.escape(title)}</h1>
            <p>{html.escape(description)}</p>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_empty_panel(title: str, description: str, *, icon: str = "folder") -> None:
    st.markdown(
        f"""
        <div class="ui-empty-state">
            <div class="ui-empty-icon">{icon_svg(icon, 20)}</div>
            <strong>{html.escape(title)}</strong>
            <p>{html.escape(description)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_heading(title: str, description: str = "") -> None:
    copy = f"<p>{html.escape(description)}</p>" if description else ""
    st.markdown(
        f'<div class="section-heading"><h2>{html.escape(title)}</h2>{copy}</div>',
        unsafe_allow_html=True,
    )
