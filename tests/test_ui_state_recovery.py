from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from app import main as app_main


class SessionStateStub(dict):
    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


def make_row(
    message_id: str,
    role: str,
    content: str,
    *,
    message_type: str = "chat",
    metadata: dict | None = None,
) -> dict:
    return {
        "message_id": message_id,
        "role": role,
        "content": content,
        "message_type": message_type,
        "metadata": metadata or {},
    }


def raw_model_output_keys(value: object) -> list[str]:
    """Collect the canonical raw vision-output key at every nesting level."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) == "_raw_model_output":
                found.append(str(key))
            found.extend(raw_model_output_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(raw_model_output_keys(item))
    return found


class ScrollPositionManagerTests(unittest.TestCase):
    def test_parent_realm_manager_yields_to_user_scroll_and_cleans_up_listeners(self) -> None:
        with patch.object(app_main.st, "iframe") as iframe:
            app_main.render_scroll_position_manager(restore=True, command_id=7)

        iframe.assert_called_once()
        bootstrap = iframe.call_args.args[0]
        installer = app_main.SCROLL_POSITION_MANAGER_INSTALLER
        self.assertEqual({"height": 1, "tab_index": -1}, iframe.call_args.kwargs)
        self.assertIn('loader = doc.createElement("script")', bootstrap)
        self.assertIn("(doc.head || doc.documentElement).appendChild(loader);", bootstrap)
        self.assertIn("restore: true", bootstrap)
        self.assertIn("resetToTop: false", bootstrap)
        self.assertIn("const commandId = 7;", bootstrap)
        self.assertIn("commandId,", bootstrap)

        self.assertIn("version: 7", installer)
        self.assertIn("window[installerKey] = install;", installer)
        self.assertIn(
            "savedPosition = Number(window.sessionStorage.getItem(storageKey));",
            installer,
        )
        handle_user_input = installer[
            installer.index("manager.handleUserInput =") : installer.index(
                "manager.handlePointerDown ="
            )
        ]
        self.assertLess(
            handle_user_input.index("manager.cancelMotion();"),
            handle_user_input.index("manager.userScrollUntil"),
        )
        for event_name, handler_name in (
            ("wheel", "handleUserInput"),
            ("touchmove", "handleUserInput"),
            ("pointerdown", "handlePointerDown"),
            ("keydown", "handleKeyDown"),
        ):
            self.assertIn(
                f'doc.removeEventListener("{event_name}", manager.{handler_name}',
                installer,
            )
            self.assertIn(
                f'doc.addEventListener("{event_name}", manager.{handler_name}',
                installer,
            )
        self.assertIn(
            'scroller.addEventListener("scroll", manager.handleScroll',
            installer,
        )
        self.assertIn('target.closest(".citrus-primary-rail")', installer)
        self.assertIn('target.closest(\'[data-testid="stSidebar"]\')', installer)
        self.assertIn("event.clientX <= primaryRailWidth", installer)
        self.assertIn("if (canMoveDown || canMoveUp) return;", installer)
        self.assertIn(
            'doc.addEventListener("wheel", manager.handleRailWheel, { capture: true, passive: false });',
            installer,
        )
        self.assertLess(
            installer.index("resetTop();"),
            installer.index("manager.scheduleMotion(resetTop"),
        )

    def test_clicks_do_not_turn_programmatic_jumps_into_saved_user_scroll(self) -> None:
        installer = app_main.SCROLL_POSITION_MANAGER_INSTALLER
        pointer_handler = installer[
            installer.index("manager.handlePointerDown =") : installer.index(
                "manager.handleKeyDown ="
            )
        ]

        self.assertIn("manager.cancelMotion();", pointer_handler)
        self.assertIn("manager.userScrollUntil = 0;", pointer_handler)
        self.assertIn("manager.remember();", pointer_handler)
        self.assertNotIn("manager.handleUserInput(event);", pointer_handler)
        self.assertIn(
            "const preserveTarget = target.closest(",
            pointer_handler,
        )
        self.assertIn('[data-testid="stExpander"] summary', pointer_handler)
        self.assertIn('[data-testid="stChatInput"]', pointer_handler)
        self.assertIn("if (!preserveTarget) return;", pointer_handler)
        self.assertIn(
            "manager.preservePosition(manager.scroller.scrollTop);",
            pointer_handler,
        )

    def test_expander_position_guard_is_short_and_user_cancelable(self) -> None:
        installer = app_main.SCROLL_POSITION_MANAGER_INSTALLER
        preserve = installer[
            installer.index("manager.preservePosition = (") : installer.index(
                "manager.handleUserInput ="
            )
        ]

        self.assertIn("delays = [0, 40, 120, 280]", preserve)
        self.assertIn("releaseDelay = 360", preserve)
        self.assertIn("manager.scheduleMotion(", preserve)
        self.assertIn("manager.remember", preserve)
        self.assertIn(
            'doc.addEventListener("touchmove", manager.handleUserInput',
            installer,
        )
        self.assertNotIn(
            'doc.addEventListener("touchstart", manager.handleUserInput',
            installer,
        )

    def test_both_scroll_bootstraps_share_the_current_manager_version(self) -> None:
        with (
            patch.object(app_main.st, "iframe") as iframe,
        ):
            app_main.render_scroll_position_manager(restore=False)
            scroll_bootstrap = iframe.call_args.args[0]
            iframe.reset_mock()
            app_main.render_progress_reveal("progress-version-check")
            progress_bootstrap = iframe.call_args.args[0]

        self.assertIn("version !== 7", scroll_bootstrap)
        self.assertIn("version !== 7", progress_bootstrap)
        self.assertNotIn("version !== 4", progress_bootstrap)

    def test_empty_state_reruns_do_not_force_scroll_reset(self) -> None:
        source = Path(app_main.__file__).read_text(encoding="utf-8-sig")
        main_source = source[source.index("def main()") :]

        self.assertIn("reset_to_top=reset_scroll_position,", main_source)
        self.assertNotIn(
            "reset_scroll_position or not bool(st.session_state.agent_messages)",
            main_source,
        )
        start_new = source[
            source.index("def start_new_conversation") : source.index("def init_state")
        ]
        self.assertIn("st.session_state.reset_main_scroll_position = True", start_new)

    def test_progress_reveal_uses_composer_boundary_and_short_cancelable_motion(self) -> None:
        installer = app_main.SCROLL_POSITION_MANAGER_INSTALLER
        reveal = installer[
            installer.index("manager.revealOnce = (revealId, selector) => {") : installer.index(
                "return manager;"
            )
        ]

        self.assertIn("manager.lastRevealId === marker", reveal)
        self.assertIn("manager.lastRevealId = marker", reveal)
        self.assertIn("doc.querySelector('[data-testid=\"stBottom\"]')", reveal)
        self.assertIn("const bottomBoundary = Math.min(scrollerRect.bottom, composerTop) - 16;", reveal)
        self.assertIn(
            "manager.scheduleMotion(reveal, [0, 40, 120], 180, manager.remember);",
            reveal,
        )

    def test_progress_reveal_bootstraps_parent_manager(self) -> None:
        with patch.object(app_main.st, "iframe") as iframe:
            app_main.render_progress_reveal("msg_layout_reveal")

        iframe.assert_called_once()
        bootstrap = iframe.call_args.args[0]
        self.assertEqual({"height": 1, "tab_index": -1}, iframe.call_args.kwargs)
        self.assertIn('install({ restore: false, resetToTop: false });', bootstrap)
        self.assertIn('manager.revealOnce("msg_layout_reveal"', bootstrap)
        self.assertIn(json.dumps(app_main.AGENT_PROGRESS_SELECTOR), bootstrap)


class EmptyStateProgressLayoutTests(unittest.TestCase):
    def test_loading_slot_follows_the_complete_example_grid(self) -> None:
        source = Path(app_main.__file__).read_text(encoding="utf-8-sig")
        empty_state = source[
            source.index("def render_empty_state") : source.index("def render_agent_progress")
        ]

        self.assertEqual(4, len(app_main.EXAMPLE_CARDS))
        self.assertLess(
            empty_state.index('key=f"example_card_{card_index}"'),
            empty_state.index('with st.container(key="agent_progress_host")'),
        )
        self.assertIn(
            '\n        with st.container(key="agent_progress_host"):\n'
            "            progress_slot = st.empty()\n"
            "    return selected_prompt, progress_slot",
            empty_state,
        )

    def test_loading_status_matches_grid_and_expands_the_scroll_area(self) -> None:
        stylesheet = Path(app_main.__file__).with_name("ui").joinpath("design_system.css")
        css = stylesheet.read_text(encoding="utf-8-sig")

        grid_start = css.index(
            '[class*="st-key-welcome_content"] div[data-testid="stHorizontalBlock"] {'
        )
        grid_rule = css[grid_start : css.index("}", grid_start) + 1]
        host_start = css.index('[class*="st-key-agent_progress_host"] {')
        host_rule = css[host_start : css.index("}", host_start) + 1]
        progress_start = css.index(".agent-live-progress {")
        progress_rule = css[progress_start : css.index("}", progress_start) + 1]
        expansion_start = css.index(
            '.block-container:has(\n    [class*="st-key-agent_progress_host"] .agent-live-progress'
        )
        expansion_rule = css[expansion_start : css.index("}", expansion_start) + 1]

        expected_width = "width: min(var(--task-grid-max), 100%);"
        self.assertIn(expected_width, grid_rule)
        self.assertIn("margin: 0 auto;", grid_rule)
        self.assertIn(expected_width, host_rule)
        self.assertIn("margin-inline: auto;", host_rule)
        self.assertIn("overflow-anchor: none;", host_rule)
        self.assertIn("width: 100%;", progress_rule)
        self.assertIn("margin: 16px 0 24px;", progress_rule)
        self.assertIn("flex: 0 0 auto !important;", expansion_rule)

    def test_loading_spinner_keeps_rotating_with_reduced_motion_enabled(self) -> None:
        stylesheet = Path(app_main.__file__).with_name("ui").joinpath("design_system.css")
        css = stylesheet.read_text(encoding="utf-8-sig")

        spinner_start = css.index(".agent-live-spinner {")
        spinner_rule = css[spinner_start : css.index("}", spinner_start) + 1]
        self.assertIn("animation: citrus-spin 800ms linear infinite;", spinner_rule)
        self.assertIn("will-change: transform;", spinner_rule)

        reduced_motion_start = css.rindex("@media (prefers-reduced-motion: reduce) {")
        reduced_motion_rule = css[reduced_motion_start:]
        global_reduction = "animation-iteration-count: 1 !important;"
        spinner_override = ".agent-live-spinner {"
        infinite_animation = "animation: citrus-spin 800ms linear infinite !important;"
        self.assertIn(global_reduction, reduced_motion_rule)
        self.assertIn(infinite_animation, reduced_motion_rule)
        self.assertLess(
            reduced_motion_rule.index(global_reduction),
            reduced_motion_rule.index(spinner_override),
        )

    def test_background_progress_reveals_once_without_rendering_from_worker(self) -> None:
        source = Path(app_main.__file__).read_text(encoding="utf-8-sig")
        monitor = source[
            source.index("def render_agent_job_monitor") : source.index("def handle_prompt")
        ]
        worker = source[
            source.index("def _execute_agent_job") : source.index("def _active_agent_job_snapshot")
        ]

        self.assertIn("active_agent_progress_revealed", monitor)
        self.assertIn("reveal_id = snapshot.job_id", monitor)
        self.assertEqual(1, monitor.count("render_agent_progress("))
        self.assertNotIn("render_agent_progress(", worker)
        self.assertNotIn("st.session_state", worker)


class DeepRetrievalUiStateTests(unittest.TestCase):
    def test_sidebar_uses_persistent_required_segmented_control(self) -> None:
        source = Path(app_main.__file__).read_text(encoding="utf-8-sig")
        sidebar = source[source.index("def render_sidebar") : source.index("def render_tool_steps")]

        self.assertIn('key="retrieval_mode"', sidebar)
        self.assertIn('persist_state="session"', sidebar)
        self.assertIn("required=True", sidebar)
        self.assertIn("disabled=bool(st.session_state.get(\"active_agent_job_id\"))", sidebar)
        self.assertIn("全库深度检索", app_main.RETRIEVAL_MODE_LABELS.values())

    def test_deep_progress_uses_frozen_mode_label(self) -> None:
        slot = SimpleNamespace(markdown=Mock())

        app_main.render_agent_progress(
            slot,
            "正在扫描全库文献",
            retrieval_mode="deep",
        )

        rendered = slot.markdown.call_args.args[0]
        self.assertIn("正在扫描全库文献", rendered)
        self.assertIn("全库深度检索", rendered)
        self.assertIn("agent-live-subtitle is-deep", rendered)

    def test_deep_statistics_render_scan_and_adoption_counts(self) -> None:
        with patch.object(app_main.st, "markdown") as markdown:
            app_main.render_deep_retrieval_stats(
                {
                    "retrieval_mode": "deep",
                    "library_document_count": 17300,
                    "library_chunk_count": 365119,
                    "library_usable_document_count": 9285,
                    "library_ocr_document_count": 8015,
                    "fts_rows_returned": 1080,
                    "selected_document_count": 18,
                    "selected_count": 24,
                    "ocr_filtered_count": 5,
                    "adjacent_added_count": 7,
                }
            )

        rendered = markdown.call_args.args[0]
        self.assertIn("全库范围", rendered)
        self.assertIn("17,300", rendered)
        self.assertIn("365,119", rendered)
        self.assertIn("FTS 返回次数", rendered)
        self.assertIn("1,080", rendered)
        self.assertNotIn("候选片段", rendered)
        self.assertIn("采用文献", rendered)
        self.assertIn("18", rendered)
        self.assertIn("采用证据", rendered)
        self.assertIn("24", rendered)
        self.assertIn("正文可用文献", rendered)
        self.assertIn("库内待 OCR", rendered)
        self.assertIn("本轮排除题录", rendered)
        self.assertIn("相邻补充", rendered)

    def test_legacy_row_count_uses_accurate_fts_label(self) -> None:
        with patch.object(app_main.st, "markdown") as markdown:
            app_main.render_deep_retrieval_stats(
                {
                    "retrieval_mode": "deep",
                    "database_rows_scanned": 81,
                }
            )

        rendered = markdown.call_args.args[0]
        self.assertIn("FTS 返回次数", rendered)
        self.assertIn("81", rendered)
        self.assertNotIn("候选片段", rendered)

    def test_unavailable_index_and_partial_completion_are_explicit(self) -> None:
        with patch.object(app_main.st, "markdown") as markdown:
            app_main.render_deep_retrieval_stats(
                {
                    "retrieval_mode": "deep",
                    "database_available": False,
                    "retrieval_complete": False,
                    "retrieval_error": "索引加载失败",
                }
            )
        unavailable = markdown.call_args.args[0]
        self.assertIn("全库索引不可用", unavailable)
        self.assertIn("索引加载失败", unavailable)
        self.assertIn("deep-retrieval-status is-error", unavailable)

        with patch.object(app_main.st, "markdown") as markdown:
            app_main.render_deep_retrieval_stats(
                {
                    "retrieval_mode": "deep",
                    "database_available": True,
                    "retrieval_complete": False,
                    "timed_out": True,
                    "attempted_subquery_count": 7,
                    "subquery_count": 12,
                    "retrieval_error": "超过总时限",
                }
            )
        partial = markdown.call_args.args[0]
        self.assertIn("部分完成 7/12", partial)
        self.assertIn("超过总时限", partial)
        self.assertIn("deep-retrieval-status is-warning", partial)

    def test_adjacent_evidence_and_parameter_source_locations_are_traceable(self) -> None:
        with patch.object(app_main.st, "markdown") as markdown:
            app_main.render_adjacent_evidence(
                [
                    {
                        "section": "材料与方法",
                        "page_start": 7,
                        "chunk_id": "doc-1:chunk-8",
                        "chunk_text": "温度 < 60 °C，时间 30 min。",
                    }
                ]
            )

        rendered = markdown.call_args.args[0]
        self.assertIn("相邻方法/结果证据", rendered)
        self.assertIn("材料与方法", rendered)
        self.assertIn("page_start: 7", rendered)
        self.assertIn("doc-1:chunk-8", rendered)
        self.assertIn("温度 &lt; 60 °C", rendered)
        self.assertEqual(
            "paper-1；片段 chunk-8；第7页",
            app_main.parameter_source_location(
                {
                    "source_refs": ["paper-1；片段 chunk-8；第7页"],
                    "source_ids": ["paper-1"],
                }
            ),
        )
        self.assertEqual(
            "paper-2",
            app_main.parameter_source_location({"source_ids": ["paper-2"]}),
        )
        analysis_source = Path(app_main.__file__).read_text(encoding="utf-8-sig")
        self.assertIn('render_adjacent_evidence(item.get("adjacent_chunks"))', analysis_source)
        self.assertIn('"来源定位": parameter_source_location(item)', analysis_source)

    def test_quick_statistics_remain_hidden(self) -> None:
        with patch.object(app_main.st, "markdown") as markdown:
            app_main.render_deep_retrieval_stats(
                {
                    "retrieval_mode": "quick",
                    "database_rows_scanned": 10,
                    "selected_count": 2,
                }
            )

        markdown.assert_not_called()

    def test_statistics_survive_analysis_and_general_message_persistence(self) -> None:
        stats = {
            "retrieval_mode": "deep",
            "database_rows_scanned": 120,
            "selected_count": 8,
        }
        persisted = app_main.build_persisted_analysis_payload(
            {
                "result": {"report": "# report", "deep_retrieval_stats": stats},
                "report_path": "output/report.md",
            }
        )
        restored = app_main.restore_ui_messages(
            [
                {
                    "message_id": "assistant-deep",
                    "role": "assistant",
                    "content": "answer",
                    "message_type": "chat",
                    "metadata": {"deep_retrieval_stats": stats},
                }
            ]
        )

        self.assertEqual(stats, persisted["deep_retrieval_stats"])
        self.assertEqual(stats, persisted["result"]["deep_retrieval_stats"])
        self.assertEqual(stats, restored[0]["deep_retrieval_stats"])

    def test_general_evidence_survives_message_persistence(self) -> None:
        evidence = [
            {
                "title": "Citrus processing evidence",
                "year": 2026,
                "page": 8,
                "chunk_text": "Evidence excerpt",
            }
        ]
        restored = app_main.restore_ui_messages(
            [
                {
                    "message_id": "assistant-evidence",
                    "role": "assistant",
                    "content": "简明回答",
                    "message_type": "chat",
                    "metadata": {"evidence": evidence},
                }
            ]
        )

        self.assertEqual(evidence, restored[0]["evidence"])


class ProductRouteStateTests(unittest.TestCase):
    def test_query_view_overrides_stale_session_view(self) -> None:
        state = SessionStateStub(
            product_view="workspace",
            mobile_secondary_open=True,
        )
        with (
            patch.object(app_main.st, "session_state", state),
            patch.object(app_main, "_query_value", return_value="knowledge"),
            patch.object(app_main, "_set_query_value") as set_query,
            patch.object(app_main, "preserve_sidebar_draft") as preserve_draft,
        ):
            view = app_main.current_product_view()

        self.assertEqual("knowledge", view)
        self.assertEqual("knowledge", state.product_view)
        self.assertFalse(state.mobile_secondary_open)
        self.assertTrue(state.reset_main_scroll_position)
        preserve_draft.assert_called_once_with()
        set_query.assert_not_called()

    def test_query_sid_switch_restores_only_the_target_conversation(self) -> None:
        user_token = "u_" + "a" * 32
        user_id = "anon_" + hashlib.sha256(user_token.encode("utf-8")).hexdigest()[:24]
        old_session_id = "s_" + "b" * 32
        target_session_id = "s_" + "c" * 32
        state = SessionStateStub(
            agent_messages=[{"role": "assistant", "content": "old conversation"}],
            current_batch={"batch": "old"},
            last_result={"result": "old"},
            last_vision_context={"vision": "old"},
            clear_sidebar_inputs=False,
            image_uploader_version=0,
            sidebar_draft_observation="old observation",
            sidebar_draft_image_bytes=b"old image",
            sidebar_draft_image_mime_type="image/png",
            sidebar_draft_image_name="old.png",
            manual_observation="old observation",
            memory_user_id=user_id,
            memory_project_id="citrus-agent",
            memory_session_id=old_session_id,
            memory_restored_session=old_session_id,
        )
        manager = SimpleNamespace(
            ensure_session=Mock(),
            restore_session_messages=Mock(return_value=[{"message_id": "target-row"}]),
        )
        restored_messages = [{"role": "assistant", "content": "target conversation"}]

        def query_value(name: str) -> str:
            return {"uid": user_token, "sid": target_session_id}.get(name, "")

        with (
            patch.object(app_main.st, "session_state", state),
            patch.object(app_main, "_query_value", side_effect=query_value),
            patch.object(app_main, "_set_query_value"),
            patch.object(app_main, "_authenticated_identity", return_value=""),
            patch.object(app_main, "get_memory_manager", return_value=manager),
            patch.object(app_main, "restore_ui_messages", return_value=restored_messages),
            patch.object(
                app_main,
                "restore_latest_analysis_state",
                return_value=(
                    {"batch": "target"},
                    {"result": "target"},
                    {"vision": "target"},
                ),
            ),
        ):
            app_main.initialize_memory_identity()

        self.assertEqual(target_session_id, state.memory_session_id)
        self.assertEqual(target_session_id, state.memory_restored_session)
        self.assertEqual(restored_messages, state.agent_messages)
        self.assertEqual({"batch": "target"}, state.current_batch)
        self.assertEqual({"result": "target"}, state.last_result)
        self.assertEqual({"vision": "target"}, state.last_vision_context)
        self.assertTrue(state.reset_main_scroll_position)
        self.assertNotIn("sidebar_draft_image_bytes", state)
        self.assertNotIn("sidebar_draft_observation", state)
        manager.restore_session_messages.assert_called_once_with(
            user_id,
            target_session_id,
            "citrus-agent",
        )

    def test_production_path_only_reloads_lightweight_ui_modules(self) -> None:
        source = Path(app_main.__file__).read_text(encoding="utf-8-sig")

        with (
            patch.object(app_main.importlib, "invalidate_caches") as invalidate_caches,
            patch.object(
                app_main.importlib,
                "reload",
                side_effect=lambda module: module,
            ) as reload_module,
        ):
            app_main.refresh_ui_modules()

        invalidate_caches.assert_called_once_with()
        self.assertEqual(
            [call(app_main.ui_components), call(app_main.ui_product_pages)],
            reload_module.call_args_list,
        )
        self.assertNotIn("from app.ui.product_pages import render_product_page", source)
        self.assertIn("ui_product_pages.render_product_page(active_view)", source)
        self.assertIn("live_orchestrator = orchestrator", source)

    def test_browser_history_sync_reloads_after_popstate(self) -> None:
        with patch.object(app_main.st, "iframe") as iframe:
            app_main.render_navigation_history_sync()

        iframe.assert_called_once()
        bootstrap = iframe.call_args.args[0]
        installer = app_main.NAVIGATION_HISTORY_SYNC_INSTALLER
        self.assertEqual({"height": 1, "tab_index": -1}, iframe.call_args.kwargs)
        self.assertIn('window.addEventListener("popstate", handlePopState);', installer)
        self.assertIn("window.location.reload()", installer)
        self.assertIn('loader = doc.createElement("script")', bootstrap)


class AnalysisPayloadLayoutTests(unittest.TestCase):
    def test_compact_narrative_moves_evidence_and_report_path_out_of_the_summary(self) -> None:
        narrative = """### 当前批次事实
产地：新会；品种：茶枝柑。

### 文献证据及其适用边界
- [文献1] 很长的原文证据。

### 推荐与备选方向
- 果皮-陈皮茶。

完整报告：`D:\\workspace\\outputs\\report.md`

### 本次引用文献
- [文献1] Citation
"""

        compact = app_main._compact_analysis_narrative(narrative)

        self.assertIn("当前批次事实", compact)
        self.assertIn("推荐与备选方向", compact)
        self.assertNotIn("文献证据及其适用边界", compact)
        self.assertNotIn("很长的原文证据", compact)
        self.assertNotIn("完整报告", compact)
        self.assertNotIn("D:\\workspace", compact)
        self.assertNotIn("本次引用文献", compact)
        self.assertNotIn("Citation", compact)

    def test_answer_defaults_to_compact_flow_and_hides_full_plan(self) -> None:
        source = Path(app_main.__file__).read_text(encoding="utf-8-sig")
        render_source = source[
            source.index("def render_analysis_payload") : source.index("def render_message")
        ]

        narrative = "if narrative_answer:\n        st.markdown(narrative_answer)"
        self.assertIn(narrative, render_source)
        self.assertIn("render_processing_flow_summary(processing_plan)", render_source)
        self.assertIn(
            'with st.expander("完整加工方案", expanded=False):',
            render_source,
        )
        self.assertIn("render_processing_plan(processing_plan)", render_source)
        self.assertIn("st.markdown(parameterized_text)", render_source)
        self.assertLess(
            render_source.index("render_processing_flow_summary(processing_plan)"),
            render_source.index(narrative),
        )
        self.assertLess(
            render_source.index(narrative),
            render_source.index('with st.expander("完整加工方案"'),
        )

    def test_render_places_summary_before_narrative_and_details_after_it(self) -> None:
        events: list[tuple[str, str]] = []

        @contextmanager
        def expander(label: str, *, expanded: bool = False):
            del expanded
            events.append(("enter", label))
            yield
            events.append(("exit", label))

        payload = {
            "result": {
                "scores": [{"direction": "果肉-柑橘汁/NFC"}],
                "quality_risks": [],
                "evidence": [],
                "parameter_groups": [],
                "parameterized_plan": {},
                "processing_intent": {},
                "report": "# 报告",
            },
            "report_path": "outputs/report.md",
            "summary": "summary",
            "answer": "answer",
        }
        processing_plan = {"stages": [{"name": "验收"}]}

        with (
            patch.object(app_main, "resolve_processing_plan", return_value=processing_plan),
            patch.object(
                app_main.agent_report,
                "parameterized_plan_markdown",
                return_value="PARAMETER DETAILS",
            ),
            patch.object(
                app_main.orchestrator,
                "ensure_primary_processing_flow",
                return_value="answer with flow",
            ),
            patch.object(
                app_main.orchestrator,
                "strip_primary_processing_flow",
                return_value="NARRATIVE",
            ),
            patch.object(app_main.orchestrator, "summarize_result", return_value="summary"),
            patch.object(
                app_main,
                "render_processing_flow_summary",
                side_effect=lambda _plan: events.append(("flow", "summary")),
            ),
            patch.object(app_main, "render_processing_plan", side_effect=lambda _plan: events.append(("plan", "rendered"))),
            patch.object(app_main, "render_tool_steps"),
            patch.object(app_main.st, "expander", side_effect=expander),
            patch.object(app_main.st, "markdown", side_effect=lambda value, **_kwargs: events.append(("markdown", str(value)))),
            patch.object(app_main.st, "info"),
            patch.object(app_main.st, "caption"),
            patch.object(app_main.st, "download_button"),
        ):
            app_main.render_analysis_payload(payload)

        flow_index = events.index(("flow", "summary"))
        narrative_index = events.index(("markdown", "NARRATIVE"))
        details_index = events.index(("enter", "完整加工方案"))
        plan_index = events.index(("plan", "rendered"))
        parameter_index = events.index(("markdown", "PARAMETER DETAILS"))
        self.assertLess(flow_index, narrative_index)
        self.assertLess(narrative_index, details_index)
        self.assertLess(details_index, plan_index)
        self.assertLess(plan_index, parameter_index)
        self.assertIn(("enter", "完整加工方案"), events)


class VisionStateRecoveryTests(unittest.TestCase):
    def test_analysis_vision_result_drops_raw_output_before_persist_and_restore(self) -> None:
        vision_result = {
            "answer": "候选品种为脐橙",
            "variety_candidate": "脐橙",
            "variety_confidence": "中",
            "_raw_model_output": "ROOT_RAW_OUTPUT_MUST_NOT_PERSIST",
            "structured_observation": {
                "品种候选": "脐橙",
                "_raw_model_output": "NESTED_RAW_OUTPUT_MUST_NOT_PERSIST",
                "observations": [
                    {
                        "safe": "果皮完整",
                        "_raw_model_output": "LIST_RAW_OUTPUT_MUST_NOT_PERSIST",
                    }
                ],
            },
        }
        snapshot = app_main.build_persisted_analysis_payload(
            {
                "result": {"report": "# 批次报告", "batch": {"batch_id": "B-VISION"}},
                "batch": {"batch_id": "B-VISION"},
                "report_path": Path("outputs/reports/B-VISION.md"),
                "answer": "已完成图片与批次分析。",
                "vision_result": vision_result,
            }
        )

        encoded = json.dumps(snapshot, ensure_ascii=False)
        self.assertEqual([], raw_model_output_keys(snapshot))
        self.assertNotIn("ROOT_RAW_OUTPUT_MUST_NOT_PERSIST", encoded)
        self.assertNotIn("NESTED_RAW_OUTPUT_MUST_NOT_PERSIST", encoded)
        self.assertNotIn("LIST_RAW_OUTPUT_MUST_NOT_PERSIST", encoded)
        self.assertEqual("果皮完整", snapshot["vision_result"]["structured_observation"]["observations"][0]["safe"])

        restored = app_main.restore_ui_messages(
            [
                make_row(
                    "analysis-with-vision",
                    "assistant",
                    "已完成图片与批次分析。",
                    message_type="analysis",
                    metadata={"analysis_payload": snapshot},
                )
            ]
        )

        self.assertEqual(1, len(restored))
        self.assertEqual("analysis", restored[0]["kind"])
        restored_vision = restored[0]["payload"]["vision_result"]
        self.assertEqual([], raw_model_output_keys(restored_vision))
        self.assertEqual("脐橙", restored_vision["variety_candidate"])

    def test_vision_only_message_drops_raw_output_during_restore(self) -> None:
        restored = app_main.restore_ui_messages(
            [
                make_row(
                    "vision-answer",
                    "assistant",
                    "图片显示为脐橙候选。",
                    metadata={
                        "vision_result": {
                            "answer": "图片显示为脐橙候选。",
                            "variety_candidate": "脐橙",
                            "_raw_model_output": "RAW_VISION_CHAT_OUTPUT",
                            "structured_observation": {
                                "品种候选": "脐橙",
                                "_raw_model_output": "RAW_NESTED_CHAT_OUTPUT",
                            },
                        }
                    },
                )
            ]
        )

        self.assertEqual([], raw_model_output_keys(restored[0]["vision_result"]))
        self.assertNotIn("RAW_VISION_CHAT_OUTPUT", repr(restored))
        self.assertNotIn("RAW_NESTED_CHAT_OUTPUT", repr(restored))

    def test_latest_state_recovers_vision_only_context_without_analysis_state(self) -> None:
        restored = app_main.restore_ui_messages(
            [
                make_row("vision-question", "user", "这张图是什么品种？"),
                make_row(
                    "vision-answer",
                    "assistant",
                    "外观初筛候选为脐橙。",
                    metadata={
                        "vision_result": {
                            "answer": "外观初筛候选为脐橙。",
                            "appearance_description": "果皮橙黄色，表面较完整。",
                            "structured_observation": {
                                "品种候选": "脐橙",
                                "品种判断置信度": "中",
                            },
                            "_raw_model_output": "DO_NOT_RESTORE_RAW_OUTPUT",
                        }
                    },
                ),
                make_row("ordinary-follow-up", "assistant", "还可以继续提供批次指标。"),
            ]
        )

        batch, result, vision = app_main.restore_latest_analysis_state(restored)

        self.assertIsNone(batch)
        self.assertIsNone(result)
        self.assertIsNotNone(vision)
        self.assertEqual("脐橙", vision["variety_candidate"])
        self.assertEqual("中", vision["variety_confidence"])
        self.assertEqual("外观初筛候选为脐橙。", vision["vision_answer"])
        self.assertEqual("果皮橙黄色，表面较完整。", vision["appearance_description"])
        self.assertNotIn("DO_NOT_RESTORE_RAW_OUTPUT", repr(vision))


class ScopedUploadedImageRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.manager = SimpleNamespace(db_path=self.root / "memory" / "memory.db")
        self.user_id = "user_alpha"
        self.project_id = "project_one"
        self.image_bytes = b"\x89PNG\r\n\x1a\nscoped-citrus-image"
        self.stored_path = app_main.persist_uploaded_image(
            self.manager,
            self.user_id,
            self.project_id,
            self.image_bytes,
            "image/png",
        )
        self.metadata = {
            "has_image": True,
            "stored_image_path": self.stored_path,
            "image_mime_type": "image/png",
            "image_size": len(self.image_bytes),
            "image_sha256": hashlib.sha256(self.image_bytes).hexdigest(),
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _restore_user_message(
        self,
        *,
        user_id: str | None = None,
        project_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        restored = app_main.restore_ui_messages(
            [
                make_row(
                    "user-image",
                    "user",
                    "请识别这张图片。",
                    metadata=metadata or self.metadata,
                )
            ],
            manager=self.manager,
            user_id=user_id or self.user_id,
            project_id=project_id or self.project_id,
        )
        self.assertEqual(1, len(restored))
        return restored[0]

    def test_image_is_restored_only_for_its_exact_user_and_project_scope(self) -> None:
        owner_message = self._restore_user_message()
        self.assertEqual(self.image_bytes, owner_message["image_bytes"])
        self.assertEqual("image/png", owner_message["image_mime_type"])
        self.assertNotIn("attachment_missing", owner_message)

        wrong_user = self._restore_user_message(user_id="user_beta")
        self.assertNotIn("image_bytes", wrong_user)
        self.assertTrue(wrong_user["attachment_missing"])

        wrong_project = self._restore_user_message(project_id="project_two")
        self.assertNotIn("image_bytes", wrong_project)
        self.assertTrue(wrong_project["attachment_missing"])

    def test_out_of_scope_path_is_rejected_even_with_matching_size_and_digest(self) -> None:
        outside_path = self.root / "outside" / "copied-image.png"
        outside_path.parent.mkdir(parents=True)
        outside_path.write_bytes(self.image_bytes)
        outside_metadata = {
            **self.metadata,
            "stored_image_path": str(outside_path),
        }

        restored = self._restore_user_message(metadata=outside_metadata)

        self.assertNotIn("image_bytes", restored)
        self.assertNotIn("image_mime_type", restored)
        self.assertTrue(restored["attachment_missing"])


if __name__ == "__main__":
    unittest.main()
