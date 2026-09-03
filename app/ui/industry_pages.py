"""Industry-facing workspace surfaces for the Citrus AI demo.

The first release keeps the existing Agent workflow intact and adds a small,
session-scoped business layer on top of the current Workspace page. Values in
this module are intentionally synthetic until a real batch/CRM data source is
connected.
"""

from __future__ import annotations

import html
from datetime import date
from typing import Any

import streamlit as st

from app.ui import components as ui_components


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _init_state() -> None:
    st.session_state.setdefault(
        "industry_batch",
        {
            "batch_id": "GX-WG-20260903-01",
            "origin": "广西桂林",
            "variety": "沃柑",
            "weight": "20",
            "brix": "12.8",
            "supplier": "桂林示例果园",
            "fertilizer": "示例农资供应商",
            "process_note": "已完成采后分选，检测报告待补",
        },
    )
    st.session_state.setdefault(
        "industry_request",
        {
            "buyer": "示例果汁加工企业",
            "product": "NFC 果汁",
            "quantity": "15",
            "brix_min": "12",
            "delivery": "2026-09-10",
            "notes": "需要可追溯批次与农残报告",
        },
    )
    st.session_state.setdefault("industry_batch_saved", False)
    st.session_state.setdefault("industry_request_saved", False)
    st.session_state.setdefault("industry_connection_requested", False)
    st.session_state.setdefault("industry_report_generated", False)
    st.session_state.setdefault("industry_consent", False)


def _status(text: str, tone: str = "neutral") -> str:
    return f'<span class="industry-status {html.escape(tone)}">{_esc(text)}</span>'


def _section_heading(eyebrow: str, title: str, description: str = "") -> None:
    description_html = (
        f'<p class="industry-section-description">{_esc(description)}</p>'
        if description
        else ""
    )
    st.markdown(
        f"""
        <div class="industry-section-heading">
            <div class="industry-section-eyebrow">{_esc(eyebrow)}</div>
            <h2>{_esc(title)}</h2>
            {description_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _module_card(icon: str, title: str, english: str, description: str, status: str) -> None:
    st.markdown(
        f"""
        <article class="industry-module-card">
            <div class="industry-module-icon">{ui_components.icon_svg(icon, 21)}</div>
            <div class="industry-module-copy">
                <h3>{_esc(title)}</h3>
                <small>{_esc(english)}</small>
                <p>{_esc(description)}</p>
            </div>
            {_status(status, "ready")}
        </article>
        """,
        unsafe_allow_html=True,
    )


def _render_overview() -> None:
    batch = st.session_state.industry_batch
    request = st.session_state.industry_request
    _section_heading(
        "CITRUS AI · MY BUSINESS",
        "产业协作概览",
        "从批次采集到供需匹配，先把产业协作信息放在同一条工作线上。",
    )
    st.markdown(
        '<div class="industry-demo-strip">设计示例 · 演示数据 · 所有企业名称、批次和指标均为虚构</div>',
        unsafe_allow_html=True,
    )

    columns = st.columns(3)
    with columns[0]:
        _module_card(
            "database",
            "批次采集",
            "Batch intake",
            "产地、基础指标、投入品和加工信息统一归档。",
            "已保存" if st.session_state.industry_batch_saved else "待补充",
        )
    with columns[1]:
        _module_card(
            "factory",
            "供应与需求",
            "Supply & demand",
            "让供应端和采购端用同一组字段描述自己的条件。",
            "1 条需求",
        )
    with columns[2]:
        _module_card(
            "activity",
            "匹配与对接",
            "Match & connect",
            "先筛硬性条件，再进入授权、打样和报价沟通。",
            "3 个候选",
        )

    metric_columns = st.columns(4)
    metric_columns[0].metric("已登记批次", "06")
    metric_columns[1].metric("可供原料", "42 吨")
    metric_columns[2].metric("开放需求", "08 条")
    metric_columns[3].metric("待处理对接", "03 条")

    st.markdown(
        f"""
        <div class="industry-current-line">
            <span class="industry-current-dot"></span>
            <span>当前工作对象：{_esc(batch['batch_id'])} · {_esc(batch['origin'])}{_esc(batch['variety'])} · {_esc(batch['weight'])} 吨</span>
            <span class="industry-current-meta">目标需求：{_esc(request['buyer'])} · {_esc(request['product'])}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_batch_intake() -> None:
    batch = st.session_state.industry_batch
    _section_heading(
        "01 · INFORMATION COLLECTION",
        "批次采集",
        "供应端与加工端可以分别填写，Agent 只会展示获得授权的字段。",
    )
    with st.form("industry_batch_form", clear_on_submit=False):
        first = st.columns(3)
        with first[0]:
            batch_id = st.text_input("批次编号", value=batch["batch_id"])
        with first[1]:
            origin = st.text_input("产地", value=batch["origin"])
        with first[2]:
            variety = st.text_input("品种", value=batch["variety"])

        second = st.columns(4)
        with second[0]:
            weight = st.text_input("批次重量（吨）", value=batch["weight"])
        with second[1]:
            brix = st.text_input("糖度（°Brix）", value=batch["brix"])
        with second[2]:
            supplier = st.text_input("原料供应方", value=batch["supplier"])
        with second[3]:
            fertilizer = st.text_input("肥料供应商", value=batch["fertilizer"])

        process_note = st.text_area(
            "加工端补充",
            value=batch["process_note"],
            height=84,
            placeholder="可填写分选、清洗、冷链、设备或 SOP 状态；不填写虚构参数。",
        )
        sharing = st.columns([1.3, 1, 1])
        with sharing[0]:
            visibility = st.selectbox("对外可见范围", ["仅参与匹配", "已授权合作方", "企业内部"], index=0)
        with sharing[1]:
            st.caption("安全提示")
            st.caption("未检测字段不会被自动判定为合格。")
        with sharing[2]:
            submitted = st.form_submit_button("保存批次", width="stretch")

    if submitted:
        if not batch_id.strip() or not origin.strip() or not variety.strip():
            st.warning("批次编号、产地和品种是必填项。")
        else:
            st.session_state.industry_batch = {
                "batch_id": batch_id.strip(),
                "origin": origin.strip(),
                "variety": variety.strip(),
                "weight": weight.strip(),
                "brix": brix.strip(),
                "supplier": supplier.strip(),
                "fertilizer": fertilizer.strip(),
                "process_note": process_note.strip(),
            }
            st.session_state.industry_batch_saved = True
            st.success(f"批次已保存为演示草稿；当前共享范围：{visibility}。")

    st.markdown(
        f"""
        <div class="industry-data-summary">
            <div><span>批次</span><strong>{_esc(batch['batch_id'])}</strong></div>
            <div><span>原料</span><strong>{_esc(batch['origin'])} · {_esc(batch['variety'])}</strong></div>
            <div><span>基础指标</span><strong>{_esc(batch['weight'])} 吨 · {_esc(batch['brix'])} °Brix</strong></div>
            <div><span>检测状态</span><strong>{_status("农残报告待补", "pending")}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_supply() -> None:
    _section_heading(
        "02 · SUPPLY CENTER",
        "供应中心",
        "用可核验字段展示可供批次，不把“已上传”误写成“已放行”。",
    )
    supplies = [
        ("GX-WG-20260903-01", "广西桂林 · 沃柑", "20 吨", "12.8 °Brix", "已上传", "pending"),
        ("JX-NC-20260902-04", "江西赣南 · 脐橙", "12 吨", "12.2 °Brix", "已核验 3/4", "ready"),
        ("GD-CZ-20260901-02", "广东新会 · 茶枝柑", "8 吨", "10.5 °Brix", "待补检测", "pending"),
    ]
    for index in range(0, len(supplies), 3):
        row = st.columns(3)
        for column, item in zip(row, supplies[index : index + 3]):
            batch_id, name, quantity, metric, status, tone = item
            with column:
                st.markdown(
                    f"""
                    <article class="industry-supply-card">
                        <div class="industry-supply-card-head"><span class="industry-mini-icon">{ui_components.icon_svg('citrus', 18)}</span>{_status(status, tone)}</div>
                        <h3>{_esc(name)}</h3>
                        <p class="industry-card-id">{_esc(batch_id)}</p>
                        <div class="industry-card-metrics"><span>{_esc(quantity)}</span><span>{_esc(metric)}</span></div>
                        <div class="industry-card-foot"><span>产地与指标可见</span><span>查看批次</span></div>
                    </article>
                    """,
                    unsafe_allow_html=True,
                )

    st.markdown('<div class="industry-table-caption">筛选条件 · 品种：沃柑 / 脐橙 / 茶枝柑 · 供应状态：已上传、已核验、待补检测</div>', unsafe_allow_html=True)
    ui_components.render_light_table(
        [
            {"批次": "GX-WG-20260903-01", "供应方": "桂林示例果园", "可供量": "20 吨", "检测": "农残待补", "可见范围": "仅参与匹配"},
            {"批次": "JX-NC-20260902-04", "供应方": "赣南示例合作社", "可供量": "12 吨", "检测": "基础报告已上传", "可见范围": "授权合作方"},
        ],
        "暂无供应批次。",
        height=220,
    )


def _render_demand() -> None:
    request = st.session_state.industry_request
    _section_heading(
        "03 · DEMAND CENTER",
        "需求中心",
        "企业先填写必须条件和偏好条件，匹配结果会解释缺口，不直接替代采购验收。",
    )
    with st.form("industry_demand_form", clear_on_submit=False):
        first = st.columns(3)
        with first[0]:
            buyer = st.text_input("采购企业", value=request["buyer"])
        with first[1]:
            product = st.selectbox("目标产品", ["NFC 果汁", "果皮精油", "陈皮原料", "果胶中间体"], index=0)
        with first[2]:
            quantity = st.text_input("需求量（吨）", value=request["quantity"])
        second = st.columns(3)
        with second[0]:
            brix_min = st.text_input("糖度下限（°Brix）", value=request["brix_min"])
        with second[1]:
            delivery = st.text_input("期望到货日", value=request["delivery"])
        with second[2]:
            must_report = st.checkbox("必须提供检测报告", value=True)
        notes = st.text_area("采购补充", value=request["notes"], height=84)
        submitted = st.form_submit_button("发布需求草稿", width="stretch")
    if submitted:
        if not buyer.strip() or not quantity.strip():
            st.warning("采购企业和需求量是必填项。")
        else:
            st.session_state.industry_request = {
                "buyer": buyer.strip(),
                "product": product,
                "quantity": quantity.strip(),
                "brix_min": brix_min.strip(),
                "delivery": delivery.strip(),
                "notes": notes.strip(),
            }
            st.session_state.industry_request_saved = True
            st.success(f"需求已保存为演示草稿；{('检测报告已设为必须条件' if must_report else '检测报告暂列为偏好条件')}。")

    st.markdown(
        f"""
        <div class="industry-requirement-layout">
            <section class="industry-requirement-main">
                <div class="industry-panel-label">必须条件 · Must have</div>
                <div class="industry-requirement-row"><span>产品</span><strong>{_esc(request['product'])}</strong></div>
                <div class="industry-requirement-row"><span>数量</span><strong>{_esc(request['quantity'])} 吨</strong></div>
                <div class="industry-requirement-row"><span>糖度</span><strong>≥ {_esc(request['brix_min'])} °Brix</strong></div>
                <div class="industry-requirement-row"><span>到货</span><strong>{_esc(request['delivery'])} 前</strong></div>
            </section>
            <section class="industry-requirement-main">
                <div class="industry-panel-label">采购偏好 · Nice to have</div>
                <div class="industry-requirement-row"><span>企业</span><strong>{_esc(request['buyer'])}</strong></div>
                <div class="industry-requirement-row"><span>追溯</span><strong>产地、投入品、批次可回查</strong></div>
                <div class="industry-requirement-row"><span>交接</span><strong>先样品，再确认报价</strong></div>
                <div class="industry-requirement-row"><span>备注</span><strong>{_esc(request['notes'])}</strong></div>
            </section>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_matching() -> None:
    request = st.session_state.industry_request
    _section_heading(
        "04 · MATCH ENGINE",
        "智能匹配",
        "匹配先看硬性条件，再把待补材料和排除原因明示出来。匹配不等于放行。",
    )
    st.markdown(
        f"""
        <div class="industry-match-query">
            <div><span>当前需求</span><strong>{_esc(request['buyer'])} · {_esc(request['product'])} · {_esc(request['quantity'])} 吨</strong></div>
            <div><span>硬性条件</span><strong>糖度 ≥ {_esc(request['brix_min'])} °Brix · { _esc(request['delivery']) } 前到货</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    candidates = [
        ("A", "JX-NC-20260902-04", "赣南示例合作社", "4/4 满足", "可进入对接", "ready", "糖度、数量、交期和基础报告均满足"),
        ("B", "GX-WG-20260903-01", "桂林示例果园", "3/4 满足", "待补材料", "pending", "农残报告尚未上传，暂不建议排产"),
        ("C", "GD-CZ-20260901-02", "新会示例果园", "2/4 满足", "不推荐", "blocked", "数量不足且糖度低于当前需求下限"),
    ]
    for rank, batch_id, supplier, score, state, tone, reason in candidates:
        st.markdown(
            f"""
            <div class="industry-match-row">
                <div class="industry-match-rank">{_esc(rank)}</div>
                <div class="industry-match-main"><strong>{_esc(batch_id)}</strong><span>{_esc(supplier)}</span></div>
                <div class="industry-match-score"><strong>{_esc(score)}</strong><span>{_esc(reason)}</span></div>
                <div>{_status(state, tone)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if st.button("发起 A 批次对接", key="industry_start_connection", width="stretch"):
        st.session_state.industry_connection_requested = True
        st.success("已生成对接草稿；联系人和报价仍需双方授权后补充。")


def _render_connections() -> None:
    _section_heading(
        "05 · CONNECTIONS",
        "对接中心",
        "把匹配结果转成可追踪的合作步骤，默认不展示私人联系方式。",
    )
    state = "已创建对接草稿" if st.session_state.industry_connection_requested else "等待发起对接"
    tone = "ready" if st.session_state.industry_connection_requested else "pending"
    st.markdown(
        f"""
        <div class="industry-connection-layout">
            <section class="industry-connection-card">
                <div class="industry-card-topline"><span>匹配候选 A</span>{_status(state, tone)}</div>
                <h3>赣南示例合作社 · JX-NC-20260902-04</h3>
                <div class="industry-connection-list"><span>下一步</span><strong>双方授权 → 样品测试 → 确认报价</strong></div>
                <div class="industry-connection-list"><span>当前信息</span><strong>批次指标、可供量、报告状态</strong></div>
                <div class="industry-connection-list"><span>未展示</span><strong>手机号、邮箱、合同和最终价格</strong></div>
            </section>
            <section class="industry-connection-card">
                <div class="industry-card-topline"><span>授权检查</span>{_status("需人工确认", "pending")}</div>
                <h3>对接前确认</h3>
            </section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    consent = st.checkbox(
        "我确认本次对接仅使用已授权的企业信息",
        value=bool(st.session_state.industry_consent),
        key="industry_consent_checkbox",
    )
    st.caption("演示版只记录当前会话状态，不会向真实企业发送消息。")
    if st.button("确认授权并进入样品测试", key="industry_consent_button", width="stretch"):
        if not consent:
            st.warning("请先确认本次对接使用已授权的企业信息。")
        else:
            st.session_state.industry_consent = True
            st.session_state.industry_connection_requested = True
            st.success("已进入样品测试待办；正式联系人和报价请由授权人员补充。")


def _render_reports() -> None:
    batch = st.session_state.industry_batch
    _section_heading(
        "06 · REPORT CENTER",
        "报告中心",
        "把批次事实、需求条件、缺口和行动项整理成企业可读的报告草稿。",
    )
    report_type = st.selectbox("报告类型", ["原料适配与整改报告", "企业采购规格确认单", "供应批次信息卡"], key="industry_report_type")
    preview = st.columns([1.15, 1])
    with preview[0]:
        st.markdown(
            f"""
            <section class="industry-report-preview">
                <div class="industry-report-head"><span>A4 · DRAFT</span>{_status("待人工复核", "pending")}</div>
                <h3>{_esc(report_type)}</h3>
                <p>批次：{_esc(batch['batch_id'])} · {_esc(batch['origin'])}{_esc(batch['variety'])} · {_esc(batch['weight'])} 吨</p>
                <hr>
                <h4>一、当前事实</h4>
                <p>已采集产地、品种、重量、糖度、供应方和投入品供应方；农残报告尚未补齐。</p>
                <h4>二、产业需求</h4>
                <p>目标路线为 NFC 果汁，需求方要求批次可追溯，并在到货前完成检测复核。</p>
                <h4>三、后续行动</h4>
                <p>补充检测报告，确认样品测试结果，再由授权人员决定是否进入排产。</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
    with preview[1]:
        st.markdown('<div class="industry-panel-label">报告动作</div>', unsafe_allow_html=True)
        st.write("生成结构化草稿后，可导出给采购、质控或生产评审。")
        if st.button("生成报告草稿", key="industry_generate_report", width="stretch"):
            st.session_state.industry_report_generated = True
            st.success("报告草稿已生成，状态为待人工复核。")
        report_markdown = f"""# {report_type}\n\n- 批次：{batch['batch_id']}\n- 产地：{batch['origin']}\n- 品种：{batch['variety']}\n- 重量：{batch['weight']} 吨\n- 糖度：{batch['brix']} °Brix\n\n## 待补材料\n\n- 农残检测报告\n- 样品测试结果\n- 授权联系人和报价\n\n> 本文件为演示草稿，不替代企业 SOP、实验室检测或生产放行。\n"""
        st.download_button("下载 Markdown 草稿", report_markdown, file_name="citrus-industry-report-draft.md", mime="text/markdown", width="stretch")
        st.caption("报告输出会保留事实、证据缺口和人工确认点，不自动生成合规结论。")


def _render_dashboard() -> None:
    _section_heading(
        "07 · INDUSTRY ANALYTICS",
        "产业链看板",
        "先用演示数据观察供应、需求、匹配和待办的结构，后续再接真实业务统计。",
    )
    st.markdown(
        """
        <div class="industry-dashboard-grid">
            <section class="industry-dashboard-panel">
                <div class="industry-panel-label">供应去向 · 近 30 天</div>
                <div class="industry-bar-row"><span>鲜果</span><i style="--bar:78%"></i><strong>42 吨</strong></div>
                <div class="industry-bar-row"><span>果汁</span><i style="--bar:54%"></i><strong>23 吨</strong></div>
                <div class="industry-bar-row"><span>果皮</span><i style="--bar:38%"></i><strong>16 吨</strong></div>
                <div class="industry-bar-row"><span>副产物</span><i style="--bar:24%"></i><strong>9 吨</strong></div>
            </section>
            <section class="industry-dashboard-panel">
                <div class="industry-panel-label">匹配漏斗 · 演示统计</div>
                <div class="industry-funnel-row"><span>已登记批次</span><strong>24</strong>{_status("100%", "ready")}</div>
                <div class="industry-funnel-row"><span>进入匹配</span><strong>18</strong>{_status("75%", "ready")}</div>
                <div class="industry-funnel-row"><span>待补材料</span><strong>07</strong>{_status("需补齐", "pending")}</div>
                <div class="industry-funnel-row"><span>完成对接</span><strong>05</strong>{_status("人工确认", "neutral")}</div>
            </section>
        </div>
        <div class="industry-dashboard-note">数据看板中的数量是演示样本，仅用于展示产品交互结构。</div>
        """,
        unsafe_allow_html=True,
    )


def render_industry_workspace() -> None:
    """Render the additive business layer inside the existing Workspace page."""
    _init_state()
    _render_overview()
    tabs = st.tabs(["批次采集", "供应中心", "需求中心", "智能匹配", "对接中心", "报告中心", "产业链看板"])
    with tabs[0]:
        _render_batch_intake()
    with tabs[1]:
        _render_supply()
    with tabs[2]:
        _render_demand()
    with tabs[3]:
        _render_matching()
    with tabs[4]:
        _render_connections()
    with tabs[5]:
        _render_reports()
    with tabs[6]:
        _render_dashboard()


__all__ = ["render_industry_workspace"]
