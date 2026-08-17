import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "app" / "ui" / "design_system.css"
COMPONENTS_PATH = ROOT / "app" / "ui" / "components.py"
MAIN_PATH = ROOT / "app" / "main.py"
CONFIG_PATH = ROOT / ".streamlit" / "config.toml"
MISANS_SEMIBOLD_PATH = ROOT / "app" / "static" / "fonts" / "MiSans-Semibold.ttf"
MISANS_SEMIBOLD_SHA256 = (
    "77c23f31ae124867778344970155a0c8d34a89897dedaab81aeee82ff00a4ce6"
)


class DesignSystemRegressionTests(unittest.TestCase):
    def test_desktop_brand_wordmark_has_balanced_scale_and_hit_area(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        brand_start = css.index(".primary-brand {")
        brand_rule = css[brand_start : css.index("}", brand_start) + 1]
        mark_start = css.index(".primary-brand-mark svg {")
        mark_rule = css[mark_start : css.index("}", mark_start) + 1]
        word_start = css.index(".primary-brand-word {")
        word_rule = css[word_start : css.index("}", word_start) + 1]
        action_start = css.index('[class*="st-key-product_brand_action"] {')
        action_rule = css[action_start : css.index("}", action_start) + 1]

        self.assertIn("height: 52px;", brand_rule)
        self.assertIn("gap: 10px;", brand_rule)
        self.assertIn("width: 30px;", mark_rule)
        self.assertIn("height: 30px;", mark_rule)
        self.assertIn("font-size: 15px;", word_rule)
        self.assertIn("line-height: 20px;", word_rule)
        self.assertIn("letter-spacing: 0;", word_rule)
        self.assertIn("width: calc(var(--primary-rail-width) - 31px);", action_rule)
        self.assertIn("height: 52px;", action_rule)

    def test_mobile_navigation_uses_a_real_five_column_button_grid(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        mobile_start = css.index("@media (max-width: 899px) {")
        mobile_css = css[mobile_start : css.index("@media (max-width: 699px) {", mobile_start)]
        action_start = mobile_css.index('[class*="st-key-product_nav_actions"] {')
        action_rule = mobile_css[action_start : mobile_css.index("}", action_start) + 1]

        self.assertIn(
            "grid-template-columns: repeat(5, minmax(0, 1fr)) !important;",
            action_rule,
        )
        self.assertIn(
            '[class*="st-key-product_nav_actions"] > [data-testid="stVerticalBlock"]',
            mobile_css,
        )
        self.assertIn(
            "grid-template-columns: repeat(5, minmax(0, 1fr)) !important;",
            mobile_css,
        )
        self.assertIn("gap: 0 !important;", mobile_css)

    def test_workspace_mobile_rows_are_stacked_and_page_scroll_is_not_nested(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        self.assertIn(".data-table-shell.workspace-table {", css)
        self.assertIn("max-height: none;", css)
        self.assertIn("content: attr(data-label);", css)
        self.assertIn("grid-template-columns: 82px minmax(0, 1fr);", css)

    def test_long_markdown_cannot_expand_the_whole_chat_page(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        self.assertIn(
            'section[data-testid="stAppScrollToBottomContainer"] {\n'
            "    overflow-x: hidden !important;",
            css,
        )
        self.assertIn("overflow-wrap: anywhere;", css)
        self.assertIn("word-break: break-word;", css)

    def test_keyboard_focus_and_active_navigation_labels_remain_visible(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        components = COMPONENTS_PATH.read_text(encoding="utf-8-sig")
        focus_start = css.index(
            '[class*="st-key-product_brand_action"] button:focus-visible'
        )
        focus_rule = css[focus_start : css.index("}", focus_start) + 1]

        self.assertIn("outline: 2px solid var(--text-primary) !important;", focus_rule)
        self.assertIn("当前页面：", components)

    def test_font_stack_is_bundled_and_cross_platform(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        config = CONFIG_PATH.read_text(encoding="utf-8-sig")
        self.assertIn(
            '--font-ui: "CitrusMiSansSemibold", "MiSans Semibold", sans-serif;',
            css,
        )
        self.assertIn(
            '--font-mono: "CitrusMiSansSemibold", "MiSans Semibold", sans-serif;',
            css,
        )
        self.assertIn('family = "CitrusMiSansSemibold"', config)
        self.assertIn('url = "app/static/fonts/MiSans-Semibold.ttf"', config)
        self.assertIn('weight = "520"', config)
        self.assertIn(
            'font = "CitrusMiSansSemibold, sans-serif"',
            config,
        )
        self.assertIn('headingFont = "CitrusMiSansSemibold, sans-serif"', config)
        self.assertIn('codeFont = "CitrusMiSansSemibold, sans-serif"', config)
        self.assertTrue(MISANS_SEMIBOLD_PATH.is_file())
        self.assertGreater(MISANS_SEMIBOLD_PATH.stat().st_size, 8_000_000)
        self.assertEqual(
            hashlib.sha256(MISANS_SEMIBOLD_PATH.read_bytes()).hexdigest(),
            MISANS_SEMIBOLD_SHA256,
        )
        self.assertIn("--weight-regular: 520;", css)
        self.assertIn("--weight-medium: 520;", css)
        self.assertIn("--weight-semibold: 520;", css)
        self.assertIn("baseFontWeight = 500", config)
        self.assertIn("headingFontWeights = 500", config)
        self.assertIn("codeFontWeight = 500", config)
        self.assertIn("metricValueFontWeight = 500", config)
        self.assertNotIn("cdn-font.hyperos.mi.com", css)
        self.assertNotIn("CitrusRoboto", config)
        self.assertNotIn("MiSans VF", config)
        self.assertNotIn('"PingFang SC"', css)

    def test_all_visible_text_surfaces_use_misans_semibold(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")

        for selector in (
            '[data-testid="stMarkdownContainer"]',
            '[data-testid="stChatMessage"]',
            '[data-testid="stChatInput"]',
            '[data-testid="stDataFrame"]',
            '[data-testid="stAlert"]',
            '[data-testid="stToast"]',
            '[data-testid="stMetric"]',
            '[data-testid="stExpander"]',
            '[data-testid="stTabs"]',
            '[data-baseweb]',
            '[role="listbox"]',
            '[role="option"]',
            '[role="dialog"]',
            '[role="tooltip"]',
            ".analysis-shell :where(",
            "input::placeholder",
            "textarea::placeholder",
        ):
            self.assertIn(selector, css)

        self.assertIn("font-family: var(--font-ui) !important;", css)
        self.assertIn("font-weight: var(--weight-regular) !important;", css)
        self.assertNotIn("SFMono-Regular", css)
        self.assertNotIn("Consolas", css)

    def test_report_draft_has_scoped_document_typography_and_rule_spacing(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        scope = (
            ':is(.analysis-shell, [class*="st-key-analysis_shell_"])\n'
            '    div[data-testid="stExpander"]:has(.report-anchor)'
        )
        report_start = css.index("/* Report draft typography")
        report_end = css.index('div[data-testid="stDataFrame"] {', report_start)
        report_css = css[report_start:report_end]

        self.assertIn(scope, report_css)
        self.assertIn("--report-body-size: 14px;", report_css)
        self.assertIn("--report-body-leading: 1.72;", report_css)
        self.assertIn(
            '[data-testid="stElementContainer"]:has(.report-anchor) {\n'
            "    display: none !important;",
            report_css,
        )
        for selector, size, line_height in (
            ('[data-testid="stMarkdownContainer"] h1 {', "22px", "1.35"),
            ('[data-testid="stMarkdownContainer"] h2 {', "18px", "1.45"),
            ('[data-testid="stMarkdownContainer"] h3 {', "15px", "1.5"),
            ('[data-testid="stMarkdownContainer"] h4 {', "14px", "1.55"),
        ):
            start = report_css.index(selector)
            rule = report_css[start : report_css.index("}", start) + 1]
            self.assertIn(f"font-size: {size} !important;", rule)
            self.assertIn(f"line-height: {line_height} !important;", rule)

        h2_start = report_css.index('[data-testid="stMarkdownContainer"] h2 {')
        h2_rule = report_css[h2_start : report_css.index("}", h2_start) + 1]
        self.assertIn("margin: 24px 0 10px !important;", h2_rule)
        self.assertIn("padding: 16px 0 0 !important;", h2_rule)
        self.assertIn("border-top: 1px solid var(--border) !important;", h2_rule)

        hr_start = report_css.index('[data-testid="stMarkdownContainer"] hr {')
        hr_rule = report_css[hr_start : report_css.index("}", hr_start) + 1]
        self.assertIn("margin: 24px 0 !important;", hr_rule)
        self.assertIn('[data-testid="stMarkdownContainer"] hr + h2 {', report_css)

        analysis_start = css.index(".analysis-shell .stMarkdown,")
        analysis_end = css.index(
            '[data-testid="stMarkdownContainer"] h1,',
            analysis_start,
        )
        ordinary_analysis_rule = css[analysis_start:analysis_end]
        self.assertIn("font-size: 15px;", ordinary_analysis_rule)

    def test_desktop_main_content_is_not_double_offset_when_sidebar_is_open(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        selector = (
            'body:has([data-testid="stSidebar"][aria-expanded="false"]) '
            '[data-testid="stMain"] {'
        )
        start = css.index(selector)
        rule = css[start : css.index("}", start) + 1]

        self.assertIn("margin-left: 0 !important;", rule)
        self.assertNotIn("secondary-panel-width", rule)
        self.assertIn("--main-pad-start: 36px;", css)
        self.assertIn("--main-pad-end: 36px;", css)

    def test_bilingual_product_headers_keep_close_readable_secondary_copy(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        selector = ".product-page-header .product-page-subtitle-en {"
        start = css.index(selector)
        rule = css[start : css.index("}", start) + 1]

        self.assertIn("margin-top: 2px;", rule)
        self.assertIn("--text-tertiary: #727272;", css)

    def test_desktop_navigation_hit_area_matches_visual_rows(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        visual_start = css.index(".primary-nav-item {")
        visual_rule = css[visual_start : css.index("}", visual_start) + 1]
        hit_start = css.index(
            '[class*="st-key-product_nav_actions"] [data-testid="stButton"] {'
        )
        hit_rule = css[hit_start : css.index("}", hit_start) + 1]

        self.assertIn("min-height: 62px;", visual_rule)
        self.assertIn("height: 62px;", hit_rule)
        self.assertIn(
            '[class*="st-key-product_nav_actions"] [data-testid="stButton"] > button {',
            css,
        )
        self.assertIn("position: absolute !important;", css)

    def test_compact_desktop_stacks_task_cards_before_they_overflow(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        compact_start = css.index("@media (min-width: 900px) and (max-width: 1099px) {")
        compact_css = css[compact_start : css.index("@media (max-width: 899px) {", compact_start)]
        self.assertIn("flex-direction: column;", compact_css)
        self.assertIn("width: 100% !important;", compact_css)

    def test_mobile_panel_icon_is_not_drawn_twice(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        mobile_start = css.index("@media (max-width: 899px) {")
        mobile_css = css[mobile_start : css.index("@media (max-width: 699px) {", mobile_start)]
        self.assertIn("background-image: url(", mobile_css)
        self.assertNotIn(
            '[class*="st-key-mobile_panel_toggle"] button::before',
            mobile_css,
        )

    def test_chat_composer_keeps_bilingual_placeholder(self) -> None:
        main_source = MAIN_PATH.read_text(encoding="utf-8-sig")
        self.assertIn(
            'typed_prompt = st.chat_input(\n'
            '        "输入问题或粘贴批次信息…\\nAsk or paste batch data…",\n'
            '        disabled=active_job is not None,\n'
            '    )',
            main_source,
        )

    def test_sidebar_controls_share_a_deliberate_type_scale(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        main_source = MAIN_PATH.read_text(encoding="utf-8-sig")

        self.assertIn('font-size: 14px !important;', css)
        self.assertIn(
            '[data-testid="stSidebar"] [data-testid="stTextAreaRootElement"] textarea:placeholder-shown',
            css,
        )
        self.assertIn('padding-top: 29px !important;', css)
        self.assertIn('content: "JPG / PNG / TIFF · max 200MB";', css)
        self.assertIn('button[data-testid^="stBaseButton-"]', css)
        self.assertIn('[data-testid="stWidgetLabel"] p {', css)
        self.assertIn('flex: 0 0 18px;', css)
        self.assertIn('"新建对话\\nNew Chat"', main_source)
        self.assertNotIn('"＋ 新建对话"', main_source)
        self.assertIn('"如：果皮完整、无霉斑腐烂。\\n"', main_source)

    def test_mobile_sidebar_preserves_readable_control_width(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8-sig")
        mobile_start = css.index("@media (max-width: 899px) {")
        mobile_css = css[mobile_start : css.index("@media (max-width: 699px) {", mobile_start)]

        self.assertIn("--secondary-panel-width: min(344px, 92vw);", mobile_css)
        self.assertIn("padding: 72px 24px 28px !important;", mobile_css)


if __name__ == "__main__":
    unittest.main()
