from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("avatarctl_v024", ROOT / "lib/avatarctl.py")
assert SPEC and SPEC.loader
avatarctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(avatarctl)
state_v024 = avatarctl.sys.modules["state_v024"]


def default_state() -> dict:
    return avatarctl.load_json(ROOT / "defaults/state.default.json")


class TransitionTests(unittest.TestCase):
    def gym_state(self) -> dict:
        state = default_state()
        state["scene"].update(
            {
                "scene_id": "gym-1",
                "location": "健身房",
                "environment": "健身房器械区",
                "activity": "运动",
                "props": ["健身器械"],
            }
        )
        state["appearance"]["outfit"] = {
            "base": ["运动服"],
            "legwear": "",
            "footwear": "运动鞋",
            "outerwear": [],
        }
        state["physical"].update(
            {"cleanliness": "dirty", "sweat": "heavy", "dirt": "some"}
        )
        state["presentation"].update(
            {
                "pose": "弯腰喘气",
                "action": "休息",
                "held_objects": ["毛巾"],
                "camera": "健身自拍构图",
            }
        )
        state["relationship"]["shared_commitments"] = ["保持诚实"]
        state["memory"]["long_term_summary"] = "共同去过海边。"
        state_v024.sync_legacy_view(state)
        return state

    def test_t1_cross_scene_composite_cleanup(self) -> None:
        state = self.gym_state()
        relationship = copy.deepcopy(state["relationship"])
        memory = copy.deepcopy(state["memory"])
        result = state_v024.apply_transition(
            state,
            {
                "transition_type": "new_scene",
                "actions": [
                    {"type": "shower"},
                    {"type": "replace_outfit", "preset": "clean_casual"},
                    {"type": "move", "location": "图书馆"},
                    {"type": "start_activity", "activity": "在图书馆休闲"},
                ],
            },
        )
        self.assertEqual(result["scene"]["location"], "图书馆")
        self.assertEqual(result["appearance"]["outfit"]["base"], ["clean_casual"])
        self.assertNotIn("运动服", json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["physical"]["sweat"], "none")
        self.assertEqual(result["physical"]["dirt"], "none")
        self.assertEqual(result["physical"]["cleanliness"], "clean")
        self.assertEqual(result["physical"]["wetness"], "dry")
        self.assertEqual(result["presentation"]["pose"], "")
        self.assertEqual(result["presentation"]["held_objects"], [])
        self.assertNotIn("健身房", json.dumps(result["scene"], ensure_ascii=False))
        self.assertEqual(result["relationship"], relationship)
        self.assertEqual(result["memory"], memory)

    def test_t2_continue_keeps_scene_and_outfit(self) -> None:
        state = default_state()
        state["scene"].update({"scene_id": "library-7", "location": "图书馆"})
        state["appearance"]["outfit"]["base"] = ["休闲服"]
        result = state_v024.apply_transition(
            state,
            {
                "transition_type": "continue",
                "actions": [{"type": "set_action", "action": "把书翻到下一页"}],
            },
        )
        self.assertEqual(result["scene"]["scene_id"], "library-7")
        self.assertEqual(result["scene"]["location"], "图书馆")
        self.assertEqual(result["appearance"]["outfit"]["base"], ["休闲服"])
        self.assertEqual(result["presentation"]["action"], "把书翻到下一页")

    def test_t3_replace_outfit(self) -> None:
        state = self.gym_state()
        relationship = copy.deepcopy(state["relationship"])
        memory = copy.deepcopy(state["memory"])
        result = state_v024.apply_transition(
            state,
            {
                "transition_type": "partial",
                "actions": [{"type": "replace_outfit", "preset": "白色连衣裙"}],
            },
        )
        self.assertEqual(result["appearance"]["outfit"]["base"], ["白色连衣裙"])
        self.assertEqual(result["appearance"]["outfit"]["outerwear"], [])
        self.assertEqual(result["scene"]["location"], "健身房")
        self.assertEqual(result["relationship"], relationship)
        self.assertEqual(result["memory"], memory)

    def test_t4_layer_outfit(self) -> None:
        state = default_state()
        base = copy.deepcopy(state["appearance"]["outfit"]["base"])
        result = state_v024.apply_transition(
            state,
            {
                "transition_type": "partial",
                "actions": [{"type": "layer_outfit", "item": "外套"}],
            },
        )
        self.assertEqual(result["appearance"]["outfit"]["base"], base)
        self.assertEqual(result["appearance"]["outfit"]["outerwear"], ["外套"])

    def test_t5_shower_intermediate_is_damp(self) -> None:
        state = self.gym_state()
        result = state_v024.apply_transition(
            state,
            {
                "transition_type": "partial",
                "actions": [{"type": "shower"}],
            },
        )
        self.assertEqual(result["physical"]["cleanliness"], "clean")
        self.assertEqual(result["physical"]["sweat"], "none")
        self.assertEqual(result["physical"]["wetness"], "damp")

    def test_t6_reset_scene_preserves_relationship_and_memory(self) -> None:
        state = self.gym_state()
        result = state_v024.reset_scene(state)
        self.assertEqual(result["relationship"], state["relationship"])
        self.assertEqual(result["memory"], state["memory"])
        self.assertEqual(result["scene"]["location"], "")
        self.assertEqual(result["appearance"]["outfit"]["base"], [])

    def test_transition_rejects_unknown_fields(self) -> None:
        with self.assertRaises(state_v024.StateValidationError):
            state_v024.apply_transition(
                default_state(),
                {
                    "transition_type": "partial",
                    "actions": [{"type": "shower", "relationship": {}}],
                },
            )


class MigrationAndTransactionTests(unittest.TestCase):
    def legacy_state(self) -> dict:
        state = {
            "schema_version": 1,
            "character": {
                "name": "银月",
                "identity": "固定成年女性数字人",
                "identity_locked": True,
            },
            "visual": {
                "outfit": "生产服装",
                "legwear": "丝袜",
                "footwear": "鞋",
                "hair": "白发",
                "makeup": "淡妆",
                "expression": "微笑",
                "pose": "坐着",
                "action": "看书",
                "scene": "旧场景",
                "lighting": "自然光",
                "camera": "全身",
            },
            "internal": {
                "mood": "平静",
                "current_activity": "阅读",
                "relationship_stage": 4,
                "affection": 88,
                "trust": 77,
            },
            "continuity": {
                "revision": 196,
                "updated_at": "2026-07-28T00:00:00+00:00",
                "last_image": "/readonly/output/r0196.png",
                "last_prompt_sha256": "abc",
                "last_prompt_id": "prompt",
            },
            "memory": {"recent_events": [{"content": "旧记忆"}]},
        }
        return state

    def test_t8_migration_is_lossless_and_idempotent(self) -> None:
        old = self.legacy_state()
        migrated = state_v024.migrate_v1_to_v2(old)
        again = state_v024.migrate_v1_to_v2(migrated)
        self.assertEqual(migrated, again)
        self.assertEqual(migrated["continuity"]["revision"], 196)
        self.assertEqual(
            migrated["continuity"]["last_image"], "/readonly/output/r0196.png"
        )
        self.assertEqual(migrated["visual"], old["visual"])
        self.assertEqual(migrated["internal"], old["internal"])
        self.assertEqual(migrated["relationship"]["trust"], 77)
        self.assertEqual(migrated["relationship"]["intimacy"], 88)
        self.assertEqual(
            migrated["memory"]["recent_events"], old["memory"]["recent_events"]
        )

    def test_migration_file_backup_event_and_second_run_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "state.json"
            history_path = root / "history.jsonl"
            state_path.write_text(
                json.dumps(self.legacy_state(), ensure_ascii=False), encoding="utf-8"
            )
            first = state_v024.migrate_state_file(
                state_path,
                history_path,
                root / "baseline-backups",
                atomic_writer=avatarctl.atomic_write_json,
                append_event=avatarctl.append_jsonl,
                now=lambda: "now",
            )
            second = state_v024.migrate_state_file(
                state_path,
                history_path,
                root / "baseline-backups",
                atomic_writer=avatarctl.atomic_write_json,
                append_event=avatarctl.append_jsonl,
                now=lambda: "later",
            )
            self.assertTrue(first[1])
            self.assertFalse(second[1])
            self.assertTrue(Path(first[2]).is_file())
            self.assertEqual(len(history_path.read_text().splitlines()), 1)

    def test_t7_generation_failure_rolls_back_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = copy.deepcopy(avatarctl.load_json(ROOT / "config.json"))
            config["runtime"]["state_dir"] = tmp
            paths = avatarctl.ensure_runtime(config)
            before = paths["state"].read_bytes()
            job_path = paths["jobs"] / "failure.json"
            avatarctl.atomic_write_json(
                job_path,
                {
                    "job_id": "failure",
                    "status": "queued",
                    "action": "render-transition",
                    "patch": {},
                    "transition": {
                        "transition_type": "new_scene",
                        "actions": [{"type": "move", "location": "图书馆"}],
                    },
                    "remember": "",
                    "say": "",
                    "channel": "test",
                    "no_send": True,
                },
            )
            with mock.patch.object(
                avatarctl, "submit_comfyui", side_effect=avatarctl.AvatarError("mock failure")
            ):
                with self.assertRaises(avatarctl.AvatarError):
                    avatarctl.run_generation_job(job_path, config)
            self.assertEqual(paths["state"].read_bytes(), before)
            self.assertFalse(paths["history"].exists())


if __name__ == "__main__":
    unittest.main()
