# Troubleshooting

## doctor 报 no workflow ready

这是 fail-closed readiness，不是 hash 问题。运行 `avatarctl workflows` 查看每个 workflow@target 原因；用真实 MCP `list_workflow_slots` 和 `validate_workflow` 验证后再更新 registry status。

API export 出现 `workflow_not_frontend_format` 时，在 ComfyUI 用 `File > Save (As)` 保存 frontend format。不要伪造 slot address。

## 5090 不可达

保持其 `interface_verified=false`。Router 只会选择 registry 中已验证的其他 target；若没有则明确失败，不会盲跑。检查主机路由/SSH/MCP 后重新执行 server_info 和 workflow inspection。

## 已有 prompt_id 后超时

查询：

```bash
avatarctl transaction-status TRANSACTION_ID
```

只对绑定的 target/prompt_id 调用 `job(status|wait|watch)`。每次 wait 20 秒，总 deadline 240 秒。不要 run_workflow、prepare、换 GPU 或切 direct HTTP。

## fetch_outputs 临时失败

用相同 prompt_id 重试 fetch。必须 `inline_images=true`；Hermes tool result 中必须出现 `MEDIA:/absolute/linux/path`。Windows `D:\...` saved path 只能传 `--remote-result-image`，不能传 `--result-image` 或写入 last_image。没有 Linux MEDIA 文件就停止且不 commit。

## variant slot mismatch

`verify-variant` 会列出 expected/observed mismatch 并 fail closed。不要修改原 Workflow，不要 set-slot，不要 run_workflow，也不要换 target；修正 registry 或 frontend Workflow 后由新的用户操作创建新 transaction。

## Telegram 失败

transaction 会是 `pending_delivery`，generation/state 已提交。只运行：

```bash
avatarctl resend-last
```

不得重新生成。

## image edit 回退 cosplay

必须同时有 Hermes 本地 last image 和同 target 的 remote image path。0.2.4 的旧 last image 没有 MCP 远端引用，第一次 edit 会安全回退为完整重建；第一次成功 MCP commit 后会记录远端引用。

## direct HTTP emergency mode

仅在新用户操作前把 local config 设为：

```json
{"execution":{"mode":"direct_http"}}
```

旧 backend 仍使用本地 API-format workflow 和配置的 ComfyUI URL，deadline 同为 240 秒。它只检查 prompt/seed/output 的最小接口，不检查 SHA、node count、模型或 topology。不要对已有 MCP prompt_id 使用它。
