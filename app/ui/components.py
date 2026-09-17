from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import streamlit as st

from agent.vision_client import MAX_UPLOAD_BYTES, SUPPORTED_UPLOAD_EXTENSIONS


NAV_GROUPS = (
    ("data", "资料与数据", "Data & records", (("intake", "file-text", "资料确认", "Data intake"),)),
    ("process", "路线与工艺", "Routes & process", (("decision", "decision", "路线决策", "Decision"), ("process", "factory", "工艺方案", "Process"))),
    ("matching", "供需匹配", "Supply & demand", (("matching", "share", "供需匹配", "Matching"),)),
    ("insights", "可视化与报告", "Insights & reports", (("analytics", "chart-no-axes", "数据看板", "Data board"), ("report", "file-text", "报告撰写", "Report"))),
    ("review", "审核发布", "Review & publish", (("review", "shield", "审核发布", "Review"),)),
    ("knowledge", "知识与标准", "Knowledge & standards", (("knowledge", "book-open", "知识与标准", "Knowledge"),)),
)
NAV_ITEMS = tuple(item for _key, _zh, _en, items in NAV_GROUPS for item in items)


def normalize_product_view(view: str) -> str:
    """Keep saved links and sessions usable after retiring overview pages."""
    normalized = str(view or "").strip().lower().replace("-", "_").replace(" ", "_")
    return {
        "workspace": "intake",
        "工作台": "intake",
        # Data cleaning is an automatic intake pipeline step, not a separate
        # user-facing workspace. Keep old links usable by opening intake.
        "assets": "intake",
        "data_assets": "intake",
        "data_cleaning": "intake",
        "数据资产": "intake",
        "数据清洗": "intake",
        "results": "report",
        "成果中心": "report",
        "运行分析": "analytics",
        "分析": "analytics",
    }.get(normalized, normalized)


WORKFLOW_STEPS = (
    ("intake", "资料确认"),
    ("evidence", "分析证据"),
    ("decision", "路线决策"),
    ("process", "工艺方案"),
    ("report", "报告撰写"),
    ("review", "审核发布"),
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
    "chart-no-axes": '<path d="M3 3v18h18"/><path d="M7 17v-5"/><path d="M12 17V8"/><path d="M17 17V5"/>',
    "settings": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.09a2 2 0 0 1-1-1.74v-.51a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "help-circle": '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 1 1 5.83 1c0 2-3 2-3 4"/><path d="M12 18h.01"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "panel-left": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "file-text": '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="8" x2="16" y1="13" y2="13"/><line x1="8" x2="16" y1="17" y2="17"/>',
    "decision": '<rect x="3" y="3" width="15" height="16" rx="2"/><path d="M7 8h7"/><path d="M7 12h4"/><circle cx="17" cy="17" r="3"/><path d="m19.25 19.25 1.75 1.75"/>',
    "factory": '<path d="M3 21V9l6 3V8l6 3V4h4v17"/><path d="M3 21h18"/><path d="M7 17v-2"/><path d="M12 17v-2"/>',
    "circle-yen": '<circle cx="12" cy="12" r="10"/><path d="m8 7 4 5 4-5"/><path d="M8 13h8"/><path d="M8 16h8"/><path d="M12 12v6"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3z"/><path d="m9 12 2 2 4-4"/>',
    "share": '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 13v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7"/>',
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


def render_light_table(
    rows: list[dict[str, Any]],
    empty_message: str,
    *,
    height: int = 360,
    variant: str = "data",
) -> None:
    """Render a safe, theme-independent light table for read-only data."""
    if not rows:
        st.info(empty_message)
        return

    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)

    safe_variant = {
        "settings": "settings-table",
        "workspace": "workspace-table",
        "knowledge": "knowledge-table",
    }.get(variant, "")
    safe_height = min(max(int(height), 120), 640)
    header_cells = "".join(
        f'<th scope="col">{html.escape(str(column))}</th>' for column in columns
    )
    body_rows: list[str] = []
    for row in rows:
        cells: list[str] = []
        for column in columns:
            value = row.get(column)
            display = "—" if value in (None, "") else str(value)
            escaped = html.escape(display)
            title = html.escape(display, quote=True)
            numeric_class = "is-numeric" if isinstance(value, (int, float)) else ""
            label = html.escape(str(column), quote=True)
            cells.append(
                f'<td class="{numeric_class}" data-label="{label}" '
                f'title="{title}">{escaped}</td>'
            )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    st.markdown(
        f"""
        <div class="data-table-shell {safe_variant}" style="--table-max-height:{safe_height}px"
             role="region" aria-label="数据表格" tabindex="0">
            <table>
                <thead><tr>{header_cells}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )
def _view_url(
    view: str,
    context_token: str = "",
    *,
    include_context: bool = True,
) -> str:
    values = {"view": view}
    if include_context and context_token:
        values["ctx"] = context_token
    return "?" + urlencode(values)


def render_primary_navigation(
    active_view: str,
    context_token: str = "",
    *,
    on_view_change: Callable[[str], None] | None = None,
) -> None:
    """Render the product-level rail used by every page."""
    passive_link = ' tabindex="-1" aria-hidden="true"' if on_view_change else ""
    items = []
    mobile_items = []
    for group_key, group_zh, group_en, group_items in NAV_GROUPS:
        group_links = []
        for view, icon, zh_label, en_label in group_items:
            active = " is-active" if view == active_view else ""
            current = ' aria-current="page"' if view == active_view else ""
            href = html.escape(_view_url(view, context_token), quote=True)
            item_icon = icon_svg(icon, 22)
            group_links.append(
                f'<a class="primary-nav-item{active}" href="{href}"{current}{passive_link}>'
                f'<span class="primary-nav-icon">{item_icon}</span>'
                f'<span class="primary-nav-copy"><span>{html.escape(zh_label)}</span>'
                f'<small>{html.escape(en_label)}</small></span></a>'
            )
            mobile_items.append(
                f'<a class="mobile-nav-item{active}" href="{href}" target="_self"{current}>'
                f'{item_icon}<span>{html.escape(zh_label)}</span></a>'
            )
        items.append(
            f'<section class="primary-nav-group primary-nav-group-{html.escape(group_key)}">'
            f'{"".join(group_links)}</section>'
        )

    home_href = html.escape(_view_url("intake", context_token), quote=True)
    create_href = html.escape(_view_url("intake", context_token), quote=True)
    settings_href = html.escape(_view_url("settings", context_token), quote=True)
    st.markdown(
        f"""
        <nav class="citrus-primary-rail" aria-label="产品导航">
            <a class="primary-brand" href="{home_href}" aria-label="Citrus AI 首页"{passive_link}>
                <span class="primary-brand-mark">{icon_svg("citrus", 32)}</span>
                <span class="primary-brand-copy"><span class="primary-brand-word">Citrus AI</span><small>INDUSTRY AGENT</small></span>
            </a>
            <a class="primary-create" href="{create_href}"{passive_link}>{icon_svg("plus", 18)}<span>新建业务任务</span></a>
            <div class="primary-nav-list">{"".join(items)}</div>
            <a class="primary-user" href="{settings_href}"{passive_link}>
                <span class="primary-user-avatar">CA</span>
                <span class="primary-user-copy"><span>Citrus AI</span><small>Pro</small></span>
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
                args=("intake",),
            )
        with st.container(key="product_create_action"):
            st.button(
                "新建业务任务",
                key="product_create_button",
                on_click=on_view_change,
                args=("intake",),
            )
        with st.container(key="product_nav_actions"):
            for view, _icon, zh_label, en_label in NAV_ITEMS:
                button_label = (
                    f"当前页面：{zh_label} · {en_label}"
                    if view == active_view
                    else f"{zh_label} · {en_label}"
                )
                st.button(
                    button_label,
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
    context_token: str = "",
    *,
    on_view_change: Callable[[str], None] | None = None,
) -> None:
    settings_href = html.escape(_view_url("settings", context_token), quote=True)
    passive_link = ' tabindex="-1" aria-hidden="true"' if on_view_change else ""
    # The top-level share link intentionally carries no resume credential. It
    # opens the same product view as a fresh anonymous context and therefore
    # cannot grant access to this browser's conversation or memory.
    current_path = _view_url(active_view, include_context=False)
    current_url = str(getattr(st.context, "url", "") or "")
    share_href = (
        current_url.split("?", 1)[0] + current_path if current_url else current_path
    )
    st.markdown(
        f"""
        <div class="citrus-topbar-context">
            <span class="topbar-context-icon">{icon_svg("factory", 19)}</span>
            <span><strong>柑橘产业链 Agent</strong><small>智能决策与加工工作台</small></span>
        </div>
        <div class="citrus-top-actions">
            <a class="top-icon-action" href="{settings_href}" aria-label="帮助与系统信息"{passive_link}>
                {icon_svg("help-circle", 20)}
            </a>
            <a class="top-icon-action" href="{settings_href}" aria-label="外观与主题设置"{passive_link}>
                {icon_svg("sun", 20)}
            </a>
            <a class="top-share-action" href="{html.escape(share_href, quote=True)}"
               target="_blank" rel="noopener noreferrer"
               aria-label="打开不包含会话数据的新链接" title="不包含当前会话或用户数据">
                {icon_svg("share", 20)}<span>无数据链接</span>
            </a>
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
        with st.container(key="top_theme_action"):
            st.button(
                "外观与主题设置",
                key="top_theme_button",
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
            icon=":material/chat:",
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
    del icon
    st.markdown(
        '<header class="product-page-header workbench-page-header">'
        f'<div class="product-page-eyebrow">{html.escape(eyebrow)}</div>'
        f'<h1 class="product-page-title">{html.escape(title)}</h1>'
        f'<p class="product-page-subtitle">{html.escape(description)}</p>'
        '</header>',
        unsafe_allow_html=True,
    )


def render_process_stepper(current: str) -> None:
    """Render the shared six-step task workflow."""
    keys = [key for key, _label in WORKFLOW_STEPS]
    try:
        current_index = keys.index(current)
    except ValueError:
        current_index = 0
    items = []
    for index, (key, label) in enumerate(WORKFLOW_STEPS):
        state = (
            " is-complete"
            if index < current_index
            else " is-active"
            if index == current_index
            else ""
        )
        marker = icon_svg("shield", 13) if index < current_index else str(index + 1)
        items.append(
            f'<div class="process-step{state}" data-step="{html.escape(key)}">'
            f'<span class="process-step-marker">{marker}</span>'
            f'<span class="process-step-label">{html.escape(label)}</span></div>'
        )
    st.markdown(
        '<nav class="process-stepper" aria-label="任务流程">'
        + "".join(items)
        + "</nav>",
        unsafe_allow_html=True,
    )


def status_badge(label: str, tone: str = "neutral") -> str:
    safe_tone = (
        tone
        if tone in {"neutral", "success", "warning", "danger", "dark"}
        else "neutral"
    )
    return f'<span class="status-badge is-{safe_tone}">{html.escape(label)}</span>'


def render_metric_cards(
    items: list[tuple[str, Any, str]], *, columns: int = 4
) -> None:
    safe_columns = min(max(int(columns), 1), 4)
    cards = []
    for label, value, note in items:
        note_html = f'<small>{html.escape(str(note))}</small>' if note else ""
        cards.append(
            '<article class="workbench-metric">'
            f'<span>{html.escape(str(label))}</span>'
            f'<strong>{html.escape(str(value))}</strong>'
            f'{note_html}</article>'
        )
    st.markdown(
        f'<section class="workbench-metrics cols-{safe_columns}">'
        + "".join(cards)
        + "</section>",
        unsafe_allow_html=True,
    )


def section_card(
    title: str, body: str, *, eyebrow: str = "", class_name: str = ""
) -> str:
    eyebrow_html = (
        f'<span class="section-card-eyebrow">{html.escape(eyebrow)}</span>'
        if eyebrow
        else ""
    )
    safe_class = html.escape(class_name, quote=True)
    return (
        f'<section class="workbench-section {safe_class}"><header>{eyebrow_html}'
        f'<h2>{html.escape(title)}</h2></header>'
        f'<div class="workbench-section-body">{body}</div></section>'
    )


def render_empty_state(
    title: str, description: str, *, icon: str = "file-text"
) -> None:
    st.markdown(
        f'<section class="workbench-empty">{icon_svg(icon, 25)}'
        f'<strong>{html.escape(title)}</strong>'
        f'<p>{html.escape(description)}</p></section>',
        unsafe_allow_html=True,
    )


def render_agent_panel(view: str) -> tuple[str, Any | None]:
    """Render one contextual Agent panel and return prompt plus optional image."""
    context = {
        "identity": (
            "身份说明",
            "先确认组织与角色，系统会据此限定数据范围和可执行动作。",
            ["不同身份有什么区别？", "我应该选择哪个身份？"],
        ),
        "workspace": (
            "当前重点",
            "优先处理资料不完整或等待确认的任务，再推进后续路线与报告。",
            ["今天最值得先做什么？", "查看需要我确认的任务"],
        ),
        "intake": (
            "缺失项检查",
            "我会检查批次字段、检测状态和附件，但不会把缺失数据推断为已确认。",
            ["还缺哪些资料？", "这批原料可以开始分析吗？"],
        ),
        "evidence": (
            "证据边界",
            "我会区分直接证据、参考证据与证据不足，并保留可回查来源。",
            ["解释当前证据强弱", "有哪些风险需要补证？"],
        ),
        "decision": (
            "路线建议",
            "推荐基于批次事实、规则与可核验证据；确认前仍可补充约束重新比较。",
            ["为什么推荐首选路线？", "加入成本约束重新比较"],
        ),
        "process": (
            "方案优化",
            "我会区分企业 SOP、文献参数和待小试参数，避免把候选值写成放行参数。",
            ["哪些参数必须小试？", "检查工艺风险点"],
        ),
        "matching": (
            "匹配解释",
            "先核验产品、质量、产能与交付硬条件，再解释综合适配度。",
            ["解释首选匹配原因", "还有哪些条件未满足？"],
        ),
        "report": (
            "撰写协作",
            "我可以改写章节、补充证据索引并检查敏感表述，任务事实保持不变。",
            ["检查报告证据边界", "改写执行摘要"],
        ),
        "review": (
            "发布前检查",
            "自动检查只负责定位问题；最终确认、签署和发布由具备权限的人员完成。",
            ["列出待人工确认项", "生成审核意见草稿"],
        ),
        "assets": (
            "数据复用",
            "我会标注来源、版本、权限与关联任务，避免重复录入和越权引用。",
            ["查找可复用数据", "哪些资产即将过期？"],
        ),
        "results": (
            "成果检索",
            "可以按任务、版本与成果类型查找，并追溯到生成它的原始任务。",
            ["汇总最近成果", "比较两个报告版本"],
        ),
        "knowledge": (
            "知识解释",
            "我会说明来源差异、证据等级和适用条件，不把弱证据当作确定结论。",
            ["如何判断证据强弱？", "查找适用的行业标准"],
        ),
        "analytics": (
            "运行诊断",
            "我会基于实际运行记录解释完成率、耗时与异常，不虚构成本或 Token 数据。",
            ["解释最近的运行瓶颈", "有哪些可执行改进？"],
        ),
        "settings": (
            "设置影响",
            "模型、权限和数据生命周期设置会影响可见范围、能力状态与系统安全。",
            ["当前启用了哪些模型？", "数据如何隔离与保存？"],
        ),
    }.get(
        view,
        ("当前上下文", "我会沿用当前任务上下文继续协作。", ["总结当前任务", "推荐下一步"]),
    )
    title, summary, questions = context
    task_context = st.session_state.get("industry_task_context") or {}
    task_id = str(task_context.get("task_id") or "")
    record_id = str(task_context.get("record_id") or "")
    contextual_messages = st.session_state.get("industry_context_messages") or []

    pending = ""
    prompt = ""
    submitted = False
    uploaded_image = None
    with st.container(key=f"agent_panel_shell_{view}"):
        st.markdown(
            '<header class="agent-panel-brand"><span class="agent-panel-mark">'
            + icon_svg("citrus", 19)
            + '</span><span class="agent-panel-identity"><strong>Citrus Agent</strong>'
            + '<small>页面助手</small></span><span class="agent-online">在线</span></header>',
            unsafe_allow_html=True,
        )
        with st.container(key=f"agent_panel_scroll_{view}"):
            st.markdown(
                f'<section class="agent-context-card"><div>{icon_svg("activity", 17)}'
                f'<strong>{html.escape(title)}</strong></div><p>{html.escape(summary)}</p></section>',
                unsafe_allow_html=True,
            )
            if task_id or record_id:
                st.markdown(
                    f'<div class="agent-task-binding"><span>当前任务</span>'
                    f'<code>{html.escape(task_id or "待生成")}</code>'
                    f'<small>批次记录：{html.escape(record_id or "待生成")}</small></div>',
                    unsafe_allow_html=True,
                )
            if contextual_messages:
                thread_items: list[str] = []
                for message in contextual_messages[-8:]:
                    content = html.escape(str(message.get("content") or "").strip()).replace(
                        "\n", "<br>"
                    )
                    if not content:
                        continue
                    if message.get("role") == "user":
                        thread_items.append(
                            f'<article class="agent-panel-message user"><p>{content}</p></article>'
                        )
                    else:
                        thread_items.append(
                            '<article class="agent-panel-message assistant">'
                            f'<span class="agent-message-mark">{icon_svg("citrus", 14)}</span>'
                            f'<div><b>Citrus Agent</b><p>{content}</p></div></article>'
                        )
                if thread_items:
                    st.markdown(
                        '<section class="agent-panel-conversation" aria-label="当前页面对话">'
                        '<header><strong>当前对话</strong><span>已关联此页面</span></header>'
                        '<div class="agent-panel-thread">'
                        + "".join(thread_items)
                        + "</div></section>",
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown(
                    '<div class="agent-panel-suggestions-label"><strong>建议提问</strong>'
                    '<span>选择一个问题开始</span></div>',
                    unsafe_allow_html=True,
                )
                with st.container(key=f"agent_panel_suggestions_{view}"):
                    for index, question in enumerate(questions):
                        if st.button(
                            question,
                            key=f"agent_quick_{view}_{index}",
                            width="stretch",
                        ):
                            pending = question

        with st.container(key=f"agent_composer_{view}"):
            with st.form(
                key=f"agent_panel_form_{view}_{task_id or 'unbound'}",
                border=False,
                clear_on_submit=True,
            ):
                # Submit image and text as one form state, including image-only messages.
                uploaded_image = st.file_uploader(
                    "添加图片",
                    type=SUPPORTED_UPLOAD_EXTENSIONS,
                    max_upload_size=MAX_UPLOAD_BYTES // (1024 * 1024),
                    key=f"agent_panel_upload_{view}",
                    label_visibility="collapsed",
                    help="上传柑橘图片，发送后由视觉模型进行识别",
                )
                prompt = st.text_input(
                    "询问当前页面或继续任务",
                    placeholder="向 Citrus Agent 提问…",
                    label_visibility="collapsed",
                    key=f"agent_panel_prompt_{view}",
                )
                submitted = st.form_submit_button(
                    "发送",
                    icon=":material/arrow_upward:",
                    help="发送给 Agent",
                    width="content",
                )
    if submitted:
        pending = prompt.strip()
        if not pending and uploaded_image is not None:
            pending = "请识别这张图片，并说明可见特征和需要进一步确认的信息。"
    return pending, uploaded_image


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
