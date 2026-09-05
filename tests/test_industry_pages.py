from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_every_industry_route_registers_in_a_fresh_runtime():
    for route in ('data', 'production', 'supply', 'demand', 'match', 'visuals', 'reports'):
        app = AppTest.from_string(f'''
import streamlit as st
from app.ui import industry_pages
st.query_params['industry'] = {route!r}
industry_pages.render_industry_workspace()
''', default_timeout=30).run()
        assert not app.exception
        assert app.session_state['industry_workspace_view'] == route


def test_sidebar_alignment_rules_cover_button_and_nested_label():
    css = (Path(__file__).parents[1] / 'app/ui/design_system.css').read_text(encoding='utf-8')
    start = css.index('[class*="st-key-workspace_industry_nav"] [data-testid="stButton"] > button {')
    rule = css[start:css.index('}', start)]
    assert 'justify-content: flex-start !important' in rule
    assert 'text-align: left !important' in rule
    assert '[class*="st-key-workspace_industry_nav"] [data-testid="stMarkdownContainer"]' in css


def test_current_industry_navigation_button_keeps_the_active_background():
    css = (Path(__file__).parents[1] / 'app/ui/design_system.css').read_text(encoding='utf-8')
    selector = (
        '[class*="st-key-workspace_industry_nav"] [data-testid="stButton"] '
        '> button[data-testid="stBaseButton-primary"] {'
    )
    start = css.index(selector)
    rule = css[start:css.index('}', start)]
    assert 'background: var(--active) !important' in rule


def test_reference_photos_are_bundled_for_cloud_static_serving():
    asset = Path(__file__).parents[1] / 'app/static/industry/supply-reference.png'
    assert asset.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')


def test_industry_navigation_contains_the_meeting_modules_without_ai_guidance_copy():
    root = Path(__file__).parents[1]
    main = (root / 'app/main.py').read_text(encoding='utf-8')
    workspace = (root / 'app/ui/industry_workspace/workspace.js').read_text(encoding='utf-8')
    for label in ('产业数据采集', '商业对接', '产业可视化', '报告中心'):
        assert label in main
    assert 'AI引导' not in main + workspace
    assert '设计示例 · 演示数据' not in workspace
    for standard in ('GB 14881—2013', 'GB 2760—2024', 'GB 2762—2025', 'GB 2763—2021'):
        assert standard in workspace


def test_industry_navigation_callback_accepts_every_visible_workspace_route():
    source = (Path(__file__).parents[1] / 'app/main.py').read_text(encoding='utf-8')
    callback = source.split('def select_industry_view', 1)[1].split(
        'def toggle_mobile_secondary_panel', 1
    )[0]
    for route in ('data', 'production', 'supply', 'demand', 'match', 'visuals', 'reports'):
        assert f'"{route}"' in callback
    assert 'st.session_state.mobile_secondary_open = False' in callback
