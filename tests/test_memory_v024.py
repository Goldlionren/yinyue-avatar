from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("avatarctl_memory", ROOT / "lib/avatarctl.py")
assert SPEC and SPEC.loader
avatarctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(avatarctl)
memory_store = avatarctl.memory_store
recent = avatarctl.sys.modules["recent_history_v024"]


class MemoryRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = copy.deepcopy(avatarctl.load_json(ROOT / "config.json"))
        self.config["runtime"]["state_dir"] = self.temp.name
        self.paths = avatarctl.ensure_runtime(self.config)

    def add(self, text: str, memory_type="shared_experience", importance=3):
        return avatarctl.cmd_memory_add(
            self.config,
            memory_type=memory_type,
            importance=importance,
            text=text,
            source_event_id="test-source",
        )

    def events(self):
        return memory_store.load_events(
            self.paths["memory_events"], self.config["memory"]["max_text_chars"]
        )

    def test_memory_crud_and_state_partitions_unchanged(self) -> None:
        before = avatarctl.load_json(self.paths["state"])
        added = self.add("一起去了图书馆", "shared_experience", 4)
        shown = avatarctl.cmd_memory_show(self.config, added["memory_id"])
        listed = avatarctl.cmd_memory_list(
            self.config, status="active", memory_type="shared_experience"
        )
        self.assertEqual(shown["event"]["text"], "一起去了图书馆")
        self.assertEqual(listed["count"], 1)
        after = avatarctl.load_json(self.paths["state"])
        for key in ("relationship", "scene", "continuity"):
            self.assertEqual(after[key], before[key])

    def test_dedupe_does_not_write_duplicate(self) -> None:
        first = self.add("  同一件   事情 ")
        history_before = self.paths["history"].read_bytes()
        second = self.add("同一件 事情")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["memory_id"], second["memory_id"])
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.paths["history"].read_bytes(), history_before)

    def test_supersede_retains_old_event(self) -> None:
        old = self.add("旧偏好", "user_preference", 2)
        new = avatarctl.cmd_memory_supersede(
            self.config,
            old["memory_id"],
            text="新偏好",
            memory_type="",
            importance=5,
            source_event_id="correction",
        )
        events = {event["memory_id"]: event for event in self.events()}
        self.assertEqual(events[old["memory_id"]]["status"], "superseded")
        self.assertEqual(events[new["memory_id"]]["supersedes"], old["memory_id"])
        self.assertEqual(events[new["memory_id"]]["status"], "active")

    def test_resolve_retains_record(self) -> None:
        added = self.add("待完成事项", "open_thread", 4)
        avatarctl.cmd_memory_resolve(self.config, added["memory_id"])
        events = {event["memory_id"]: event for event in self.events()}
        self.assertEqual(events[added["memory_id"]]["status"], "resolved")

    def test_input_schema_empty_length_type_and_importance(self) -> None:
        cases = [
            dict(text="", memory_type="shared_experience", importance=3),
            dict(text="x", memory_type="invalid", importance=3),
            dict(text="x", memory_type="shared_experience", importance=0),
            dict(
                text="x" * (self.config["memory"]["max_text_chars"] + 1),
                memory_type="shared_experience",
                importance=3,
            ),
        ]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(
                (avatarctl.AvatarError, memory_store.MemoryValidationError)
            ):
                self.add(**values)

    def test_summary_sorting_and_active_only(self) -> None:
        max_text = self.config["memory"]["max_text_chars"]
        events = [
            memory_store.make_event(
                memory_type="important_fact",
                importance=importance,
                text=text,
                source_event_id=None,
                supersedes=None,
                created_at=created,
                max_text_chars=max_text,
            )
            for importance, text, created in (
                (3, "medium-old", "2026-01-01T00:00:00+00:00"),
                (5, "high", "2026-01-02T00:00:00+00:00"),
                (3, "medium-new", "2026-01-03T00:00:00+00:00"),
            )
        ]
        archived = copy.deepcopy(events[0])
        archived["memory_id"] = "archived"
        archived["status"] = "archived"
        events.append(archived)
        summary = memory_store.build_summary(
            events, generated_at="fixed", per_category_limit=8, max_chars=1000
        )
        self.assertEqual(
            [item["text"] for item in summary["important_facts"]],
            ["high", "medium-new", "medium-old"],
        )
        self.assertNotIn("archived", [item["memory_id"] for item in summary["important_facts"]])

    def test_summary_character_budget(self) -> None:
        max_text = self.config["memory"]["max_text_chars"]
        events = [
            memory_store.make_event(
                memory_type="important_fact",
                importance=5,
                text=text,
                source_event_id=None,
                supersedes=None,
                created_at=f"2026-01-0{index}T00:00:00+00:00",
                max_text_chars=max_text,
            )
            for index, text in ((1, "abcdefghij"), (2, "klmnopqrst"))
        ]
        summary = memory_store.build_summary(
            events, generated_at="fixed", per_category_limit=8, max_chars=12
        )
        self.assertLessEqual(summary["used_chars"], 12)
        self.assertTrue(summary["truncated"])

    def test_summary_failure_rolls_back_events_and_preserves_summary(self) -> None:
        self.add("initial")
        old_events = self.paths["memory_events"].read_bytes()
        old_summary = self.paths["memory_summary"].read_bytes()
        max_text, _, _ = avatarctl.memory_limits(self.config)
        events = memory_store.load_events(self.paths["memory_events"], max_text)
        candidate, _, _ = memory_store.candidate_add(
            events,
            memory_type="important_fact",
            importance=5,
            text="candidate",
            source_event_id=None,
            created_at="2026-01-01T00:00:00+00:00",
            max_text_chars=max_text,
        )
        summary = avatarctl.build_memory_summary_for(candidate, self.config, "fixed")

        def fail_summary(path, value):
            if path == self.paths["memory_summary"]:
                raise OSError("injected summary failure")
            avatarctl.atomic_write_json(path, value)

        with self.assertRaises(OSError):
            memory_store.commit_memory_transaction(
                events_path=self.paths["memory_events"],
                summary_path=self.paths["memory_summary"],
                backups_dir=self.paths["memory_backups"],
                old_events=events,
                candidate_events=candidate,
                candidate_summary=summary,
                atomic_text_writer=avatarctl.atomic_write_text,
                atomic_json_writer=fail_summary,
                now="fixed",
            )
        self.assertEqual(self.paths["memory_events"].read_bytes(), old_events)
        self.assertEqual(self.paths["memory_summary"].read_bytes(), old_summary)

    def test_summary_backup_is_created_and_not_pruned(self) -> None:
        self.add("one")
        backups_before = set(self.paths["memory_backups"].glob("*.json"))
        avatarctl.cmd_memory_rebuild_summary(self.config)
        backups_after = set(self.paths["memory_backups"].glob("*.json"))
        self.assertGreater(len(backups_after), len(backups_before))
        avatarctl.cmd_memory_rebuild_summary(self.config)
        self.assertGreater(
            len(set(self.paths["memory_backups"].glob("*.json"))),
            len(backups_after),
        )

    def test_context_does_not_read_memory_events(self) -> None:
        self.paths["memory_events"].write_text("{not-valid-json\n", encoding="utf-8")
        result = avatarctl.cmd_context(self.config)
        self.assertEqual(result["memory_summary"]["schema_version"], 1)

    def test_legacy_state_memory_bootstraps_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = copy.deepcopy(avatarctl.load_json(ROOT / "config.json"))
            config["runtime"]["state_dir"] = tmp
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            state = avatarctl.load_json(ROOT / "defaults/state.default.json")
            state["memory"]["recent_events"] = [
                {"at": "old", "content": "旧共同经历"}
            ]
            avatarctl.atomic_write_json(root / "state.json", state)
            paths = avatarctl.ensure_runtime(config)
            first = memory_store.load_events(
                paths["memory_events"], config["memory"]["max_text_chars"]
            )
            avatarctl.ensure_runtime(config)
            second = memory_store.load_events(
                paths["memory_events"], config["memory"]["max_text_chars"]
            )
            self.assertEqual(len(first), 1)
            self.assertEqual(first, second)

    def test_remember_maps_to_shared_experience_importance_three_and_dedupes(self) -> None:
        avatarctl.cmd_update(self.config, {}, "共同看了一场电影")
        avatarctl.cmd_update(self.config, {}, "共同看了一场电影")
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "shared_experience")
        self.assertEqual(events[0]["importance"], 3)

    def test_telegram_disabled_blocks_without_send_subprocess(self) -> None:
        config = copy.deepcopy(self.config)
        config["telegram"]["enabled"] = False
        with mock.patch.object(avatarctl, "run_send_with_retry") as send:
            result = avatarctl.deliver_text_and_media(
                say="blocked",
                image=Path(self.temp.name) / "not-used.png",
                channel="DISABLED",
                config=config,
            )
        self.assertTrue(result["blocked"])
        self.assertFalse(result["attempted"])
        send.assert_not_called()

    def test_staging_launcher_disabled_blocks_worker(self) -> None:
        config = copy.deepcopy(self.config)
        config["runtime"]["launcher"] = "disabled"
        with self.assertRaises(avatarctl.AvatarError):
            avatarctl.launch_worker(
                self.paths["jobs"] / "never.json",
                config,
                self.paths["logs"] / "never.log",
            )


class MeaningfulHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.jsonl"

    def write_lines(self, values) -> None:
        with self.path.open("wb") as handle:
            for value in values:
                if isinstance(value, bytes):
                    handle.write(value + b"\n")
                else:
                    handle.write(json.dumps(value).encode() + b"\n")

    def test_whitelist_and_corrupt_line_tolerance(self) -> None:
        self.write_lines(
            [
                {"event": "doctor", "event_id": "ignored", "at": "1"},
                b"{bad-json",
                {"event": "migration", "event_id": "kept", "at": "2"},
            ]
        )
        result = recent.meaningful_recent_history(
            self.path, max_events=8, max_chars=4000, scan_max_lines=100
        )
        self.assertEqual([event["event_id"] for event in result["events"]], ["kept"])
        self.assertEqual(result["skipped_corrupt_lines"], 1)

    def test_event_id_and_business_fingerprint_dedupe(self) -> None:
        self.write_lines(
            [
                {"event": "migration", "event_id": "same", "at": "1", "from_schema": 1, "to_schema": 2},
                {"event": "migration", "event_id": "same", "at": "2", "from_schema": 1, "to_schema": 2},
                {"event": "migration", "event_id": "other-a", "at": "3", "from_schema": 1, "to_schema": 2},
                {"event": "migration", "event_id": "other-b", "at": "4", "from_schema": 1, "to_schema": 2},
            ]
        )
        result = recent.meaningful_recent_history(
            self.path, max_events=8, max_chars=4000, scan_max_lines=100
        )
        # Compact migration fingerprints ignore event_id/timestamp.
        self.assertEqual(len(result["events"]), 1)

    def test_priority_count_budget_and_chronological_output(self) -> None:
        self.write_lines(
            [
                {"event": "render", "event_id": "render", "at": "1", "image": "/x"},
                {"event_type": "author_relationship_overwrite", "event_id": "rel", "timestamp": "3", "revision_before": 1, "revision_after": 2, "changed_fields": {"before": {"secret": "x"}, "after": {"secret": "y"}}},
                {"event": "transition", "event_id": "scene", "at": "2", "transition": {"transition_type": "new_scene"}},
            ]
        )
        result = recent.meaningful_recent_history(
            self.path, max_events=2, max_chars=4000, scan_max_lines=100
        )
        self.assertEqual(
            [event["event_id"] for event in result["events"]], ["scene", "rel"]
        )
        self.assertTrue(result["truncated"])
        self.assertNotIn("changed_fields", result["events"][-1])
        tiny = recent.meaningful_recent_history(
            self.path, max_events=8, max_chars=10, scan_max_lines=100
        )
        self.assertEqual(tiny["events"], [])
        self.assertTrue(tiny["truncated"])


if __name__ == "__main__":
    unittest.main()
