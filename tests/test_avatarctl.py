from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("avatarctl_module", ROOT / "lib/avatarctl.py")
assert SPEC and SPEC.loader
avatarctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(avatarctl)


class AvatarCtlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = avatarctl.load_json(ROOT / "config.json")

    def test_workflow_validation_checks_interface_not_sha(self) -> None:
        workflow = avatarctl.load_json(ROOT / self.config["workflow"]["path"])
        workflow["82"]["inputs"]["lora_name"] = "user-can-change-this.safetensors"
        with mock.patch.object(avatarctl, "load_json", return_value=workflow):
            path, checked = avatarctl.validate_workflow(self.config)
        self.assertTrue(path.name.endswith(".json"))
        self.assertEqual(checked["82"]["inputs"]["lora_name"], "user-can-change-this.safetensors")

    def test_only_prompt_and_legacy_seed_generator_are_dynamic(self) -> None:
        original = avatarctl.load_json(ROOT / self.config["workflow"]["path"])
        changed = copy.deepcopy(original)
        avatarctl.apply_legacy_workflow_parameters(
            changed,
            self.config["workflow"],
            prompt="new prompt",
            seed=12345,
        )

        expected = copy.deepcopy(original)
        expected["63"]["inputs"]["value"] = "new prompt"
        expected["85"]["inputs"]["seed"] = 12345
        self.assertEqual(changed, expected)
        self.assertEqual(changed["85"]["inputs"]["seed"], 12345)

    def test_legacy_seed_is_always_eight_digits(self) -> None:
        with mock.patch.object(avatarctl.secrets, "randbelow", return_value=0):
            low = avatarctl.random_eight_digit_seed()
        with mock.patch.object(avatarctl.secrets, "randbelow", return_value=89_999_999):
            high = avatarctl.random_eight_digit_seed()
        self.assertEqual(low, 10_000_000)
        self.assertEqual(high, 99_999_999)

    def test_reject_unknown_state_field(self) -> None:
        with self.assertRaises(avatarctl.AvatarError):
            avatarctl.parse_set_values(["visual.unknown=value"], self.config)

    def test_parse_set_values_expands_semicolon_joined_assignments(self) -> None:
        patch = avatarctl.parse_set_values(
            [
                'visual.outerwear=;visual.top=红色上衣;'
                'visual.pose="双手叉腰"'
            ],
            self.config,
        )
        self.assertEqual(
            patch,
            {
                "visual.outerwear": "",
                "visual.top": "红色上衣",
                "visual.pose": "双手叉腰",
            },
        )

    def test_parse_set_values_accepts_repeated_empty_visual_assignments(self) -> None:
        patch = avatarctl.parse_set_values(
            ["visual.outerwear=;visual.top=;visual.bottom=;visual.dress="],
            self.config,
        )
        self.assertEqual(
            patch,
            {
                "visual.outerwear": "",
                "visual.top": "",
                "visual.bottom": "",
                "visual.dress": "",
            },
        )

    def test_parse_set_values_rejects_unparsed_embedded_assignment(self) -> None:
        with self.assertRaisesRegex(avatarctl.AvatarError, "未解析的状态赋值"):
            avatarctl.parse_set_values(
                ["visual.outerwear=错误 visual.pose=坐下"],
                self.config,
            )

    def test_apply_patch_is_minimal(self) -> None:
        state = avatarctl.load_json(ROOT / "defaults/state.default.json")
        before = copy.deepcopy(state)
        changes = avatarctl.apply_patch(
            state,
            {"visual.footwear": "白色低帮运动鞋", "visual.pose": "坐在床边"},
        )
        self.assertEqual(len(changes), 2)
        self.assertEqual(state["visual"]["outfit"], before["visual"]["outfit"])
        self.assertEqual(state["visual"]["footwear"], "白色低帮运动鞋")

    def test_wardrobe_status_and_update_are_structured_persistent_and_no_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = copy.deepcopy(self.config)
            config["runtime"]["state_dir"] = str(Path(tmp) / "state")
            before = avatarctl.cmd_wardrobe_status(config)
            result = avatarctl.cmd_wardrobe_update(
                config,
                {
                    "连衣裙": "黑色丝绒连衣裙",
                    "袜子": "黑色丝袜",
                    "配饰": "",
                },
            )
            after = avatarctl.cmd_wardrobe_status(config)
        self.assertTrue(result["changed"])
        self.assertEqual(after["revision"], before["revision"] + 1)
        self.assertEqual(after["clothing"]["dress"], "黑色丝绒连衣裙")
        self.assertEqual(after["clothing"]["legwear"], "黑色丝袜")
        self.assertEqual(after["clothing"]["outfit"], "")
        self.assertEqual(after["clothing"]["accessories"], "")
        self.assertFalse(any(Path(tmp).glob("state/transactions/*.json")))

    def test_wardrobe_update_rejects_unknown_and_non_string_values(self) -> None:
        with self.assertRaisesRegex(avatarctl.AvatarError, "不允许修改穿着字段"):
            avatarctl.normalize_wardrobe_changes({"pose": "站立"})
        with self.assertRaisesRegex(avatarctl.AvatarError, "必须是字符串"):
            avatarctl.normalize_wardrobe_changes({"footwear": 123})

    def test_wardrobe_base_clothing_forms_clear_stale_alternatives(self) -> None:
        self.assertEqual(
            avatarctl.normalize_wardrobe_changes({"dress": "红裙"}),
            {"dress": "红裙", "outfit": "", "top": "", "bottom": ""},
        )
        self.assertEqual(
            avatarctl.normalize_wardrobe_changes({"outfit": "运动套装"}),
            {"outfit": "运动套装", "top": "", "bottom": "", "dress": ""},
        )

    def test_mcp_target_switch_is_atomic_preserves_local_config_and_keeps_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_path = root / "config.local.json"
            local = {
                "telegram": {"default_channel": "telegram:test"},
                "execution": {"mode": "mcp"},
            }
            avatarctl.atomic_write_json(local_path, local)
            config = avatarctl.deep_merge(self.config, local)
            config["runtime"]["state_dir"] = str(root / "state")
            with mock.patch.object(avatarctl, "LOCAL_CONFIG_PATH", local_path):
                before = avatarctl.cmd_mcp_target(config)
                result = avatarctl.cmd_mcp_target(config, "5090")
            saved = avatarctl.load_json(local_path)
            backups = list((root / "state/config-backups").glob("*.json"))
            backup_value = avatarctl.load_json(backups[0])

        self.assertEqual(before["default_target"], "comfy_3060")
        self.assertEqual(result["default_target"], "comfy_5090")
        self.assertEqual(result["previous_target"], "comfy_3060")
        self.assertTrue(result["updated"])
        self.assertEqual(saved["telegram"]["default_channel"], "telegram:test")
        self.assertEqual(saved["execution"]["mode"], "mcp")
        self.assertEqual(saved["execution"]["default_target"], "comfy_5090")
        self.assertEqual(len(backups), 1)
        self.assertEqual(backup_value, local)

    def test_mcp_target_rejects_unknown_value_without_changing_local_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "config.local.json"
            avatarctl.atomic_write_json(local_path, {"execution": {"mode": "mcp"}})
            before = local_path.read_bytes()
            config = copy.deepcopy(self.config)
            config["runtime"]["state_dir"] = str(Path(tmp) / "state")
            with mock.patch.object(avatarctl, "LOCAL_CONFIG_PATH", local_path):
                with self.assertRaisesRegex(avatarctl.AvatarError, "可选值"):
                    avatarctl.cmd_mcp_target(config, "4090")
            self.assertEqual(local_path.read_bytes(), before)

    def test_mcp_target_same_selection_is_a_noop_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "config.local.json"
            avatarctl.atomic_write_json(
                local_path,
                {"execution": {"mode": "mcp", "default_target": "comfy_3060"}},
            )
            before = local_path.read_bytes()
            config = copy.deepcopy(self.config)
            config["runtime"]["state_dir"] = str(Path(tmp) / "state")
            with mock.patch.object(avatarctl, "LOCAL_CONFIG_PATH", local_path):
                result = avatarctl.cmd_mcp_target(config, "3060")
            self.assertEqual(local_path.read_bytes(), before)
            self.assertFalse(result["updated"])
            self.assertEqual(result["backup"], "")
            self.assertFalse((Path(tmp) / "state/config-backups").exists())

    def test_mcp_target_cli_accepts_show_and_three_short_names(self) -> None:
        parser = avatarctl.build_parser()
        self.assertEqual(parser.parse_args(["mcp-target"]).target, "")
        for target in ("3060", "4080s", "5090"):
            self.assertEqual(parser.parse_args(["mcp-target", target]).target, target)

    def test_delivery_sends_text_and_media_separately(self) -> None:
        calls: list[str] = []

        def fake_send(cli, channel, message, config):
            calls.append(message)
            return {"ok": True, "attempts": []}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            avatarctl, "run_send_with_retry", side_effect=fake_send
        ):
            image = Path(tmp) / "x.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            result = avatarctl.deliver_text_and_media(
                say="我现在就拍给你看。",
                image=image,
                channel="telegram",
                config=self.config,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0], "我现在就拍给你看。")
        self.assertEqual(calls[1], f"MEDIA:{image.resolve()}")
        self.assertEqual(len(calls), 2)

    def test_resolve_hermes_cli_falls_back_to_user_local_bin_without_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            executable = home / ".local/bin/hermes"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with mock.patch.object(avatarctl.shutil, "which", return_value=None), mock.patch.object(
                avatarctl.Path, "home", return_value=home
            ):
                resolved = avatarctl.resolve_hermes_cli(self.config)
        self.assertEqual(resolved, str(executable))

    def test_missing_hermes_cli_is_a_delivery_failure_not_worker_exception(self) -> None:
        with mock.patch.object(
            avatarctl.subprocess,
            "run",
            side_effect=FileNotFoundError(2, "No such file or directory", "hermes"),
        ):
            result = avatarctl.run_send_once("hermes", "telegram", "hello", 5)
        self.assertFalse(result["ok"])
        self.assertIn("无法启动 hermes send", result["error"])
        self.assertIn("No such file or directory", result["stderr"])

    def test_resend_with_missing_worker_path_becomes_pending_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = copy.deepcopy(self.config)
            config["runtime"]["state_dir"] = tmp
            config["telegram"]["hermes_cli"] = str(Path(tmp) / "missing-hermes")
            config["telegram"]["send_retries"] = 1
            paths = avatarctl.ensure_runtime(config)
            image = paths["output"] / "last.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            state = avatarctl.load_json(ROOT / "defaults/state.default.json")
            state["continuity"]["last_image"] = str(image)
            avatarctl.atomic_write_json(paths["state"], state)
            job_path = paths["jobs"] / "missing-cli.json"
            avatarctl.atomic_write_json(
                job_path,
                {
                    "job_id": "missing-cli",
                    "action": "resend-last",
                    "status": "queued",
                    "say": "",
                    "channel": "telegram",
                },
            )

            avatarctl.run_resend_job(job_path, config)

            job = avatarctl.load_json(job_path)
            self.assertEqual(job["status"], "pending_delivery")
            self.assertFalse(job["result"]["delivery"]["ok"])
            self.assertTrue(Path(job["pending_file"]).is_file())

    def test_queue_deduplicates_running_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = copy.deepcopy(self.config)
            config["runtime"]["state_dir"] = tmp
            request = {
                "action": "show",
                "patch": {},
                "say": "我现在就拍给你看。",
                "remember": "",
                "channel": "telegram",
                "no_send": True,
            }
            with mock.patch.object(
                avatarctl, "launch_worker", return_value={"launcher": "test"}
            ):
                first = avatarctl.queue_job(copy.deepcopy(request), config)
                second = avatarctl.queue_job(copy.deepcopy(request), config)
            self.assertTrue(first["queued"])
            self.assertTrue(second["deduplicated"])
            self.assertEqual(first["job_id"], second["job_id"])
            self.assertEqual(second["agent_action"], "stop_silently")

    def test_show_say_is_optional(self) -> None:
        parser = avatarctl.build_parser()
        args = parser.parse_args(["show"])
        self.assertEqual(args.say, "")
        self.assertFalse(args.foreground)

    def test_prompt_is_deterministic_state_serialization(self) -> None:
        state = avatarctl.load_json(ROOT / "defaults/state.default.json")
        prompt = avatarctl.serialize_visual_prompt(state)
        self.assertIn("浅蓝色丝质吊带裙", prompt)
        self.assertIn("白色长发，狐狸耳朵", prompt)
        self.assertNotIn("masterpiece", prompt)


if __name__ == "__main__":
    unittest.main()
