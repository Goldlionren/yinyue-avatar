# Migration and rollback

## 0.3.3 → 0.3.4

State schema 与 `visual_system_version` 均不变。0.3.4 根据 3060 当前 frontend Workflow，把 MCP seed 控制恢复为唯一的 `111.seed`：每个新 transaction 生成 8 位整数，只修改统一 SeedNode，不再分别修改 `92/93.noise_seed`。这是因为 Comfy MCP 转换器会丢弃 frontend 的 `randomize` 标记，但不会执行随机化；若不覆盖 `111.seed`，静态文件中的 `42` 会被重复提交。

旧 0.3.2 的双 sampler seed transaction 继续只读兼容，不会阻塞新的 prepare；0.3.3 生成的未提交 seed-free transaction 也不会被批量重写。提示词生成新增变化原话兜底，避免“换个衣服/动作”在空 patch 时复用旧节点 63。3060 manifest 的原始损坏文件备份为 `yinyue_cosplay01.manifest.json.backup-20260819-1035`，中间修复版备份为 `yinyue_cosplay01.manifest.json.backup-20260819-1050`。

## 0.3.2 → 0.3.3

State schema 仍为 2，`visual_system_version` 仍为 1，不重写已有 state。0.3.3 新 transaction 不再生成 seed；旧 0.3.2 transaction 的已有字段保持只读兼容，但不会进入新的 MCP vary、verify 或 generation report。含旧采样字段且从未 claim/submit 的 planned/verified transaction 会保留在磁盘，但不再参与新 prepare 的 dedup/block。已有 submit claim 或 prompt_id 的事务仍按原 job 恢复。original/variant path、submit_count、job/result/commit/delivery status 保持兼容，不做破坏性批量迁移。

执行协议仍为 immutable original → `vary_workflow` transaction variant → slot verification → single submit claim → async run once → Linux materialization → commit。0.3.3 只从 MCP production control plane 删除采样参数；旧 direct HTTP backend 保留，但不会在 MCP transaction 中自动 fallback。

## 0.2.4 → 0.3.0

旧 JSON `schema_version` 保持 2，以维持所有 0.2.4 reader/writer。新增独立的 `visual_system_version: 1` 扩展：

- `visual.outerwear/top/bottom/dress/headwear/accessories`
- `continuity.last_workflow_id`
- `continuity.last_target`
- `continuity.last_transaction_id`
- `continuity.remote_images`
- `continuity.delivery_status`

`ensure_runtime` 在同一 `avatar.lock` 下执行幂等迁移。首次迁移先保存：

```text
~/.hermes/state/yinyue-avatar/baseline-backups/state-v0.2.4-pre-v0.3.0-rNNNN.json
```

迁移不增加 revision，不删除 `visual.outfit`、relationship、memory、history 或图片，并写一条 `visual_system_migration` history event。重复运行不再写 state/history。

## 本次生产备份

```text
/home/james/.hermes/backups/yinyue-avatar/20260818T161302Z-pre-v0.3.3
```

`skill/` 完整；`state/` 包含所有非 output state、history/jobs/memory/pending/backups 及当时 `last_image`。完整 output 未复制但始终保留在原目录，manifest 明确记录。

## 回滚

先停止新的 avatar 请求，再执行一条完整恢复命令：

```bash
BACKUP=/home/james/.hermes/backups/yinyue-avatar/20260818T161302Z-pre-v0.3.3; \
cp -a "$BACKUP/skill/." /home/james/.hermes/skills/roleplay/yinyue-avatar/ && \
cp -a "$BACKUP/state/." /home/james/.hermes/state/yinyue-avatar/
```

该命令不会删除 production output 中未备份的旧图片。若要求字节级回到旧 state，应在回滚前另存升级后 state/history/transactions，再用备份文件覆盖对应文件。
