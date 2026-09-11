from __future__ import annotations

import copy
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
avatarctl = importlib.import_module("avatarctl")
executor = importlib.import_module("mcp_executor")


class FakeMCP:
    def __init__(self, image: Path):
        self.image = image
        self.calls: list[tuple[str, dict]] = []
        self.vary_slots: list[dict] = []
        self.wait_count = 0

    def __call__(self, name: str, args: dict) -> str:
        self.calls.append((name, copy.deepcopy(args)))
        tool = name.rsplit("__", 1)[-1]
        if tool == "server_info":
            payload = {"comfyui_running": True}
        elif tool == "vary_workflow":
            self.vary_slots = copy.deepcopy(args["slots"])
            payload = {
                "workflow": args["out_dir"] + r"\Krea2_YINYUE_cosplay01_000.json"
            }
        elif tool == "list_workflow_slots":
            payload = {
                "workflow": args["workflow_path"],
                "slots": [
                    {"address": item["address"], "current_value": item["values"][0]}
                    for item in self.vary_slots
                ],
            }
        elif tool == "run_workflow":
            payload = {"prompt_id": "c7d8842d-ac21-4752-8e83-ce8b4c66cb1b"}
        elif tool == "job":
            self.wait_count += 1
            payload = {
                "timed_out": self.wait_count == 1,
                "status": "running" if self.wait_count == 1 else "completed",
            }
        elif tool == "fetch_outputs":
            return json.dumps(
                {
                    "result": (
                        '{"saved_path":"D:\\\\AI\\\\YinyueAvatar\\\\out\\\\image.png"}'
                        f"\nMEDIA:{self.image}"
                    )
                }
            )
        else:
            return json.dumps({"error": f"unexpected tool: {name}"})
        return json.dumps({"result": json.dumps(payload, ensure_ascii=False)})


class MCPExecutorTests(unittest.TestCase):
    def ready_config(self, root: str) -> dict:
        config = avatarctl.load_json(ROOT / "config.json")
        config["runtime"]["state_dir"] = str(Path(root) / "state")
        config["telegram"]["enabled"] = False
        registry = avatarctl.load_json(ROOT / "registry/workflows.json")
        for workflow in registry["workflows"].values():
            for target in workflow["allowed_targets"]:
                workflow["target_status"][target].update(
                    workflow_exists=True, interface_verified=True, reason="test"
                )
        registry_path = Path(root) / "registry.json"
        avatarctl.atomic_write_json(registry_path, registry)
        config["execution"]["registry_path"] = str(registry_path)
        return config

    def test_generate_owns_complete_mcp_flow_and_submits_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.ready_config(tmp)
            image = Path(tmp) / "mcp.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            fake = FakeMCP(image)
            with mock.patch.object(executor.core, "load_config", return_value=config):
                result = executor.generate(
                    {
                        "intent": "换个姿势拍照",
                        "visual": {"pose": "跪在地上"},
                        "say": "test",
                        "no_send": True,
                    },
                    fake,
                )
            self.assertTrue(result["generation_committed"])
            names = [name.rsplit("__", 1)[-1] for name, _ in fake.calls]
            self.assertEqual(
                names,
                [
                    "server_info", "vary_workflow", "list_workflow_slots",
                    "run_workflow", "job", "job", "fetch_outputs",
                ],
            )
            self.assertEqual(names.count("run_workflow"), 1)
            transaction = result["transaction"]
            self.assertEqual(transaction["status"], "committed")
            self.assertEqual(transaction["submit_count"], 1)
            self.assertEqual(
                transaction["prompt_id"],
                "c7d8842d-ac21-4752-8e83-ce8b4c66cb1b",
            )

    def test_invalid_visual_field_fails_before_any_mcp_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.ready_config(tmp)
            fake = FakeMCP(Path(tmp) / "unused.png")
            with mock.patch.object(executor.core, "load_config", return_value=config):
                with self.assertRaises(executor.MCPExecutionError):
                    executor.generate(
                        {"intent": "拍照", "visual": {"underwear": ""}}, fake
                    )
            self.assertEqual(fake.calls, [])

    def test_new_request_resumes_bound_job_without_resubmit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.ready_config(tmp)
            image = Path(tmp) / "resume.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            prepared = avatarctl.cmd_prepare(
                config,
                intent="旧请求",
                patch={"visual.pose": "跪在地上"},
                requested_workflow="",
                requested_target="",
                aspect_ratio="",
                megapixels=None,
                width=None,
                height=None,
                say="test",
                channel="telegram",
                no_send=True,
            )
            transaction = prepared["transaction"]
            variant = transaction["variant_dir"] + r"\resume.json"
            observed = {
                "workflow": variant,
                "slots": [
                    {"address": item["address"], "current_value": item["value"]}
                    for item in transaction["slot_overrides"]
                ],
            }
            avatarctl.cmd_verify_variant(
                config,
                transaction["transaction_id"],
                variant,
                observed_slots_json=json.dumps(observed, ensure_ascii=False),
            )
            avatarctl.cmd_claim_submit(config, transaction["transaction_id"])
            avatarctl.cmd_bind(
                config,
                transaction["transaction_id"],
                "c7d8842d-ac21-4752-8e83-ce8b4c66cb1b",
            )
            fake = FakeMCP(image)
            with mock.patch.object(executor.core, "load_config", return_value=config):
                result = executor.generate(
                    {"intent": "另一个新请求", "visual": {"pose": "站立"}}, fake
                )
            names = [name.rsplit("__", 1)[-1] for name, _ in fake.calls]
            self.assertEqual(names, ["job", "job", "fetch_outputs"])
            self.assertNotIn("run_workflow", names)
            self.assertTrue(result["generation_committed"])

    def test_new_request_supersedes_unsubmitted_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.ready_config(tmp)
            image = Path(tmp) / "supersede.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            orphan = avatarctl.cmd_prepare(
                config,
                intent="同一要求拍照",
                patch={"visual.pose": "旧的错误姿势"},
                requested_workflow="",
                requested_target="",
                aspect_ratio="",
                megapixels=None,
                width=None,
                height=None,
                say="old",
                channel="telegram",
                no_send=True,
            )["transaction"]
            fake = FakeMCP(image)
            with mock.patch.object(executor.core, "load_config", return_value=config):
                result = executor.generate(
                    {
                        "intent": "同一要求拍照",
                        "visual": {"pose": "新的正确姿势"},
                        "no_send": True,
                    },
                    fake,
                )
            old = avatarctl.cmd_transaction_status(config, orphan["transaction_id"])
            self.assertEqual(old["status"], "aborted")
            self.assertEqual(
                old["abort_reason"],
                "superseded by deterministic single-tool request",
            )
            self.assertEqual(result["transaction"]["status"], "committed")
            names = [name.rsplit("__", 1)[-1] for name, _ in fake.calls]
            self.assertEqual(names.count("run_workflow"), 1)

    def test_plugin_registers_single_deterministic_tool(self) -> None:
        plugin_path = ROOT / "plugins" / "yinyue-visual" / "__init__.py"
        spec = importlib.util.spec_from_file_location("test_yinyue_visual_plugin", plugin_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        captured = []
        hooks = {}

        class Context:
            def register_tool(self, **kwargs):
                captured.append(kwargs)

            def register_hook(self, name, callback):
                hooks[name] = callback

        module.register(Context())
        self.assertEqual([item["name"] for item in captured], ["yinyue_avatar_generate"])
        self.assertEqual(captured[0]["toolset"], "yinyue-avatar")
        self.assertEqual(
            set(hooks),
            {
                "pre_gateway_dispatch",
                "pre_llm_call", "pre_tool_call", "post_tool_call",
                "transform_llm_output", "post_llm_call",
            },
        )

        restored = hooks["pre_gateway_dispatch"](
            event=SimpleNamespace(
                text="背景换成大街上，拍照给我",
                source=SimpleNamespace(platform=SimpleNamespace(value="telegram")),
                raw_message=SimpleNamespace(
                    text="/yinyue-avatar 背景换成大街上，拍照给我"
                ),
            )
        )
        self.assertEqual(restored["action"], "rewrite")
        self.assertTrue(restored["text"].startswith("/yinyue-avatar "))
        self.assertIsNone(hooks["pre_gateway_dispatch"](
            event=SimpleNamespace(
                text="普通聊天",
                source=SimpleNamespace(platform=SimpleNamespace(value="telegram")),
                raw_message=SimpleNamespace(text="普通聊天"),
            )
        ))

        marker = (
            '[IMPORTANT: The user has invoked the "yinyue-avatar" skill, '
            "indicating they want you to follow its instructions.]"
        )
        injected = hooks["pre_llm_call"](
            session_id="session-1", task_id="task-1", turn_id="turn-1",
            user_message=marker,
        )
        self.assertIn("yinyue_avatar_generate", injected["context"])
        discovery = hooks["pre_tool_call"](
            session_id="session-1", turn_id="turn-1", tool_name="terminal"
        )
        self.assertIsNone(discovery)
        self.assertIsNone(hooks["pre_tool_call"](
            session_id="session-1", turn_id="turn-1",
            tool_name="yinyue_avatar_generate",
        ))
        blocked = hooks["pre_tool_call"](
            session_id="session-1", turn_id="turn-1", tool_name="terminal"
        )
        self.assertEqual(blocked["action"], "block")
        duplicate = hooks["pre_tool_call"](
            session_id="session-1", turn_id="turn-1",
            tool_name="yinyue_avatar_generate",
        )
        self.assertEqual(duplicate["action"], "block")
        hooks["post_tool_call"](
            session_id="session-1", turn_id="turn-1",
            tool_name="yinyue_avatar_generate",
            result=json.dumps({"ok": False, "error": "fixture"}),
        )
        truthful = hooks["transform_llm_output"](
            session_id="session-1", platform="telegram",
            response_text="已经生成 https://example.com/old.png",
        )
        self.assertIn("没有发送新照片", truthful)
        self.assertNotIn("http", truthful)

        hooks["pre_llm_call"](
            session_id="session-2", task_id="task-2", turn_id="turn-2",
            user_message=marker,
        )
        no_call = hooks["transform_llm_output"](
            session_id="session-2", platform="telegram",
            response_text="给你看 https://example.com/old.png",
        )
        self.assertIn("没有执行图片生成", no_call)
        self.assertNotIn("http", no_call)
        hooks["post_llm_call"](session_id="session-2")

        hooks["pre_llm_call"](
            session_id="session-file", task_id="task-file", turn_id="turn-file",
            user_message=marker,
        )
        old_file = hooks["transform_llm_output"](
            session_id="session-file", platform="telegram",
            response_text="给你：![银月](file:///tmp/old.png)",
        )
        self.assertIn("没有执行图片生成", old_file)
        self.assertNotIn("file://", old_file)
        hooks["post_llm_call"](session_id="session-file")

        hooks["pre_llm_call"](
            session_id="session-3", task_id="task-3", turn_id="turn-3",
            user_message=marker,
        )
        normal_chat = hooks["transform_llm_output"](
            session_id="session-3", platform="telegram",
            response_text="我在这里，陪你慢慢聊。",
        )
        self.assertIsNone(normal_chat)
        hooks["post_llm_call"](session_id="session-3")

        # A visual transaction may start from on-demand Skill discovery even
        # when the turn did not begin with a slash-skill marker.
        self.assertIsNone(hooks["pre_tool_call"](
            session_id="session-4", task_id="task-4", turn_id="turn-4",
            tool_name="yinyue_avatar_generate",
        ))
        hooks["post_tool_call"](
            session_id="session-4", turn_id="turn-4",
            tool_name="yinyue_avatar_generate",
            result=json.dumps({"ok": True}),
        )
        confirmed = hooks["transform_llm_output"](
            session_id="session-4", platform="telegram", response_text="",
        )
        self.assertIn("确认生成并发送", confirmed)


if __name__ == "__main__":
    unittest.main()
