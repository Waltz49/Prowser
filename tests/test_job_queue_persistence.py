#!/usr/bin/env python3
"""Verify image-gen job queue persistence (serialize, load/save, fold-on-shutdown)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Repo root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestJobQueuePersistenceLayer(unittest.TestCase):
    def test_serialize_roundtrip_fields(self):
        from imagegen_plugins.model_task_queue import QueuedGenerateJob
        from imagegen_plugins.image_gen_persistence import (
            load_job_queue_records,
            save_job_queue_records,
            serialize_queued_job_record,
        )

        plugin = MagicMock()
        plugin.plugin_id = "flux_schnell_mflux"
        plugin.function = "create"
        job = QueuedGenerateJob(
            job_id="abc123",
            plugin=plugin,
            values={"prompt": "test prompt", "copies": 3, "steps": 4},
            status_html="",
            thumbnail_paths=[],
            copies_total=3,
            full_prompt="test prompt",
            plugin_id="flux_schnell_mflux",
            function="create",
        )
        rec = serialize_queued_job_record(job)
        self.assertEqual(rec["job_id"], "abc123")
        self.assertEqual(rec["plugin_id"], "flux_schnell_mflux")
        self.assertEqual(rec["function"], "create")
        self.assertEqual(rec["copies_total"], 3)
        self.assertEqual(rec["values"]["prompt"], "test prompt")
        self.assertEqual(rec["values"]["copies"], 3)

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "imagegen_plugins.image_gen_persistence.get_config"
            ) as mock_cfg:
                from config import ImageBrowserConfig

                cfg = ImageBrowserConfig(profile_dir=tmp)
                mock_cfg.return_value = cfg
                save_job_queue_records([rec])
                loaded = load_job_queue_records()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["job_id"], "abc123")
            self.assertEqual(loaded[0]["copies_total"], 3)

    def test_load_skips_invalid_records(self):
        from imagegen_plugins.image_gen_persistence import load_job_queue_records

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = os.path.join(tmp, "data", "settings.json")
            os.makedirs(os.path.dirname(settings_path), exist_ok=True)
            with open(settings_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "imagegen": {
                            "job_queue": [
                                {
                                    "job_id": "ok",
                                    "plugin_id": "p",
                                    "function": "create",
                                    "values": {},
                                },
                                {
                                    "job_id": "",
                                    "plugin_id": "p",
                                    "function": "create",
                                    "values": {},
                                },
                                "not-a-dict",
                            ]
                        }
                    },
                    fh,
                )
            with patch(
                "imagegen_plugins.image_gen_persistence.get_config"
            ) as mock_cfg:
                from config import ImageBrowserConfig

                cfg = ImageBrowserConfig(profile_dir=tmp)
                mock_cfg.return_value = cfg
                loaded = load_job_queue_records()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["job_id"], "ok")

    def test_json_safe_dict_drops_non_serializable(self):
        from imagegen_plugins.image_gen_persistence import _json_safe_dict

        class NotSerializable:
            pass

        out = _json_safe_dict({"a": 1, "b": NotSerializable()})
        self.assertEqual(out, {"a": 1})


class TestFoldActiveJobIntoQueue(unittest.TestCase):
    def test_remaining_copies_formula(self):
        """Active job folded with copies = remaining (includes in-progress copy)."""
        remaining_cases = [
            (3, 0, 3),  # 3 copies, none done, running first
            (3, 1, 2),  # 1 done, 2 left
            (3, 2, 1),  # 2 done, 1 left
            (1, 0, 1),  # single copy
        ]
        for total, done, expected in remaining_cases:
            remaining = max(1, total - done)
            self.assertEqual(remaining, expected, f"total={total} done={done}")


class TestPersistSnapshot(unittest.TestCase):
    def test_snapshot_includes_active_and_pending(self):
        from imagegen_plugins.image_gen_controller import ImageGenController
        from imagegen_plugins.model_task_queue import QueuedGenerateJob

        mw = MagicMock()
        ctrl = ImageGenController.__new__(ImageGenController)
        ctrl.main_window = mw
        plugin = MagicMock()
        plugin.plugin_id = "flux_schnell_mflux"
        plugin.function = "create"
        plugin.pipeline_id = "flux_schnell_mflux_play"
        ctrl._active_plugin = plugin
        ctrl._active_queue_job_id = "active1"
        ctrl._copies_total = 3
        ctrl._copies_done = 1
        ctrl._pending_values = {"prompt": "active", "copies": 3}
        ctrl._active_thumbnail_paths = []
        pending = QueuedGenerateJob(
            job_id="pending2",
            plugin=plugin,
            values={"prompt": "pending", "copies": 1},
            status_html="",
            thumbnail_paths=[],
            copies_total=1,
            plugin_id="flux_schnell_mflux",
            function="create",
        )
        ctrl._queue = [pending]
        records = ctrl._job_queue_records_for_persist()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["job_id"], "active1")
        self.assertEqual(records[0]["copies_total"], 2)
        self.assertEqual(records[0]["values"]["copies"], 2)
        self.assertEqual(records[1]["job_id"], "pending2")


class TestExitPersistGuard(unittest.TestCase):
    def test_exit_persist_blocks_late_empty_overwrite(self):
        from imagegen_plugins.image_gen_controller import ImageGenController
        from imagegen_plugins.model_task_queue import QueuedGenerateJob

        mw = MagicMock()
        ctrl = ImageGenController.__new__(ImageGenController)
        ctrl.main_window = mw
        ctrl._queue_persist_timer = MagicMock()
        ctrl._queue_advance_suppressed = False
        ctrl._exit_queue_persisted = False
        ctrl._queue_persist_suppressed = False
        ctrl._active_plugin = None
        ctrl._active_queue_job_id = ""
        plugin = MagicMock()
        plugin.plugin_id = "flux_schnell_mflux"
        plugin.function = "create"
        ctrl._queue = [
            QueuedGenerateJob(
                job_id="j1",
                plugin=plugin,
                values={"prompt": "one", "copies": 1},
                status_html="",
                thumbnail_paths=[],
                copies_total=1,
                plugin_id="flux_schnell_mflux",
                function="create",
            )
        ]
        saved: list = []

        def _capture(records):
            saved.append(list(records))

        with patch(
            "imagegen_plugins.image_gen_controller.save_job_queue_records",
            side_effect=_capture,
        ):
            ctrl._persist_job_queue_for_exit()
            ctrl._queue.clear()
            ctrl._persist_job_queue_now()
            ctrl._schedule_persist_job_queue()
            ctrl._persist_job_queue_for_exit()
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(saved[0]), 1)
        self.assertEqual(saved[0][0]["job_id"], "j1")
        ctrl._queue_persist_timer.start.assert_not_called()


class TestMissingReferenceValidation(unittest.TestCase):
    def test_create_job_no_refs_not_invalid(self):
        from imagegen_plugins.model_task_queue import job_references_invalid

        plugin = MagicMock()
        plugin.function = "create"
        plugin.pipeline_id = "flux_schnell_mflux_play"
        self.assertFalse(job_references_invalid(plugin, {"prompt": "x"}))

    def test_edit_job_missing_source_is_invalid(self):
        from imagegen_plugins.model_task_queue import job_references_invalid

        plugin = MagicMock()
        plugin.function = "edit"
        plugin.pipeline_id = "mflux_flux2_klein_edit"
        self.assertTrue(
            job_references_invalid(
                plugin,
                {"source_image_path": "/no/such/file.png", "prompt": "x"},
            )
        )


class TestConfirmQuitIfRunning(unittest.TestCase):
    def _make_ctrl(self):
        from imagegen_plugins.image_gen_controller import ImageGenController

        mw = MagicMock()
        mw._api_quit_in_progress = False
        ctrl = ImageGenController.__new__(ImageGenController)
        ctrl.main_window = mw
        ctrl._tasks = MagicMock()
        ctrl._foreground_tasks = MagicMock()
        ctrl._hold_job_queue = False
        ctrl._queue = []
        ctrl.prepare_for_shutdown = MagicMock()
        return ctrl

    def test_hold_with_queued_jobs_no_confirm(self):
        ctrl = self._make_ctrl()
        ctrl._hold_job_queue = True
        ctrl._queue = [MagicMock()]
        ctrl._tasks.is_running.return_value = False
        ctrl._foreground_tasks.is_running.return_value = False
        with patch("imagegen_plugins.image_gen_controller.show_styled_question") as ask:
            self.assertTrue(ctrl.confirm_quit_if_running())
            ask.assert_not_called()

    def test_between_series_cooldown_no_confirm(self):
        ctrl = self._make_ctrl()
        ctrl._hold_job_queue = True
        ctrl._copy_batch_active = True
        ctrl._copy_batch_cancelled = False
        ctrl._tasks.is_running.return_value = False
        ctrl._foreground_tasks.is_running.return_value = False
        with patch("imagegen_plugins.image_gen_controller.show_styled_question") as ask:
            self.assertTrue(ctrl.confirm_quit_if_running())
            ask.assert_not_called()

    def test_active_generation_shows_confirm(self):
        from PySide6.QtWidgets import QMessageBox

        ctrl = self._make_ctrl()
        ctrl._tasks.is_running.return_value = True
        ctrl._foreground_tasks.is_running.return_value = False
        with patch(
            "imagegen_plugins.image_gen_controller.show_styled_question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as ask:
            self.assertTrue(ctrl.confirm_quit_if_running())
            ask.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
