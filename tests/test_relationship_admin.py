from __future__ import annotations

import copy
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "avatarctl_relationship_admin", ROOT / "lib/avatarctl.py"
)
assert SPEC and SPEC.loader
avatarctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(avatarctl)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def relationship(name: str = "author") -> dict:
    return {
        "role": name,
        "stage": "stable",
        "trust": 70,
        "intimacy": 60,
        "attachment": 50,
        "current_dynamic": "explicit maintenance",
        "shared_commitments": ["test"],
        "important_boundaries": [],
        "preferred_names": {},
        "last_major_change": None,
    }


class RelationshipAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = copy.deepcopy(avatarctl.load_json(ROOT / "config.json"))
        self.config["runtime"]["state_dir"] = str(self.root / "state")
        self.paths = avatarctl.ensure_runtime(self.config)

    def state(self) -> dict:
        return avatarctl.load_json(self.paths["state"])

    def snapshot_non_relationship(self) -> dict:
        state = self.state()
        return {
            key: copy.deepcopy(state[key])
            for key in (
                "scene",
                "appearance",
                "physical",
                "emotion",
                "presentation",
                "memory",
                "visual",
            )
        }

    def overwrite(self, value: dict, **kwargs):
        return avatarctl.replace_relationship(
            self.config,
            value,
            apply=True,
            bypass_schema=kwargs.get("bypass_schema", False),
            confirm=kwargs.get("confirm", ""),
            input_source=kwargs.get("input_source", "test"),
        )

    def invoke_cli(self, arguments: list[str]) -> dict:
        output = io.StringIO()
        with (
            mock.patch.object(avatarctl, "load_config", return_value=self.config),
            mock.patch.object(avatarctl.sys, "argv", ["avatarctl", *arguments]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(avatarctl.main(), 0)
        return json.loads(output.getvalue())

    def test_cli_from_file_overwrite(self) -> None:
        source = self.root / "cli-relationship.json"
        source.write_text(json.dumps(relationship("cli-file")), encoding="utf-8")
        output = self.invoke_cli(
            ["relationship-overwrite", "--from-file", str(source), "--apply"]
        )
        self.assertEqual(self.state()["relationship"], relationship("cli-file"))
        self.assertNotIn("cli-file", canonical(output))

    def test_cli_inline_overwrite(self) -> None:
        output = self.invoke_cli(
            [
                "relationship-overwrite",
                "--json",
                json.dumps(relationship("cli-inline")),
                "--apply",
            ]
        )
        self.assertEqual(self.state()["relationship"], relationship("cli-inline"))
        self.assertNotIn("cli-inline", canonical(output))

    def test_from_file_complete_overwrite_and_not_merge(self) -> None:
        old = self.state()["relationship"]
        self.assertIn("legacy_affection", old)
        source = self.root / "relationship.json"
        source.write_text(json.dumps(relationship("file")), encoding="utf-8")
        value, label = avatarctl.load_relationship_payload(from_file=str(source))
        self.overwrite(value, input_source=label)
        current = self.state()["relationship"]
        self.assertEqual(current, relationship("file"))
        self.assertNotIn("legacy_affection", current)

    def test_inline_json_complete_overwrite(self) -> None:
        text = json.dumps(relationship("inline"))
        value, label = avatarctl.load_relationship_payload(json_text=text)
        result = self.overwrite(value, input_source=label)
        self.assertEqual(self.state()["relationship"], relationship("inline"))
        self.assertEqual(result["input_source"], "inline-json")

    def test_invalid_schema_rejected_and_state_unchanged(self) -> None:
        before = self.paths["state"].read_bytes()
        with self.assertRaises(avatarctl.AvatarError):
            self.overwrite({"role": "missing required fields"})
        self.assertEqual(self.paths["state"].read_bytes(), before)
        # Backup occurs before schema validation.
        self.assertEqual(len(list(self.paths["relationship_backups"].glob("*.json"))), 1)

    def test_break_glass_requires_confirm(self) -> None:
        before = self.paths["state"].read_bytes()
        with self.assertRaises(avatarctl.AvatarError):
            self.overwrite({"future": {"version": 99}}, bypass_schema=True)
        self.assertEqual(self.paths["state"].read_bytes(), before)

    def test_break_glass_accepts_future_object(self) -> None:
        future = {"future": {"version": 99}, "manual_repair": True}
        result = self.overwrite(
            future,
            bypass_schema=True,
            confirm="AUTHOR-BREAK-GLASS",
            input_source="file:/future.json",
        )
        self.assertEqual(self.state()["relationship"], future)
        self.assertTrue(result["schema_bypassed"])

    def test_break_glass_rejects_non_object_json(self) -> None:
        for text in ("[]", '"text"', "null", "42"):
            with self.subTest(text=text), self.assertRaises(avatarctl.AvatarError):
                avatarctl.load_relationship_payload(json_text=text)

    def test_backup_created_mode_and_shape(self) -> None:
        before = copy.deepcopy(self.state()["relationship"])
        before_revision = self.state()["continuity"]["revision"]
        result = self.overwrite(relationship())
        path = Path(result["backup_path"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        backup = avatarctl.load_json(path)
        self.assertEqual(backup["relationship"], before)
        self.assertEqual(backup["state_revision"], before_revision)
        self.assertEqual(backup["source"], "relationship-overwrite")
        self.assertTrue(backup["created_at"])

    def test_restore_restores_only_old_relationship(self) -> None:
        original = copy.deepcopy(self.state()["relationship"])
        first = self.overwrite(relationship("replacement"))
        non_relationship = self.snapshot_non_relationship()
        result = avatarctl.cmd_relationship_restore(
            self.config,
            first["backup_path"],
            apply=True,
            bypass_schema=False,
            confirm="",
        )
        self.assertEqual(self.state()["relationship"], original)
        self.assertEqual(self.snapshot_non_relationship(), non_relationship)
        self.assertEqual(result["event_type"], "author_relationship_restore")

    def test_break_glass_restore_requires_same_confirmation(self) -> None:
        self.overwrite(
            {"future_shape": {"version": 3}},
            bypass_schema=True,
            confirm="AUTHOR-BREAK-GLASS",
        )
        future_backup = avatarctl.create_relationship_backup(
            self.paths, self.state(), "test-future-backup"
        )
        self.overwrite(relationship("normal"))
        with self.assertRaises(avatarctl.AvatarError):
            avatarctl.cmd_relationship_restore(
                self.config,
                str(future_backup),
                apply=True,
                bypass_schema=True,
                confirm="",
            )
        avatarctl.cmd_relationship_restore(
            self.config,
            str(future_backup),
            apply=True,
            bypass_schema=True,
            confirm="AUTHOR-BREAK-GLASS",
        )
        self.assertEqual(
            self.state()["relationship"], {"future_shape": {"version": 3}}
        )

    def test_other_state_last_image_and_runtime_dirs_unchanged(self) -> None:
        state = self.state()
        state["continuity"]["last_image"] = "/tmp/sentinel-image.png"
        avatarctl.atomic_write_json(self.paths["state"], state)
        other_before = self.snapshot_non_relationship()
        continuity_before = copy.deepcopy(self.state()["continuity"])
        directory_before = {
            key: sorted(path.name for path in self.paths[key].iterdir())
            for key in ("jobs", "output", "pending")
        }
        with (
            mock.patch.object(avatarctl, "submit_comfyui") as comfy,
            mock.patch.object(avatarctl, "deliver_text_and_media") as deliver,
            mock.patch.object(avatarctl, "launch_worker") as worker,
        ):
            self.overwrite(relationship())
        after = self.state()
        self.assertEqual(self.snapshot_non_relationship(), other_before)
        self.assertEqual(after["continuity"]["last_image"], "/tmp/sentinel-image.png")
        for key, value in continuity_before.items():
            if key not in {"revision", "updated_at"}:
                self.assertEqual(after["continuity"][key], value)
        directory_after = {
            key: sorted(path.name for path in self.paths[key].iterdir())
            for key in ("jobs", "output", "pending")
        }
        self.assertEqual(directory_after, directory_before)
        comfy.assert_not_called()
        deliver.assert_not_called()
        worker.assert_not_called()

    def test_audit_history_contains_before_after_and_bypass(self) -> None:
        before = copy.deepcopy(self.state()["relationship"])
        after = relationship("audit")
        result = self.overwrite(after)
        event = json.loads(self.paths["history"].read_text().splitlines()[-1])
        self.assertEqual(event["event_type"], "author_relationship_overwrite")
        self.assertEqual(event["revision_before"], result["revision_before"])
        self.assertEqual(event["revision_after"], result["revision_after"])
        self.assertFalse(event["schema_bypassed"])
        self.assertEqual(event["changed_fields"], {"before": before, "after": after})
        self.assertTrue(event["timestamp"])

    def test_break_glass_audit_marks_bypass(self) -> None:
        self.overwrite(
            {"future": True},
            bypass_schema=True,
            confirm="AUTHOR-BREAK-GLASS",
        )
        event = json.loads(self.paths["history"].read_text().splitlines()[-1])
        self.assertTrue(event["schema_bypassed"])

    def test_legacy_relationship_patch_still_works(self) -> None:
        avatarctl.cmd_update(self.config, {"internal.trust": 91}, "")
        state = self.state()
        self.assertEqual(state["internal"]["trust"], 91)
        self.assertEqual(state["relationship"]["trust"], 91)

    def test_relationship_update_is_partial(self) -> None:
        before = copy.deepcopy(self.state()["relationship"])
        avatarctl.cmd_relationship_update(self.config, {"trust": 44}, apply=True)
        after = self.state()["relationship"]
        self.assertEqual(after["trust"], 44)
        for key, value in before.items():
            if key != "trust":
                self.assertEqual(after[key], value)

    def test_from_file_requires_absolute_path(self) -> None:
        with self.assertRaises(avatarctl.AvatarError):
            avatarctl.load_relationship_payload(from_file="relationship.json")

    def test_restore_rejects_traversal_outside_directory_and_symlink(self) -> None:
        valid = avatarctl.create_relationship_backup(
            self.paths, self.state(), "path-test"
        )
        outside = self.root / "outside.json"
        outside.write_bytes(valid.read_bytes())
        link = self.paths["relationship_backups"] / "link.json"
        link.symlink_to(valid)
        directory = self.paths["relationship_backups"] / "directory.json"
        directory.mkdir()
        for raw in (
            "../outside",
            str(outside),
            str(link),
            str(directory),
        ):
            with self.subTest(raw=raw), self.assertRaises(avatarctl.AvatarError):
                avatarctl.resolve_relationship_backup(self.paths, raw)

    def test_relationship_backups_are_never_automatically_deleted(self) -> None:
        first = self.overwrite(relationship("first"))
        second = self.overwrite(relationship("second"))
        before = {
            Path(first["backup_path"]).name,
            Path(second["backup_path"]).name,
        }
        avatarctl.cmd_relationship_backups(self.config)
        avatarctl.cmd_relationship_restore(
            self.config,
            first["backup_path"],
            apply=True,
            bypass_schema=False,
            confirm="",
        )
        after = {
            path.name for path in self.paths["relationship_backups"].glob("*.json")
        }
        self.assertTrue(before <= after)

    def test_worker_and_author_writes_are_serialized(self) -> None:
        state = self.state()
        state["relationship"] = relationship("old")
        avatarctl.sync_relationship_compatibility(state, state["relationship"])
        avatarctl.atomic_write_json(self.paths["state"], state)
        job_path = self.paths["jobs"] / "worker.json"
        avatarctl.atomic_write_json(
            job_path,
            {
                "job_id": "worker",
                "status": "queued",
                "action": "render",
                "patch": {"visual.pose": "worker pose"},
                "remember": "",
                "say": "",
                "channel": "disabled",
                "no_send": True,
            },
        )
        worker_has_read = threading.Event()
        release_worker = threading.Event()
        author_finished = threading.Event()
        errors: list[BaseException] = []

        def submit(*_args, **_kwargs):
            # run_generation_job has read state and built its candidate while
            # holding avatar.lock when it reaches submit.
            worker_has_read.set()
            self.assertTrue(release_worker.wait(5))
            return "prompt-id"

        def run_worker():
            try:
                with (
                    mock.patch.object(avatarctl, "submit_comfyui", side_effect=submit),
                    mock.patch.object(
                        avatarctl,
                        "poll_comfyui",
                        return_value={"filename": "x.png", "subfolder": "", "type": "output"},
                    ),
                    mock.patch.object(
                        avatarctl,
                        "download_image",
                        return_value=(b"\x89PNG\r\n\x1a\n", ".png"),
                    ),
                ):
                    avatarctl.run_generation_job(job_path, self.config)
            except BaseException as exc:  # surfaced in the main test thread
                errors.append(exc)

        def run_author():
            try:
                self.overwrite(relationship("author-new"))
                author_finished.set()
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run_worker)
        author = threading.Thread(target=run_author)
        worker.start()
        self.assertTrue(worker_has_read.wait(5))
        author.start()
        time.sleep(0.1)
        # Author cannot complete while the worker owns the state write lock.
        self.assertFalse(author_finished.is_set())
        release_worker.set()
        worker.join(5)
        author.join(5)
        self.assertFalse(errors)
        self.assertTrue(author_finished.is_set())
        self.assertEqual(self.state()["relationship"], relationship("author-new"))


if __name__ == "__main__":
    unittest.main()
