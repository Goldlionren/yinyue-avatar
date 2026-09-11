# yinyue-avatar 0.3.10

银月的独立、多 Workflow、多 GPU 数字人视觉 Skill。它保留 0.2.4 的角色、场景、关系和长期记忆状态，在其上增加自然语言路由、Comfy MCP execution plan、双 target registry、可恢复 transaction 和局部图片编辑连续性。

## 运行边界

运行时只依赖 Hermes、Hermes MCP runtime、`comfy_5090`、`comfy_3060`、GPU 主机的 ComfyUI/Workflow、Telegram、Python 标准库。本目录不读取或调用任何其他 Skill。

默认 backend：

```json
{"execution":{"mode":"mcp","default_target":"comfy_3060"}}
```

故障恢复可由管理员在新操作前改成 `direct_http`；已提交 MCP job 绝不跨 backend 重跑。

## 常用命令

```bash
AVATARCTL="$HOME/.hermes/skills/roleplay/yinyue-avatar/bin/avatarctl"
"$AVATARCTL" doctor
"$AVATARCTL" context
"$AVATARCTL" workflows
"$AVATARCTL" workflow-info yinyue_cosplay01
"$AVATARCTL" mcp-status
"$AVATARCTL" prepare --intent '3:4，2MP，拍张现在的照片' --no-send
"$AVATARCTL" transaction-status TRANSACTION_ID
"$AVATARCTL" resend-last
```

生产 agent 只调用一次 `yinyue_avatar_generate`。该工具内部严格执行 `prepare → MCP → bind → wait/fetch → commit` 协议，Agent 不再手工编排步骤。

0.3.8 保留最多两段纯角色氛围旁白，但隐藏全部技术进度；结构化单工具入口消除 shell 转义、help 探测、手工 MCP 调用和逐步试错。Telegram 原始消息若仍带 `/yinyue-avatar` 而标准化文本丢了命令前缀，入口守卫会先恢复原命令。插件在 Skill turn 上硬性禁止其他工具和第二次生成，并校验最终回复：没有成功调用生成工具时，禁止声称已有新图或输出图片链接。未提交的旧事务会被安全取代；已绑定任务只恢复轮询，绝不重复提交。

## 当前 Workflow registry

- `yinyue_cosplay01`：text-to-image；展示当前形象、完整换装、新场景、没有 source 时重建。
- `yinyue_edit01`：image-edit；使用同一 target 的上一张远端结果进行局部修改。

Registry 位于 `registry/workflows.json`。核心代码不固定 node ID；语义角色到 frontend workflow slot 的地址全部在 registry 中。

3060 上的当前生产 frontend Workflow 是 `D:\AI\YinyueAvatar\workflows\Krea2_YINYUE_cosplay01.json`。MCP production control plane 修改 Prompt `63.value`、分辨率 `49.aspect_ratio` / `49.megapixels`，并把同一个 8 位事务 seed 同时写入 `92.noise_seed` 与 `93.noise_seed`；默认分辨率为 `9:16`、`1.5MP`。本地 frontend 源文件保留在 `workflow/Krea2_YINYUE_cosplay01.json`，legacy direct-http 使用独立的 API-format 文件 `workflow/Krea2_YINYUE_cosplay01.api.json`。`yinyue_edit01` 仍需在可用 target 上部署和验证后才会启用；5090 保持 fail-closed，直到真实连通及 slot 验证通过。

## 事务安全

`prepare` 先创建独立 transaction_id。MCP `vary_workflow` 在 transaction 专属目录创建 variant，`list_workflow_slots` 的业务参数必须由 `verify-variant` 完整比对；只有通过后 `claim-submit` 才消费唯一提交权。`run_workflow(wait=false)` 永远只运行 variant，一次 transaction 最多提交一次。`commit` 只接受 completed job 的 Hermes Linux 本地图片并幂等更新 state；Telegram 失败不会重新生成。

MCP 等待总 deadline 为 240 秒，每次 `job(wait)` 默认 20 秒。`fetch_outputs(inline_images=true)` 的 Windows saved path 只作远端 metadata；MCP ImageContent 经 Hermes runtime 缓存后产生的 `MEDIA:/absolute/linux/path` 才能交给 `commit`。commit 会验证文件存在、可读、非空且具有真实图片签名。

## Workflow 可编辑性

不做完整 SHA-256、node_count、input_count、模型、LoRA 或 topology baseline。用户可修改 GPU Workflow；运行前只验证 registry 声明的本次语义接口仍存在且可写。

## 文档

- [构建、用户使用与 Workflow 升级指南](references/build-user-workflow-guide.md)
- [架构](docs/ARCHITECTURE.md)
- [迁移与回滚](docs/MIGRATION.md)
- [MCP Workflow 指南](docs/MCP_WORKFLOW_GUIDE.md)
- [排障](docs/TROUBLESHOOTING.md)
- [当前 MCP 发现快照](docs/MCP_DISCOVERY_20260819.json)
- [历史 MCP 发现快照](docs/MCP_DISCOVERY_20260818.json)
- [0.3.2 真实 generation 验证](docs/V0.3.2_REAL_MCP_TEST.json)

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
RUN_STAGING_SCRIPT_TESTS=1 bash tests/test_safe_scripts.sh
```

所有 helper 仅使用 Python 标准库。已有 production state/history/output 不会被安装器清空。
