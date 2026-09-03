from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_every_industry_route_registers_in_a_fresh_runtime():
    for route in ('production', 'supply', 'demand', 'match'):
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


def test_reference_photos_are_bundled_for_cloud_static_serving():
    asset = Path(__file__).parents[1] / 'app/static/industry/supply-reference.png'
    assert asset.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
