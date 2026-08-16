from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "app" / "ui" / "design_system.css"
COMPONENTS_PATH = ROOT / "app" / "ui" / "components.py"
MAIN_PATH = ROOT / "app" / "main.py"
CONFIG_PATH = ROOT / ".streamlit" / "config.toml"
ROBOTO_PATH = ROOT / "app" / "static" / "fonts" / "RobotoVariable-Latin.woff2"


class DesignSystemRegressionTests(unittest.TestCase):
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
            '--font-ui: "CitrusRoboto", "MiSans VF", "CitrusNotoSansSC", sans-serif;',
            css,
        )
        self.assertIn("cdn-font.hyperos.mi.com", css)
        self.assertIn('family = "CitrusRoboto"', config)
        self.assertIn(
            'font = "CitrusRoboto, MiSans VF, CitrusNotoSansSC, sans-serif"',
            config,
        )
        self.assertTrue(ROBOTO_PATH.is_file())
        self.assertGreater(ROBOTO_PATH.stat().st_size, 40_000)
        self.assertIn("--weight-regular: 330;", css)
        self.assertIn("--weight-medium: 450;", css)
        self.assertIn("--weight-semibold: 520;", css)
        self.assertIn("baseFontWeight = 330", config)
        self.assertNotIn('"PingFang SC"', css)

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
            'st.chat_input("输入问题或粘贴批次信息…\\nAsk or paste batch data…")',
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
