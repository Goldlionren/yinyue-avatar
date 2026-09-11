# Architecture

## 数据流

```text
Telegram → Hermes Agent → yinyue_avatar_generate（唯一一次工具调用）
  → deterministic executor → avatarctl prepare
    → intent router → prompt transformer → workflow registry
    → vary immutable original → verify transaction variant → claim one submit
    → run variant once → bind(prompt_id) → bounded polling → fetch_outputs(inline)
    → Hermes local MEDIA cache → commit state/history → Telegram delivery
```

Hermes Agent 只负责理解用户意图并提交一份结构化请求；它看不到、也不参与中间 MCP 步骤，因此不能在步骤之间调用 help、terminal、execute_code 或重新猜测命令。角色氛围旁白仍由 Agent 在工具调用前发送，技术执行进度不进入 Telegram。

`yinyue-avatar` 是独立 Skill。persona、state helper、router、prompt rules、registry、schemas、migration、tests 和 docs 全在本目录；运行时不读取其他 Skill。

## 组件

- `lib/avatarctl.py`：CLI、锁、state/history、transaction、commit/delivery、legacy HTTP。
- `lib/mcp_executor.py`：确定性执行完整 MCP transaction；提交后只允许恢复同一个 prompt_id。
- `lib/visual_v030.py`：registry 校验、意图路由、编辑 prompt、分辨率解析、target 选择、MCP plan。
- `plugins/yinyue-visual/`：向 Hermes 注册唯一的生产工具 `yinyue_avatar_generate`。
- `registry/workflows.json`：Workflow、target、远端路径、capability、semantic slot binding 和 readiness。
- `~/.hermes/state/yinyue-avatar/transactions/`：每个 MCP transaction 的完整恢复记录。

## Router

`show_current` 和 `full_regeneration` 路由到 `yinyue_cosplay01`。明确的局部动作、衣物、帽子、发型、姿势、表情和物体修改路由到 `yinyue_edit01`。局部编辑必须同时具备 Hermes 本地 `last_image` 和所选 target 的 `continuity.remote_images[target]`；缺少时安全回退 cosplay。

## Parameter binding

MCP `run_workflow` 只接受 workflow path。生产原文件不可变；executor 调用 `vary_workflow` 把 registry 的业务参数写入 transaction 专属 frontend variant。随后以 `list_workflow_slots` 的实际值与 transaction prompt/resolution 完整比对，才可消费唯一 submit claim。Agent 不读 node graph、不写原 Workflow，也不手工编排 MCP。

## Output and continuity

`fetch_outputs` 的磁盘副本位于 MCP Windows 主机，只作 remote metadata；`inline_images=true` 同时返回 MCP ImageContent。Hermes runtime 把 ImageContent 缓存成 Linux MEDIA 文件。`commit` 明确拒绝 Windows/相对/缺失/不可读/空文件，只把验证后的 Linux 图片复制到 production output。

## Transaction invariants

- transaction_id 在 submit 前生成；采样随机性由 GPU Workflow 自己负责，不进入 MCP control plane。
- variant 必须不同于 original，并位于 transaction 专属目录。
- variant slots 未验证时不能 claim；claim 后任何 plan 都不再包含 run_workflow。
- 一次 transaction 的 submit_count 最大为 1；prompt_id 与 transaction_id 不得复用。
- `bind` 后 target/workflow/variant/prompt_id 不可改变。
- job timeout/fetch failure 不能创建新 job。
- commit 幂等，duplicate commit 不增加 revision。
- state 在生成期间变化会产生 `state_conflict`，保留结果但不覆盖新 state。
- delivery 在 state commit 之后；Telegram failure 只能 resend。

## Backend boundary

MCP 是默认 backend。direct HTTP 代码仍在 `avatarctl.py`，只在管理员预先设置 `execution.mode=direct_http` 时启用。一个 transaction 内没有自动 backend fallback。
