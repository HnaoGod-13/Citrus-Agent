from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "app" / "ui" / "design_system.css"
COMPONENTS_PATH = ROOT / "app" / "ui" / "components.py"


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


if __name__ == "__main__":
    unittest.main()
