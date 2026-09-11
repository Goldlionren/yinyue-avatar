from __future__ import annotations

import base64
import copy
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("avatarctl_v030_tests", ROOT / "lib/avatarctl.py")
assert SPEC and SPEC.loader
avatarctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(avatarctl)
visual = avatarctl.visual_system


class VisualV030Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_config = avatarctl.load_json(ROOT / "config.json")

    def ready_environment(self, temp_root: str) -> tuple[dict, dict]:
        config = copy.deepcopy(self.base_config)
        config["runtime"]["state_dir"] = str(Path(temp_root) / "state")
        config["telegram"]["enabled"] = False
        registry = avatarctl.load_json(ROOT / "registry/workflows.json")
        for workflow in registry["workflows"].values():
            for target in workflow["allowed_targets"]:
                workflow["target_status"][target].update(
                    workflow_exists=True,
                    interface_verified=True,
                    reason="test fixture",
                )
        registry_path = Path(temp_root) / "workflows.json"
        registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
        config["execution"]["registry_path"] = str(registry_path)
        return config, registry

    def prepare(self, config: dict, intent: str, **kwargs):
        values = {
            "intent": intent,
            "patch": {},
            "requested_workflow": "",
            "requested_target": "",
            "aspect_ratio": "",
            "megapixels": None,
            "width": None,
            "height": None,
            "say": "test",
            "channel": "telegram",
            "no_send": True,
        }
        values.update(kwargs)
        return avatarctl.cmd_prepare(config, **values)

    def verify_and_claim(self, config: dict, prepared: dict) -> tuple[str, str]:
        transaction = prepared["transaction"]
        transaction_id = transaction["transaction_id"]
        variant_path = transaction["variant_dir"] + r"\Krea2_YINYUE_cosplay01_1.json"
        observed = {
            "workflow": variant_path,
            "slots": [
                {"address": item["address"], "current_value": item["value"]}
                for item in transaction["slot_overrides"]
            ],
        }
        avatarctl.cmd_verify_variant(
            config,
            transaction_id,
            variant_path,
            json.dumps(observed, ensure_ascii=False),
        )
        avatarctl.cmd_claim_submit(config, transaction_id)
        return transaction_id, variant_path

    def submit_and_complete(self, config: dict, prepared: dict, prompt_id: str = "prompt-one") -> tuple[str, str]:
        transaction_id, variant_path = self.verify_and_claim(config, prepared)
        avatarctl.cmd_bind(config, transaction_id, prompt_id)
        avatarctl.cmd_mark_completed(config, transaction_id, prompt_id)
        return transaction_id, variant_path

    def test_fresh_default_state_has_visual_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            paths = avatarctl.ensure_runtime(config)
            state = avatarctl.load_json(paths["state"])
            self.assertEqual(state["visual_system_version"], 1)
            self.assertIn("outerwear", state["visual"])
            self.assertIn("remote_images", state["continuity"])

    def test_existing_state_extension_migration_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            state_root = Path(config["runtime"]["state_dir"])
            state_root.mkdir(parents=True)
            old = avatarctl.load_json(ROOT / "defaults/state.default.json")
            old.pop("visual_system_version")
            for key in ("outerwear", "top", "bottom", "dress", "headwear", "accessories"):
                old["visual"].pop(key, None)
            for key in ("last_workflow_id", "last_target", "last_transaction_id", "remote_images", "delivery_status"):
                old["continuity"].pop(key, None)
            avatarctl.atomic_write_json(state_root / "state.json", old)
            avatarctl.ensure_runtime(config)
            avatarctl.ensure_runtime(config)
            events = avatarctl.tail_jsonl(state_root / "history.jsonl", 20)
            migrations = [item for item in events if item.get("event") == "visual_system_migration"]
            self.assertEqual(len(migrations), 1)
            self.assertTrue(Path(migrations[0]["backup"]).is_file())

    def test_registry_parses_and_unknown_workflow_fails(self) -> None:
        registry = visual.load_registry(ROOT / "registry/workflows.json")
        self.assertEqual(set(registry["workflows"]), {"yinyue_cosplay01", "yinyue_edit01"})
        with self.assertRaises(avatarctl.AvatarError):
            avatarctl.cmd_workflow_info(self.base_config, "missing")

    def test_production_registry_uses_both_sampler_seed_bindings(self) -> None:
        registry = visual.load_registry(ROOT / "registry/workflows.json")
        cosplay = registry["workflows"]["yinyue_cosplay01"]
        self.assertIn("seed", cosplay["input_roles"])
        seed_binding = cosplay["parameter_bindings"]["seed"]
        self.assertEqual(seed_binding["kind"], "workflow_slots")
        self.assertEqual(seed_binding["addresses"], ["92.noise_seed", "93.noise_seed"])

    def test_manifest_matches_current_business_bindings(self) -> None:
        manifest = avatarctl.load_json(ROOT / "manifests/yinyue_cosplay01.manifest.json")
        slots = manifest["slots"]
        self.assertEqual((slots["prompt"]["node_id"], slots["prompt"]["input_name"]), ("63", "value"))
        self.assertEqual((slots["aspect_ratio"]["node_id"], slots["aspect_ratio"]["input_name"]), ("49", "aspect_ratio"))
        self.assertEqual((slots["megapixels"]["node_id"], slots["megapixels"]["input_name"]), ("49", "megapixels"))
        self.assertEqual(
            [(item["node_id"], item["input_name"]) for item in slots["seed"]["addresses"]],
            [("92", "noise_seed"), ("93", "noise_seed")],
        )
        self.assertEqual((slots["seed"]["minimum"], slots["seed"]["maximum"]), (10_000_000, 99_999_999))

    def test_vary_workflow_sets_both_sampler_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            plan = self.prepare(config, "3:4，2MP，拍张现在的照片")["plan"]
            vary = next(item for item in plan["steps"] if item["step"] == "create_transaction_variant")
            addresses = {item["address"] for item in vary["arguments"]["slots"]}
            self.assertEqual(
                addresses,
                {"63.value", "49.aspect_ratio", "49.megapixels", "92.noise_seed", "93.noise_seed"},
            )

    def test_missing_workflow_target_is_not_selected(self) -> None:
        registry = avatarctl.load_json(ROOT / "registry/workflows.json")
        workflow = registry["workflows"]["yinyue_cosplay01"]
        workflow["target_status"]["comfy_3060"].update(
            workflow_exists=False,
            interface_verified=False,
            reason="test fixture missing workflow",
        )
        with self.assertRaises(visual.VisualSystemError):
            visual.select_target(
                registry, workflow, requested_target="comfy_3060", default_target="comfy_5090"
            )

    def test_router_distinguishes_show_regeneration_and_edit(self) -> None:
        self.assertEqual(visual.route_intent("给我看看你现在的样子")[0], "yinyue_cosplay01")
        self.assertEqual(visual.route_intent("今天换一身完整的新造型")[0], "yinyue_cosplay01")
        self.assertEqual(visual.route_intent("把外套脱了")[0], "yinyue_edit01")
        self.assertEqual(visual.route_intent("换个衣服")[0], "yinyue_edit01")
        self.assertEqual(visual.route_intent("换个动作")[0], "yinyue_edit01")

    def test_unavailable_edit_workflow_falls_back_and_keeps_change_in_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, registry = self.ready_environment(tmp)
            for target in registry["workflows"]["yinyue_edit01"]["allowed_targets"]:
                registry["workflows"]["yinyue_edit01"]["target_status"][target].update(
                    workflow_exists=False,
                    interface_verified=False,
                    reason="not deployed",
                )
            registry_path = Path(config["execution"]["registry_path"])
            registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
            result = self.prepare(config, "换个衣服")
            transaction = result["transaction"]
            self.assertEqual(transaction["workflow_id"], "yinyue_cosplay01")
            self.assertEqual(transaction["patch"], {})
            self.assertIn("换个衣服", transaction["parameters"]["prompt"])
            self.assertIn("最新要求为准", transaction["parameters"]["prompt"])

    def test_latest_clothing_and_pose_request_removes_conflicting_old_facts(self) -> None:
        state = avatarctl.load_json(ROOT / "defaults/state.default.json")
        prompt = visual.build_generation_prompt(
            state,
            intent="换个衣服，换个姿势",
            intent_class="full_regeneration_fallback",
        )
        self.assertTrue(prompt.startswith("【最高优先级：本次最新要求】换个衣服，换个姿势"))
        self.assertNotIn("浅蓝色丝质吊带裙", prompt)
        self.assertNotIn("站在卧室落地窗前", prompt)
        self.assertNotIn("看向镜头", prompt)
        self.assertIn("现代公寓卧室", prompt)
        self.assertIn("白色长发，狐狸耳朵", prompt)

    def test_latest_scene_request_preserves_old_clothing_and_pose(self) -> None:
        state = avatarctl.load_json(ROOT / "defaults/state.default.json")
        prompt = visual.build_generation_prompt(
            state,
            intent="换到海边拍照",
            intent_class="full_regeneration",
        )
        self.assertNotIn("现代公寓卧室", prompt)
        self.assertIn("浅蓝色丝质吊带裙", prompt)
        self.assertIn("站在卧室落地窗前", prompt)

    def test_explicit_new_state_is_shown_and_old_conflicts_are_omitted(self) -> None:
        state = avatarctl.load_json(ROOT / "defaults/state.default.json")
        state["visual"]["outfit"] = "红色西装套装"
        state["visual"]["pose"] = "双手叉腰"
        prompt = visual.build_generation_prompt(
            state,
            intent="换一身衣服，再换个姿势",
            intent_class="full_regeneration",
            changed_fields={"outfit", "pose"},
        )
        self.assertIn("【已解析的新状态】服装为红色西装套装；姿势为双手叉腰", prompt)
        self.assertNotIn("浅蓝色丝质吊带裙", prompt)
        self.assertNotIn("站在卧室落地窗前", prompt)
        self.assertIn("现代公寓卧室", prompt)

    def test_default_resolution_matches_current_3060_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            transaction = self.prepare(config, "拍张现在的照片")["transaction"]
            self.assertEqual(transaction["parameters"]["aspect_ratio"], "9:16")
            self.assertEqual(transaction["parameters"]["megapixels"], 1.5)
            overrides = {item["address"]: item["value"] for item in transaction["slot_overrides"]}
            self.assertEqual(overrides["49.aspect_ratio"], "9:16 (Portrait Widescreen)")
            self.assertEqual(overrides["49.megapixels"], 1.5)

    def test_missing_last_image_falls_back_to_cosplay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            result = self.prepare(config, "把外套脱了")
            self.assertEqual(result["transaction"]["workflow_id"], "yinyue_cosplay01")
            self.assertIn("安全回退", result["transaction"]["fallback_reason"])

    def test_partial_visual_update_only_changes_requested_field(self) -> None:
        state = avatarctl.load_json(ROOT / "defaults/state.default.json")
        before = copy.deepcopy(state)
        avatarctl.apply_patch(state, {"visual.headwear": "白色贝雷帽"})
        self.assertEqual(state["visual"]["headwear"], "白色贝雷帽")
        self.assertEqual(state["visual"]["outfit"], before["visual"]["outfit"])

    def test_edit_prompt_remove_outerwear(self) -> None:
        prompt = visual.transform_edit_prompt("把外套脱了")
        self.assertIn("去掉图中人物的外套", prompt)
        self.assertIn("其他一切保持不变", prompt)

    def test_remove_outerwear_updates_structured_and_legacy_views(self) -> None:
        state = avatarctl.load_json(ROOT / "defaults/state.default.json")
        state["appearance"]["outfit"]["outerwear"] = ["黑色外套"]
        state["visual"]["outerwear"] = "黑色外套"
        avatarctl.apply_patch(state, {"visual.outerwear": ""})
        avatarctl.sync_v2_from_legacy_patch(state, {"visual.outerwear": ""})
        self.assertEqual(state["visual"]["outerwear"], "")
        self.assertEqual(state["appearance"]["outfit"]["outerwear"], [])

    def test_edit_prompt_change_hat(self) -> None:
        prompt = visual.transform_edit_prompt("把帽子换成红色贝雷帽")
        self.assertIn("红色贝雷帽", prompt)
        self.assertIn("服装主体", prompt)

    def test_edit_prompt_change_hairstyle(self) -> None:
        prompt = visual.transform_edit_prompt("换成长卷发")
        self.assertIn("长卷发", prompt)
        self.assertIn("发型", prompt)

    def test_edit_prompt_change_pose(self) -> None:
        prompt = visual.transform_edit_prompt("把动作改成坐在床边")
        self.assertIn("坐在床边", prompt)
        self.assertIn("整体风格", prompt)

    def test_resolution_three_four_two_mp(self) -> None:
        self.assertEqual(
            visual.parse_resolution("3:4，2MP"),
            {"aspect_ratio": "3:4", "megapixels": 2},
        )

    def test_resolution_explicit_dimensions(self) -> None:
        self.assertEqual(
            visual.parse_resolution("1024x1536"),
            {"width": 1024, "height": 1536},
        )

    def test_explicit_dimensions_bind_to_supported_ratio_and_megapixels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            transaction = self.prepare(config, "1024x1536，拍张照片")["transaction"]
            self.assertEqual(transaction["parameters"]["aspect_ratio"], "2:3")
            self.assertEqual(transaction["parameters"]["megapixels"], 1.572864)
            overrides = {item["address"]: item["value"] for item in transaction["slot_overrides"]}
            self.assertEqual(overrides["49.aspect_ratio"], "2:3 (Portrait Tall)")
            self.assertEqual(overrides["49.megapixels"], 1.572864)

    def test_explicit_unsupported_dimensions_fail_instead_of_using_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            with self.assertRaisesRegex(avatarctl.AvatarError, "当前 Workflow 仅支持"):
                self.prepare(config, "1000x1400，拍张照片")

    def test_prepare_generates_one_eight_digit_seed_for_both_samplers_and_plan_is_240_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            with mock.patch.object(
                avatarctl.secrets,
                "randbelow",
                return_value=23_456_789,
            ):
                prepared = self.prepare(config, "拍张现在的照片", no_send=True)
            seed = prepared["transaction"]["parameters"]["seed"]
            self.assertEqual(seed, 33_456_789)
            self.assertEqual(prepared["transaction"]["requested_parameters"]["seed"], seed)
            self.assertNotIn("seed", prepared["plan"])
            vary = next(
                item for item in prepared["plan"]["steps"]
                if item["step"] == "create_transaction_variant"
            )
            seed_slots = {
                item["address"]: item["values"]
                for item in vary["arguments"]["slots"]
                if item["address"] in {"92.noise_seed", "93.noise_seed"}
            }
            self.assertEqual(seed_slots, {"92.noise_seed": [seed], "93.noise_seed": [seed]})
            self.assertEqual(prepared["plan"]["deadline_seconds"], 240)
            wait_step = next(item for item in prepared["plan"]["steps"] if item["step"] == "wait_bounded")
            self.assertEqual(wait_step["arguments"]["timeout_seconds"], 20)

    def test_transaction_creation_and_prepare_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            first = self.prepare(config, "给我看看你现在的样子")
            second = self.prepare(config, "给我看看你现在的样子")
            self.assertTrue(Path(config["runtime"]["state_dir"], "transactions", first["transaction"]["transaction_id"] + ".json").is_file())
            self.assertTrue(second["deduplicated"])
            self.assertEqual(first["transaction"]["transaction_id"], second["transaction"]["transaction_id"])

    def test_bound_prompt_cannot_be_changed_or_aborted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            result = self.prepare(config, "拍张现在的照片")
            transaction_id, _ = self.verify_and_claim(config, result)
            avatarctl.cmd_bind(config, transaction_id, "prompt-one")
            self.assertTrue(avatarctl.cmd_bind(config, transaction_id, "prompt-one")["idempotent"])
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_bind(config, transaction_id, "prompt-two")
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_abort(config, transaction_id, "must not abort")

    def test_recent_unbound_submit_claim_cannot_be_released(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction_id, _ = self.verify_and_claim(config, prepared)
            with self.assertRaisesRegex(avatarctl.AvatarError, "尚未超过 stale 阈值"):
                avatarctl.cmd_abort(config, transaction_id, "too recent")

    def test_stale_unbound_submit_claim_can_be_audit_released(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction_id, _ = self.verify_and_claim(config, prepared)
            paths = avatarctl.ensure_runtime(config)
            path = paths["transactions"] / f"{transaction_id}.json"
            transaction = avatarctl.load_json(path)
            transaction["created_epoch"] = (
                time.time() - int(config["runtime"]["job_stale_seconds"]) - 1
            )
            avatarctl.atomic_write_json(path, transaction)
            released = avatarctl.cmd_abort(config, transaction_id, "stale test claim")
            self.assertEqual(released["transaction"]["status"], "aborted")
            self.assertTrue(released["transaction"]["stale_submit_claim_released"])
            events = avatarctl.tail_jsonl(paths["history"], 10)
            event = next(item for item in events if item.get("event") == "transaction_aborted")
            self.assertTrue(event["possible_unbound_submission"])

    def test_duplicate_commit_does_not_increment_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片", no_send=True)
            transaction_id, _ = self.submit_and_complete(config, prepared)
            image = Path(tmp) / "mcp.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            first = avatarctl.cmd_commit(config, transaction_id, "prompt-one", str(image), r"F:\out\mcp.png")
            second = avatarctl.cmd_commit(config, transaction_id, "prompt-one", str(image), r"F:\out\mcp.png")
            self.assertTrue(first["generation_committed"])
            self.assertTrue(second["idempotent"])
            state = avatarctl.load_json(Path(config["runtime"]["state_dir"]) / "state.json")
            self.assertEqual(state["continuity"]["revision"], 1)

    def test_telegram_failure_never_creates_second_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片", no_send=False)
            transaction_id, _ = self.submit_and_complete(config, prepared)
            image = Path(tmp) / "mcp.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            with mock.patch.object(
                avatarctl,
                "deliver_text_and_media",
                return_value={"ok": False, "attempted": True, "error": "telegram down"},
            ):
                result = avatarctl.cmd_commit(config, transaction_id, "prompt-one", str(image), r"F:\out\mcp.png")
            self.assertTrue(result["generation_committed"])
            self.assertEqual(result["transaction"]["status"], "pending_delivery")
            files = list((Path(config["runtime"]["state_dir"]) / "transactions").glob("*.json"))
            self.assertEqual(len(files), 1)

    def test_transaction_id_and_prompt_id_are_semantically_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(
                config, "拍张现在的照片", requested_target="comfy_3060"
            )
            transaction_id, _ = self.verify_and_claim(config, prepared)
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_bind(config, transaction_id, transaction_id)

    def test_transaction_has_required_record_with_internal_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            transaction = self.prepare(config, "拍张现在的照片")["transaction"]
            self.assertRegex(str(transaction["requested_parameters"]["seed"]), r"^\d{8}$")
            self.assertEqual(transaction["prompt_id"], "")
            self.assertEqual(transaction["submit_count"], 0)
            for field in (
                "transaction_id", "created_at", "workflow_id", "target",
                "original_workflow_path", "variant_workflow_path",
                "requested_parameters", "prompt_id", "job_status",
                "result", "commit_status", "delivery_status",
            ):
                self.assertIn(field, transaction)

    def test_variant_path_differs_from_original_and_is_transaction_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction_id, variant_path = self.verify_and_claim(config, prepared)
            transaction = avatarctl.cmd_transaction_status(config, transaction_id)
            self.assertNotEqual(
                avatarctl._windows_path_key(transaction["original_workflow_path"]),
                avatarctl._windows_path_key(variant_path),
            )
            self.assertIn(transaction_id, variant_path)

    def test_original_workflow_is_never_modified_or_submitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction = prepared["transaction"]
            steps = prepared["plan"]["steps"]
            self.assertFalse(any(item.get("tool", "").endswith("set_workflow_slot") for item in steps))
            vary = next(item for item in steps if item["step"] == "create_transaction_variant")
            run = next(item for item in steps if item["step"] == "submit_variant_once")
            self.assertEqual(vary["arguments"]["workflow_path"], transaction["original_workflow_path"])
            self.assertEqual(run["arguments"]["workflow_path"], "$VARIANT_WORKFLOW_PATH")
            self.assertNotEqual(run["arguments"]["workflow_path"], transaction["original_workflow_path"])

    def test_variant_must_be_verified_before_submit_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            transaction = self.prepare(config, "拍张现在的照片")["transaction"]
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_claim_submit(config, transaction["transaction_id"])

    def test_variant_slot_mismatch_fails_closed_without_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "3:4，2MP，拍张现在的照片")
            transaction = prepared["transaction"]
            variant_path = transaction["variant_dir"] + r"\bad_1.json"
            observed = {
                "workflow": variant_path,
                "slots": [
                    {
                        "address": item["address"],
                        "current_value": "1:1 (Square)"
                        if item["address"] == "49.aspect_ratio" else item["value"],
                    }
                    for item in transaction["slot_overrides"]
                ],
            }
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_verify_variant(
                    config, transaction["transaction_id"], variant_path,
                    json.dumps(observed, ensure_ascii=False),
                )
            current = avatarctl.cmd_transaction_status(config, transaction["transaction_id"])
            self.assertEqual(current["status"], "planned")
            self.assertEqual(current["submit_count"], 0)
            self.assertEqual(current["prompt_id"], "")

    def test_sampler_seed_mismatch_fails_closed_without_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            transaction = self.prepare(config, "拍张现在的照片")["transaction"]
            variant_path = transaction["variant_dir"] + r"\bad-seed.json"
            observed = {
                "workflow": variant_path,
                "slots": [
                    {
                        "address": item["address"],
                        "current_value": (
                            item["value"] + 1
                            if item["address"] == "92.noise_seed" else item["value"]
                        ),
                    }
                    for item in transaction["slot_overrides"]
                ],
            }
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_verify_variant(
                    config,
                    transaction["transaction_id"],
                    variant_path,
                    json.dumps(observed, ensure_ascii=False),
                )
            current = avatarctl.cmd_transaction_status(config, transaction["transaction_id"])
            self.assertEqual(current["status"], "planned")
            self.assertEqual(current["submit_count"], 0)

    def test_one_transaction_has_at_most_one_submit_claim_and_run_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, registry = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction_id, _ = self.verify_and_claim(config, prepared)
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_claim_submit(config, transaction_id)
            claimed = avatarctl.cmd_transaction_status(config, transaction_id)
            resumed = visual.build_mcp_plan(claimed, registry)
            self.assertEqual(claimed["submit_count"], 1)
            self.assertFalse(any("run_workflow" in item.get("tool", "") for item in resumed["steps"]))

    def test_bound_prompt_forbids_resubmit_and_plan_has_no_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, registry = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction_id, _ = self.verify_and_claim(config, prepared)
            avatarctl.cmd_bind(config, transaction_id, "prompt-one")
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_bind(config, transaction_id, "prompt-two")
            submitted = avatarctl.cmd_transaction_status(config, transaction_id)
            resumed = visual.build_mcp_plan(submitted, registry)
            self.assertFalse(any("run_workflow" in item.get("tool", "") for item in resumed["steps"]))

    def test_generation_completed_has_no_post_generation_seed_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, registry = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction_id, _ = self.submit_and_complete(config, prepared)
            completed = avatarctl.cmd_transaction_status(config, transaction_id)
            plan = visual.build_mcp_plan(completed, registry)
            tools = [item.get("tool", "") for item in plan["steps"]]
            self.assertFalse(any(name.endswith(("vary_workflow", "list_workflow_slots", "run_workflow")) for name in tools))
            self.assertRegex(str(completed["parameters"]["seed"]), r"^\d{8}$")
            self.assertNotIn("seed", plan)

    def test_verify_variant_rejects_invalid_sampler_seed_slots(self) -> None:
        for value in (7, 7.0, 9.223372036854776e18, "not-an-integer"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                config, _ = self.ready_environment(tmp)
                prepared = self.prepare(config, "3:4，2MP，拍张现在的照片")
                transaction = prepared["transaction"]
                variant_path = transaction["variant_dir"] + r"\seed-ignored.json"
                slots = [
                    {"address": item["address"], "current_value": item["value"]}
                    for item in transaction["slot_overrides"]
                ]
                slots.extend([
                    {"address": "92.noise_seed", "current_value": value},
                    {"address": "93.noise_seed", "current_value": value},
                ])
                with self.assertRaisesRegex(
                    avatarctl.AvatarError, "variant slot verification mismatch"
                ):
                    avatarctl.cmd_verify_variant(
                        config,
                        transaction["transaction_id"],
                        variant_path,
                        json.dumps({"workflow": variant_path, "slots": slots}, ensure_ascii=False),
                    )
                current = avatarctl.cmd_transaction_status(
                    config, transaction["transaction_id"]
                )
                self.assertEqual(current["status"], "planned")
                self.assertEqual(current["submit_count"], 0)

    def test_verify_variant_accepts_filtered_utf8_base64(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction = prepared["transaction"]
            variant_path = transaction["variant_dir"] + r"\compact.json"
            payload = {
                "workflow": variant_path,
                "slots": [
                    {"address": item["address"], "current_value": item["value"]}
                    for item in transaction["slot_overrides"]
                ],
            }
            encoded = base64.b64encode(
                json.dumps(payload, ensure_ascii=False).encode("utf-8")
            ).decode("ascii")
            result = avatarctl.cmd_verify_variant(
                config,
                transaction["transaction_id"],
                variant_path,
                observed_slots_base64=encoded,
            )
            self.assertTrue(result["transaction"]["variant_verification"]["matched"])

    def test_verify_variant_rejects_ambiguous_or_invalid_encodings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片")
            transaction = prepared["transaction"]
            variant_path = transaction["variant_dir"] + r"\compact.json"
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_verify_variant(
                    config, transaction["transaction_id"], variant_path
                )
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_verify_variant(
                    config,
                    transaction["transaction_id"],
                    variant_path,
                    observed_slots_json="{}",
                    observed_slots_base64="e30=",
                )
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_verify_variant(
                    config,
                    transaction["transaction_id"],
                    variant_path,
                    observed_slots_base64="not-base64",
                )

    def test_windows_result_path_is_rejected(self) -> None:
        with self.assertRaises(avatarctl.AvatarError):
            avatarctl.verified_local_image(r"D:\mnt\data_nvme\yinyue_outputs\x.png")

    def test_linux_media_path_must_exist_be_readable_and_nonempty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "valid.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            path, data, suffix = avatarctl.verified_local_image(f"MEDIA:{image}")
            self.assertEqual(path, image.resolve())
            self.assertGreater(len(data), 0)
            self.assertEqual(suffix, ".png")
            empty = Path(tmp) / "empty.png"
            empty.write_bytes(b"")
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.verified_local_image(str(empty))

    def test_completed_without_local_image_does_not_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片", no_send=True)
            transaction_id, _ = self.submit_and_complete(config, prepared)
            with self.assertRaises(avatarctl.AvatarError):
                avatarctl.cmd_commit(config, transaction_id, "prompt-one", str(Path(tmp) / "missing.png"), "")
            state = avatarctl.load_json(Path(config["runtime"]["state_dir"]) / "state.json")
            transaction = avatarctl.cmd_transaction_status(config, transaction_id)
            self.assertEqual(state["continuity"]["revision"], 0)
            self.assertEqual(transaction["commit_status"], "not_committed")

    def test_successful_commit_sets_continuity_and_increments_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            prepared = self.prepare(config, "拍张现在的照片", no_send=True)
            transaction_id, _ = self.submit_and_complete(config, prepared)
            image = Path(tmp) / "mcp.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            result = avatarctl.cmd_commit(config, transaction_id, "prompt-one", f"MEDIA:{image}", r"D:\remote\x.png")
            state = avatarctl.load_json(Path(config["runtime"]["state_dir"]) / "state.json")
            self.assertTrue(result["generation_committed"])
            self.assertEqual(state["continuity"]["revision"], 1)
            self.assertEqual(state["continuity"]["last_workflow_id"], "yinyue_cosplay01")
            self.assertEqual(state["continuity"]["last_target"], prepared["transaction"]["target"])
            self.assertEqual(state["continuity"]["last_prompt_id"], "prompt-one")
            self.assertEqual(state["continuity"]["last_transaction_id"], transaction_id)
            self.assertTrue(Path(state["continuity"]["last_image"]).is_file())
            self.assertFalse(state["continuity"]["last_image"].startswith("D:"))
            history = avatarctl.tail_jsonl(Path(config["runtime"]["state_dir"]) / "history.jsonl", 20)
            committed = next(item for item in history if item.get("event") == "transaction_committed")
            self.assertNotIn("seed", committed)
            self.assertNotIn("seed", committed["requested_parameters"])

    def test_run_workflow_is_async_and_deadline_is_240(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            plan = self.prepare(config, "拍张现在的照片")["plan"]
            run = next(item for item in plan["steps"] if item["step"] == "submit_variant_once")
            wait = next(item for item in plan["steps"] if item["step"] == "wait_bounded")
            self.assertIs(run["arguments"]["wait"], False)
            self.assertNotIn("timeout_seconds", run["arguments"])
            self.assertEqual(wait["arguments"]["timeout_seconds"], 20)
            self.assertEqual(plan["deadline_seconds"], 240)
            verify = next(item for item in plan["steps"] if item["step"] == "verify_transaction_variant")
            self.assertIn("--observed-slots-base64", verify["command"])
            self.assertEqual(verify["serialization"], "filtered_json_utf8_base64")
            self.assertEqual(
                plan["interaction"]["intermediate_assistant_messages"],
                "roleplay_only_max_2",
            )
            self.assertFalse(plan["interaction"]["technical_progress"])

    def test_skill_forbids_unsafe_generation_fallbacks(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for forbidden in ("terminal", "SSH", "generate_image", "launch_comfyui", "raw Comfy MCP"):
            self.assertIn(forbidden, text)
        self.assertIn("失败也不得重复生成", text)
        self.assertIn("不得调用 `avatarctl prepare`", text)

    def test_skill_keeps_roleplay_but_hides_technical_progress(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("最多发送两段", text)
        self.assertIn("旁白只写情绪、期待和互动", text)
        self.assertIn("不得在每一步之间重复", text)
        self.assertIn("同一用户请求只允许一次 `yinyue_avatar_generate`", text)
        self.assertIn("工具返回成功后立即以空响应结束", text)
        self.assertNotIn("--observed-slots-base64", text)

    def test_existing_v032_transaction_is_read_compatibly(self) -> None:
        old = {
            "transaction_id": "a" * 32,
            "schema_version": 2,
            "status": "planned",
            "workflow_path": r"D:\AI\old.json",
            "parameters": {"prompt": "old", "seed": 123},
            "seed": 123,
            "prompt_id": "",
            "delivery": {"status": "not_attempted"},
        }
        current = avatarctl.normalize_transaction_v032(old)
        self.assertEqual(current["original_workflow_path"], old["workflow_path"])
        self.assertEqual(current["seed"], 123)
        self.assertEqual(current["submit_count"], 0)
        self.assertEqual(current["commit_status"], "not_committed")
        self.assertEqual(old["schema_version"], 2)

    def test_existing_v032_seed_override_is_filtered_from_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, registry = self.ready_environment(tmp)
            transaction = self.prepare(config, "3:4，2MP，拍张现在的照片")["transaction"]
            transaction["seed"] = 123.0
            transaction["parameters"]["seed"] = 123.0
            transaction["slot_overrides"].append(
                {"address": "111.seed", "value": 123.0}
            )
            plan = visual.build_mcp_plan(transaction, registry)
            vary = next(item for item in plan["steps"] if item["step"] == "create_transaction_variant")
            addresses = {item["address"] for item in vary["arguments"]["slots"]}
            self.assertEqual(
                addresses,
                {"63.value", "49.aspect_ratio", "49.megapixels", "92.noise_seed", "93.noise_seed"},
            )
            self.assertNotIn("111.seed", addresses)
            self.assertNotIn("seed", plan)

    def test_unsubmitted_v032_seed_transaction_does_not_reenter_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, _ = self.ready_environment(tmp)
            paths = avatarctl.ensure_runtime(config)
            old_id = "b" * 32
            avatarctl.atomic_write_json(
                paths["transactions"] / f"{old_id}.json",
                {
                    "transaction_id": old_id,
                    "schema_version": 2,
                    "status": "planned",
                    "target": "comfy_3060",
                    "fingerprint": "legacy-fingerprint",
                    "parameters": {"prompt": "legacy", "seed": 123.0},
                    "seed": 123.0,
                    "prompt_id": "",
                    "submit_count": 0,
                },
            )
            prepared = self.prepare(
                config, "拍张现在的照片", requested_target="comfy_3060"
            )
            self.assertFalse(prepared["deduplicated"])
            self.assertNotEqual(prepared["transaction"]["transaction_id"], old_id)
            self.assertRegex(
                str(prepared["transaction"]["requested_parameters"]["seed"]), r"^\d{8}$"
            )
            preserved = avatarctl.load_json(paths["transactions"] / f"{old_id}.json")
            self.assertEqual(preserved["seed"], 123.0)
            self.assertEqual(preserved["status"], "planned")

    def test_direct_http_legacy_mode_has_no_sha_gate(self) -> None:
        config = copy.deepcopy(self.base_config)
        config["execution"]["mode"] = "direct_http"
        path, workflow = avatarctl.validate_workflow(config)
        self.assertTrue(path.is_file())
        self.assertIn(config["workflow"]["prompt_node_id"], workflow)
        self.assertNotIn("masked_sha256", config["workflow"])

    def test_skill_runtime_has_no_other_skill_dependency(self) -> None:
        runtime_files = [ROOT / "SKILL.md", ROOT / "lib/avatarctl.py", ROOT / "lib/visual_v030.py", ROOT / "config.json"]
        text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
        self.assertNotIn("skills/roleplay/tavern", text)
        self.assertNotIn("telegram-media-sender", text)
        self.assertNotIn("comfyui-production-operator", text)


if __name__ == "__main__":
    unittest.main()
