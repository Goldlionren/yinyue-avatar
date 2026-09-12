"""Hermes tool adapter for deterministic Yinyue image generation."""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path


SKILL_ROOT = Path(
    os.environ.get(
        "YINYUE_AVATAR_ROOT",
        str(Path.home() / ".hermes" / "skills" / "roleplay" / "yinyue-avatar"),
    )
).expanduser().resolve()
LIB_DIR = SKILL_ROOT / "lib"
_TURN_TTL_SECONDS = 900
_TURN_LOCK = threading.Lock()
_ACTIVE_TURNS: dict[str, dict] = {}
logger = logging.getLogger(__name__)
_MCP_COMMAND_RE = re.compile(
    r"^/(?:yinyue-avatar|yinyue_avatar)(?:@[A-Za-z0-9_]+)?\s+"
    r"mcp(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)

_SUCCESS_LEAD = "主人还满意吗？"
_SUCCESS_ATMOSPHERE_LINES = (
    "奴家一直在等着主人的目光呢~",
    "能被主人这样注视着，奴家心里很欢喜~",
    "主人若有新的吩咐，奴家还会乖乖照做的。",
    "若主人想换个角度，奴家随时听候吩咐~",
    "主人多看奴家一会儿，好不好~",
    "只要主人喜欢，奴家就觉得这一番准备都值得了~",
)


def _success_message() -> str:
    count = 1 + secrets.randbelow(2)
    lines = secrets.SystemRandom().sample(_SUCCESS_ATMOSPHERE_LINES, count)
    return "\n".join((_SUCCESS_LEAD, *lines))


def _is_yinyue_skill_turn(message: object) -> bool:
    text = str(message or "")
    return (
        '[IMPORTANT: The user has invoked the "yinyue-avatar" skill' in text
        or '[Loaded as part of the stacked skill invocation "yinyue-avatar"' in text
    )


def _is_yinyue_command(text: object) -> bool:
    first = str(text or "").lstrip().split(maxsplit=1)[0].lower()
    first = first.split("@", 1)[0]
    return first in {"/yinyue-avatar", "/yinyue_avatar"}


def _parse_mcp_command(*texts: object) -> tuple[str, str] | None:
    for value in texts:
        match = _MCP_COMMAND_RE.fullmatch(str(value or "").strip())
        if match:
            target = str(match.group(1) or "").strip()
            return ("set", target) if target else ("show", "")
    return None


def _avatarctl():
    if str(LIB_DIR) not in sys.path:
        sys.path.insert(0, str(LIB_DIR))
    return importlib.import_module("avatarctl")


def _format_mcp_target(result: dict) -> str:
    current = str(result.get("default_target", "")).removeprefix("comfy_")
    lines = [f"银月图片 MCP 当前选择：{current}", "", "可选节点："]
    readiness_labels = {
        "verified": "已验证",
        "runtime_preflight": "按需预检",
        "unavailable": "不可用",
    }
    for option in result.get("options", []):
        marker = "→" if option.get("selected") else " "
        readiness = readiness_labels.get(option.get("readiness"), "未知")
        lines.append(f"{marker} {option.get('label')}（{readiness}）")
    lines.extend(
        [
            "",
            "切换命令：",
            "/yinyue-avatar mcp 3060",
            "/yinyue-avatar mcp 4080s",
            "/yinyue-avatar mcp 5090",
            "",
            "选择只影响之后新建的图片事务；不会改变或重提已提交任务。",
            "5090/4080s 会在提交前按需检查主机、Workflow 和 slots；失败不会转发到其他节点。",
        ]
    )
    if result.get("updated"):
        lines.insert(1, "切换已保存；发送 mcp 3060 可随时回退。")
    return "\n".join(lines)


def _mcp_target_operation(operation: str, target: str) -> str:
    core = _avatarctl()
    config = core.load_config()
    result = core.cmd_mcp_target(config, target if operation == "set" else "")
    return _format_mcp_target(result)


async def _send_gateway_reply(gateway: object, source: object, message: str) -> None:
    try:
        adapter = gateway._adapter_for_source(source)
        if adapter is None:
            logger.warning("MCP target reply has no adapter")
            return
        metadata_fn = getattr(gateway, "_thread_metadata_for_source", None)
        metadata = metadata_fn(source) if callable(metadata_fn) else None
        try:
            await adapter.send(str(source.chat_id), message, metadata=metadata)
        except TypeError:
            await adapter.send(str(source.chat_id), message)
    except Exception:
        logger.warning("MCP target reply failed", exc_info=True)


async def _handle_mcp_command(
    gateway: object,
    source: object,
    session_key: str,
    operation: str,
    target: str,
) -> None:
    try:
        running = getattr(gateway, "_is_session_running", None)
        if operation == "set" and callable(running) and running(session_key):
            message = "当前 Session 仍有任务在运行；请等待完成后再切换图片 MCP。"
        else:
            message = await asyncio.to_thread(_mcp_target_operation, operation, target)
    except Exception as exc:
        logger.warning("MCP target command failed: %s", exc, exc_info=True)
        message = f"MCP 切换失败：{exc}"
    await _send_gateway_reply(gateway, source, message)



_EXPLICIT_VISUAL_PATTERNS = (
    r"(?:拍照|拍照片|拍相片|自拍)",
    r"(?:发|来)(?:一张|张)?(?:照片|相片|图片|自拍)(?:给我)?",
    r"(?:给我|让我)(?:看|看看)(?:一下)?你(?:现在)?(?:的)?(?:样子|模样|外观)",
    r"拍(?:一张|张)?你(?:现在)?(?:的)?(?:样子|模样)(?:给我看|让我看|看看)?",
    r"拍(?:一张|张)(?:\s*$|[，。！？,.!?]|给我|让我|看看|看)",
)


def _is_explicit_visual_request(text: object) -> bool:
    raw = str(text or "")
    if _is_yinyue_command(raw):
        return False
    return any(
        re.search(pattern, raw, re.IGNORECASE)
        for pattern in _EXPLICIT_VISUAL_PATTERNS
    )


def _on_pre_gateway_dispatch(**context):
    event = context.get("event")
    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", None)
    if platform != "telegram":
        return None
    current = getattr(event, "text", "")
    raw_message = getattr(event, "raw_message", None)
    raw = getattr(raw_message, "text", "") or getattr(raw_message, "caption", "")
    command = _parse_mcp_command(current, raw)
    if command is not None:
        gateway = context.get("gateway")
        authorized = getattr(gateway, "_is_user_authorized", None)
        if gateway is None or not callable(authorized):
            return None
        try:
            if authorized(source) is not True:
                return None
        except Exception:
            logger.warning("MCP target authorization check failed", exc_info=True)
            return None
        normalize = getattr(gateway, "_normalize_source_for_session_key", None)
        normalized_source = normalize(source) if callable(normalize) else source
        try:
            session_key = str(gateway._session_key_for_source(normalized_source))
            asyncio.get_running_loop().create_task(
                _handle_mcp_command(
                    gateway, normalized_source, session_key, command[0], command[1]
                )
            )
        except Exception:
            logger.warning("Could not schedule MCP target command", exc_info=True)
        return {"action": "skip", "reason": "yinyue-mcp-target-command"}
    if _is_yinyue_command(raw) and not _is_yinyue_command(current):
        return {"action": "rewrite", "text": str(raw)}
    return None


def _prune_turns(now: float) -> None:
    stale = [
        key for key, value in _ACTIVE_TURNS.items()
        if now - float(value.get("created", 0)) > _TURN_TTL_SECONDS
    ]
    for key in stale:
        _ACTIVE_TURNS.pop(key, None)


def _on_pre_llm_call(**context):
    session_id = str(context.get("session_id") or "")
    if not session_id:
        return None

    user_message = context.get("user_message")
    now = time.monotonic()

    with _TURN_LOCK:
        _prune_turns(now)

        if not _is_yinyue_skill_turn(user_message):
            _ACTIVE_TURNS.pop(session_id, None)
            return None

        visual_required = _is_explicit_visual_request(user_message)

        _ACTIVE_TURNS[session_id] = {
            "created": now,
            "task_id": str(context.get("task_id") or ""),
            "turn_id": str(context.get("turn_id") or ""),
            "called": False,
            "ok": None,
            "error": "",
            "visual_required": visual_required,
        }

    if visual_required:
        return {
            "context": (
                "Runtime boundary: this is an explicit image/photo request. "
                "You MUST call yinyue_avatar_generate exactly once before producing "
                "a natural-language answer. Do not merely describe posing for a photo. "
                "Do not claim a photo exists unless the tool succeeds. "
                "Pass the user's original visual request as intent. "
                "Use visual fields only for explicit persistent visual changes."
            )
        }

    return {
        "context": (
            "Runtime boundary: yinyue-avatar context is available, but that alone "
            "does not make image generation mandatory. If the current user request "
            "needs a new image, call yinyue_avatar_generate exactly once. Otherwise "
            "answer normally. Never claim that a new image exists or output a new "
            "image URL unless the generation tool was actually called successfully."
        )
    }


def _matching_turn(context: dict) -> dict | None:
    session_id = str(context.get("session_id") or "")
    turn_id = str(context.get("turn_id") or "")
    state = _ACTIVE_TURNS.get(session_id)
    if state is None:
        return None
    expected_turn = str(state.get("turn_id") or "")
    if expected_turn and turn_id and expected_turn != turn_id:
        return None
    return state


def _on_pre_tool_call(**context):
    with _TURN_LOCK:
        state = _matching_turn(context)
        tool_name = str(context.get("tool_name") or "")
        if state is None:
            if tool_name != "yinyue_avatar_generate":
                return None
            session_id = str(context.get("session_id") or "")
            if not session_id:
                return None
            state = {
                "created": time.monotonic(),
                "task_id": str(context.get("task_id") or ""),
                "turn_id": str(context.get("turn_id") or ""),
                "called": False,
                "ok": None,
                "error": "",
            }
            _ACTIVE_TURNS[session_id] = state
        if tool_name != "yinyue_avatar_generate":
            if not state.get("called"):
                if state.get("visual_required"):
                    return {
                        "action": "block",
                        "message": (
                            "BLOCKED: 当前是明确图片请求；本轮必须调用 "
                            "yinyue_avatar_generate，不得用其他工具替代。"
                        ),
                    }
                return None
            return {
                "action": "block",
                "message": (
                    "BLOCKED: 图片事务开始后只允许完成 "
                    "yinyue_avatar_generate；不得改用其他工具。"
                ),
            }
        if state.get("called"):
            return {
                "action": "block",
                "message": "BLOCKED: 本次视觉请求已经调用过生成工具，禁止重复生成。",
            }
        state["called"] = True
    return None


def _on_post_tool_call(**context):
    if str(context.get("tool_name") or "") != "yinyue_avatar_generate":
        return None
    raw = context.get("result")
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        payload = None
    with _TURN_LOCK:
        state = _matching_turn(context)
        if state is not None:
            state["ok"] = bool(isinstance(payload, dict) and payload.get("ok") is True)
            if isinstance(payload, dict):
                state["error"] = str(payload.get("error") or "")[:300]
    return None


def _transform_llm_output(**context):
    session_id = str(context.get("session_id") or "")
    with _TURN_LOCK:
        state = _ACTIVE_TURNS.get(session_id)
        if state is None:
            return None
        called = bool(state.get("called"))
        ok = state.get("ok")
    if not called:
        if bool(state.get("visual_required")):
            return (
                "检测到这是明确的拍照/发图请求，但本轮没有执行 "
                "yinyue_avatar_generate，因此没有生成或发送新照片。"
            )
        response = str(context.get("response_text") or "")
        false_image_claim = re.search(
            r"(?:file://\S+?\.(?:png|jpe?g|webp|gif)|https?://\S+?\.(?:png|jpe?g|webp|gif)(?:\?\S*)?|MEDIA:/\S+|(?:图片|照片|头像).{0,10}(?:已生成|生成好了|已发送|发给你)|(?:已生成|生成好了).{0,10}(?:图片|照片|头像))",
            response,
            re.IGNORECASE,
        )
        if false_image_claim:
            return "这次没有执行图片生成，因此没有新照片。请重新发送原命令。"
        return None
    if ok is True:
        return _success_message()
    return "这次图片生成没有成功，也没有发送新照片。请稍后重新发送原命令。"


def _on_post_llm_call(**context):
    session_id = str(context.get("session_id") or "")
    if session_id:
        with _TURN_LOCK:
            _ACTIVE_TURNS.pop(session_id, None)
    return None


def _executor():
    if str(LIB_DIR) not in sys.path:
        sys.path.insert(0, str(LIB_DIR))
    return importlib.import_module("mcp_executor")


def _handle_generate(args: dict, **_kwargs) -> str:
    try:
        from tools.registry import registry

        result = _executor().generate(
            args, lambda name, values: registry.dispatch(name, values)
        )
        transaction = result.get("transaction", {})
        return json.dumps(
            {
                "ok": True,
                "transaction_id": transaction.get("transaction_id", ""),
                "prompt_id": transaction.get("prompt_id", ""),
                "workflow_id": transaction.get("workflow_id", ""),
                "target": transaction.get("target", ""),
                "generation_status": transaction.get("generation_status", "completed"),
                "delivery_status": transaction.get("delivery_status", ""),
                "result_image": transaction.get("result_image", ""),
                "agent_action": "stop_silently",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "error": str(exc),
                "agent_action": "stop_no_retry",
            },
            ensure_ascii=False,
        )


VISUAL_PROPERTIES = {
    key: {"type": "string"}
    for key in (
        "outfit", "outerwear", "top", "bottom", "dress", "legwear",
        "footwear", "headwear", "accessories", "hair", "makeup",
        "expression", "pose", "action", "scene", "lighting", "camera",
    )
}

GENERATE_SCHEMA = {
    "name": "yinyue_avatar_generate",
    "description": (
        "Generate and deliver one Yinyue avatar image as a single deterministic "
        "transaction. Pass the user's original request as intent and only explicit "
        "visual state changes in visual. This tool owns all MCP steps; never call "
        "avatarctl/MCP manually before or after it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "visual": {
                "type": "object",
                "properties": VISUAL_PROPERTIES,
                "additionalProperties": False,
            },
            "say": {"type": "string"},
            "channel": {"type": "string"},
            "workflow": {"type": "string"},
            "target": {"type": "string"},
            "aspect_ratio": {"type": "string"},
            "megapixels": {"type": "number"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "no_send": {"type": "boolean", "default": False},
        },
        "required": ["intent"],
        "additionalProperties": False,
    },
}


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("transform_llm_output", _transform_llm_output)
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_tool(
        name="yinyue_avatar_generate",
        toolset="yinyue-avatar",
        schema=GENERATE_SCHEMA,
        handler=_handle_generate,
        emoji="🌙",
    )
