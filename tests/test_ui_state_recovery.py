from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app import main as app_main


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

        self.assertIn("version: 4", installer)
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
            ("touchstart", "handleUserInput"),
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
        self.assertLess(
            installer.index("resetTop();"),
            installer.index("manager.scheduleMotion(resetTop"),
        )

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

    def test_only_the_first_progress_update_requests_reveal(self) -> None:
        source = Path(app_main.__file__).read_text(encoding="utf-8-sig")
        handle_prompt = source[
            source.index("def handle_prompt") : source.index("def main()")
        ]

        self.assertIn("progress_revealed = False", handle_prompt)
        self.assertIn("nonlocal progress_revealed", handle_prompt)
        self.assertIn(
            "reveal_id = user_message_id if should_reveal_progress and not progress_revealed else None",
            handle_prompt,
        )
        self.assertEqual(1, handle_prompt.count("render_agent_progress("))
        for message in (
            "正在启动批次分析流程",
            "正在读取图片并回答本轮问题",
            "正在全面检索本地文献并组织专业回答",
        ):
            self.assertIn(f'update_progress("{message}")', handle_prompt)


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
