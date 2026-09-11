# yinyue-avatar 构建、用户使用与 ComfyUI Workflow 升级指南

适用版本：`yinyue-avatar 0.3.9`  
当前验证日期：2026-09-11  
当前生产目标：`comfy_3060`

本文面向两类读者：日常通过 Telegram 使用银月的用户，以及维护 Skill、Hermes 插件和 ComfyUI Workflow 的管理员。文中的“Workflow”特指 ComfyUI 节点流程图 JSON。

## 目录

- [1. 当前系统概览](#1-当前系统概览)
- [2. 构建与运行架构](#2-构建与运行架构)
- [3. 从源码检查、打包和安装](#3-从源码检查打包和安装)
- [4. 用户使用说明](#4-用户使用说明)
- [5. 管理员日常检查](#5-管理员日常检查)
- [6. 更换或升级 ComfyUI Workflow](#6-更换或升级-comfyui-workflow)
- [7. 验收清单](#7-验收清单)
- [8. 回滚步骤](#8-回滚步骤)
- [9. 常见故障定位](#9-常见故障定位)

## 1. 当前系统概览

当前可用链路如下：

```text
Telegram 用户
  ↓
yinyue-model-router 0.3.5
  ├─ 处理 /yinyue-avatar 控制命令与穿着命令
  └─ 为当前 Session 绑定 Qwen 与 persona
  ↓
Hermes Agent
  ↓ 仅一次 yinyue_avatar_generate
yinyue-visual 1.3.0
  ↓
mcp_executor.py（确定性事务执行器）
  ↓
registry/workflows.json（目标、路径、能力和 slot 绑定）
  ↓
comfy_3060 MCP → ComfyUI Workflow → 图片
  ↓
本地 commit → 持久状态/history → Telegram 投递
```

当前生产配置：

| 项目 | 当前值 |
|---|---|
| Skill 版本 | `0.3.9` |
| 视觉插件 | `yinyue-visual 1.3.0` |
| Session 路由插件 | `yinyue-model-router 0.3.5` |
| 执行模式 | `mcp` |
| 默认目标 | `comfy_3060` |
| 生产 Workflow ID | `yinyue_cosplay01` |
| 3060 远程文件 | `D:\AI\YinyueAvatar\workflows\Krea2_YINYUE_cosplay01.json` |
| 默认画幅 | `9:16` |
| 默认像素量 | `1.5 MP` |

已验证的 3060 业务 slot：

| 业务参数 | Workflow slot |
|---|---|
| Prompt | `63.value` |
| 画幅 | `49.aspect_ratio` |
| 像素量 | `49.megapixels` |
| Seed | `92.noise_seed`、`93.noise_seed` |

两个 seed slot 必须写入同一个事务 seed。不要依赖 ComfyUI 前端文件里的 `randomize` 标志，MCP 转换时不会替它执行随机化。

`yinyue_edit01` 目前在 3060 和 5090 都未部署、未验证，因此不是当前可依赖的生产能力。局部修改缺少已验证编辑 Workflow 时会安全回退到完整重建。

## 2. 构建与运行架构

### 2.1 目录职责

```text
yinyue-avatar/
├── SKILL.md                         Agent 的最小运行规则
├── persona.md                       银月唯一人格源
├── config.json                      可发布的默认配置
├── config.local.json                本机覆盖配置，不应当对外分发
├── bin/avatarctl                    管理 CLI 入口
├── lib/avatarctl.py                 状态、事务、提交、投递与 CLI
├── lib/mcp_executor.py              单次 MCP 事务执行器
├── lib/visual_v030.py               意图路由、prompt 与 registry 逻辑
├── plugins/yinyue-visual/           Hermes 生成工具插件源码
├── registry/workflows.json          Workflow/target/slot 真值表
├── workflow/                        本地 frontend 与 API-format 文件
├── defaults/、schemas/              默认状态与 JSON 结构约束
├── memory/、lore/                   长期记忆和背景资料
├── scripts/                         安装、打包、staging 与检查脚本
├── tests/                           单元和安全脚本测试
└── references/                      运维与用户参考文档
```

Skill 之外还有两个 Hermes 运行时目录：

- `~/.hermes/plugins/yinyue-visual/`：实际被 Gateway 加载的视觉工具插件。
- `~/.hermes/plugins/yinyue-model-router/`：Telegram Session 路由、Qwen/persona 注入以及确定性穿着命令。

路由插件是独立部署组件，不包含在本 Skill 的 `scripts/install.sh` 中。修改 Skill 时不要顺手覆盖其他 Hermes 插件。

### 2.2 配置加载

`config.json` 是默认值，`config.local.json` 按对象递归覆盖默认值。机器地址、状态目录、本机 Hermes 路径等环境差异应放在 `config.local.json`，不要硬编码进公共默认配置。

关键配置项：

- `runtime.state_dir`：持久状态目录，当前默认是 `~/.hermes/state/yinyue-avatar`。
- `execution.mode`：正常生产为 `mcp`；`direct_http` 仅用于管理员明确切换后的新事务。
- `execution.default_target`：当前为 `comfy_3060`。
- `execution.allowed_targets`：允许参与路由的 GPU 目标。
- `execution.registry_path`：Workflow 注册表相对路径。
- `telegram.default_channel`：默认投递渠道。

### 2.3 状态与持久化

主要运行数据位于 `~/.hermes/state/yinyue-avatar/`：

- `state.json`：当前人物、穿着、场景、关系、连续图片等状态。
- `history.jsonl`：追加式事件历史。
- `transactions/`：每次 MCP 事务的恢复记录。
- `output/`：已提交到本地状态的图片。
- `jobs/`、`pending/`、`logs/`：旧执行面和辅助运行记录。
- `memory/`：长期记忆事件和摘要。

状态写入采用临时文件、flush、`fsync` 和原子替换。重启 Gateway 或机器不会把当前穿着、场景和最后图片恢复成默认值。

### 2.4 单次生成事务

```text
用户原始要求
  → prepare：读取持久状态并生成 transaction_id
  → vary_workflow：由不可变原文件生成 transaction 专属 variant
  → list_workflow_slots：读取 variant 的真实值
  → verify：逐项比对 Prompt、尺寸、seed 等声明接口
  → claim-submit：消费本事务唯一提交权
  → run_workflow(wait=false)：只提交一次 variant
  → bind(prompt_id)：事务与远程任务绑定
  → job(wait)：在总 deadline 内轮询同一个任务
  → fetch_outputs(inline_images=true)
  → commit：验证 Linux MEDIA 文件并原子更新状态
  → Telegram delivery；失败时只允许 resend，不重新生图
```

关键不变量：

- 每个用户视觉请求只调用一次 `yinyue_avatar_generate`。
- 原始远程 Workflow 不被修改，也不直接提交；只运行事务专属 variant。
- 一个 transaction 最多执行一次 `run_workflow`。
- 一旦绑定 `prompt_id`，超时或 fetch 失败只能恢复同一任务，不能换 GPU 重跑。
- Telegram 发送失败不等于图片生成失败，只应重发最后结果。

## 3. 从源码检查、打包和安装

### 3.1 依赖

- Linux 上的 Hermes Gateway 与 Hermes CLI。
- Python 3.10 或更高版本；核心 helper 仅依赖 Python 标准库。
- Bash；安全脚本测试和 staging 脚本还会使用 `jq`、`find`、`tar` 等系统工具。
- 已在 Hermes 中配置的 `comfy_3060`/`comfy_5090` MCP server。
- GPU 主机上的 ComfyUI、所需模型/LoRA/自定义节点以及 frontend-format Workflow。
- Telegram Gateway；其 toolset 中需要包含 `yinyue-avatar`。

检查当前 Telegram toolset：

```bash
hermes config get platform_toolsets.telegram
```

预期至少包含：

```text
hermes-telegram
yinyue-avatar
```

### 3.2 本机配置

仅当 `config.local.json` 不存在时，以 `config.local.example.json` 为模板创建。不要用示例文件覆盖已经工作的本机配置。

最低限度确认：

```json
{
  "runtime": {"state_dir": "~/.hermes/state/yinyue-avatar"},
  "execution": {"mode": "mcp", "default_target": "comfy_3060"},
  "telegram": {"default_channel": "telegram"}
}
```

### 3.3 静态检查与测试

在源码根目录执行：

```bash
find . -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
find . -type f -name '*.json' -print0 | xargs -0 -n1 python3 -m json.tool >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
scripts/smoke-test.sh
```

`scripts/smoke-test.sh` 会编译 Python、运行单元测试并执行 `avatarctl doctor`；它不会主动提交图片。`doctor` 能确认本机配置和 registry readiness，但不能代替真实 MCP `server_info`、`validate_workflow` 和 GPU 生图验收。

### 3.4 打包

```bash
scripts/package.sh /absolute/output-directory
```

输出包括 `.zip`、`.tar.gz` 和对应 SHA-256 文件。打包前检查 `config.local.json` 是否含不应分发的机器私有配置；生产备份与发布包应分别管理。

### 3.5 安装 Skill

必须从一个独立源码目录运行安装器；如果源码目录就是当前生产目录，安装器会拒绝执行。

先 dry-run：

```bash
scripts/install.sh
```

确认目标严格等于 `~/.hermes/skills/roleplay/yinyue-avatar` 后再应用：

```bash
scripts/install.sh --apply
```

安装器会：

- 备份旧 Skill 和文件哈希到 `~/.hermes/backups/yinyue-avatar/install-<UTC时间>/`。
- 在独立 staging 中检查 shell、JSON、单元测试和 registry。
- 原子切换 Skill 目录，失败时恢复旧目录。
- 保留已有 `config.local.json`。
- 不迁移或清空 state，不启动 worker，不调用 ComfyUI，也不发送 Telegram。

### 3.6 安装或更新视觉插件

只有 `plugins/yinyue-visual/` 的代码或 `plugin.yaml` 发生变化时，才需要同步运行时插件并重启 Gateway。先单独备份目标插件，然后仅更新 `yinyue-visual`，不要改动其他插件。

从独立源码目录同步时，可使用一个专属备份目录：

```bash
YINYUE_PLUGIN_BACKUP=/absolute/backup/yinyue-visual-before-upgrade
mkdir -p "$YINYUE_PLUGIN_BACKUP" "$HOME/.hermes/plugins/yinyue-visual"
cp -a "$HOME/.hermes/plugins/yinyue-visual/." "$YINYUE_PLUGIN_BACKUP/"
cp -a plugins/yinyue-visual/. "$HOME/.hermes/plugins/yinyue-visual/"
```

这里的目标严格限定为 `yinyue-visual`，不复制、删除或覆盖整个 `~/.hermes/plugins`。`yinyue-model-router` 的源码不在本 Skill 包内，应按该插件自己的 README 独立升级。

完成后检查：

```bash
hermes plugins doctor --ci yinyue-visual
hermes plugins doctor --ci yinyue-model-router
hermes gateway restart
hermes gateway status
```

仅修改 `registry/workflows.json`、`config.json`、`config.local.json`、persona 或本文档时，一般不需要重启：当前生成器每次调用都会重新读取配置和 registry，router 也会按文件变化重新加载 persona。修改 `lib/*.py`、插件 hook/schema 或已加载的 Python 模块时必须重启 Gateway。

## 4. 用户使用说明

### 4.1 启动和结束银月模式

在 Telegram 中：

```text
/yinyue-avatar 启动
/yinyue-avatar 状态
/yinyue-avatar 重置
/yinyue-avatar 结束
```

- `启动`：在当前 Telegram Session 中启用银月使用的模型和 persona。
- `状态`：显示当前 Session 的 Worker Mode、模型和路由状态。
- `重置`：清理 Session 内运行遥测并重新加载 persona；不会清空人物、穿着、关系、历史或最后图片。
- `结束`：退出当前 Session 的银月模式，其他 Session 不受影响。

### 4.2 普通聊天与生成图片

启动后可以直接自然语言聊天。只有明确要求“拍照、发图片、让我看看现在的样子”等视觉请求时才应生成图片，例如：

```text
拍张现在的照片给我看看
换成黑色西装和黑色高跟鞋，在办公室拍一张全身照
保持衣服不变，换成坐在窗边的姿势拍照
```

最好在同一条消息中明确写出要改变的衣服、姿势、场景和画幅。系统会把用户原话完整传入 `intent`，并只把明确改变的可持久字段写入状态。

不要在生成较慢时反复发送同一个请求。一个事务已经提交后，系统会继续等待同一个 `prompt_id`；重复发送可能创建新的独立用户事务。

### 4.3 查看结构化穿着状态

```text
/yinyue-avatar 穿着
```

返回固定 JSON 字段：

```json
{
  "outfit": "",
  "outerwear": "",
  "top": "",
  "bottom": "",
  "dress": "",
  "legwear": "",
  "footwear": "",
  "headwear": "",
  "accessories": ""
}
```

这条命令直接读取持久状态，不让语言模型猜测图片中的衣物。

### 4.4 修改结构化穿着状态

```text
/yinyue-avatar 穿着 设置 {"服装":"黑色西装","袜子":"黑色丝袜","鞋子":"黑色高跟鞋","配饰":""}
```

也可以使用英文键：

```text
/yinyue-avatar 穿着 设置 {"outfit":"黑色西装","legwear":"黑色丝袜","footwear":"黑色高跟鞋","accessories":""}
```

规则：

- 修改命令只更新持久状态，不自动生成图片。
- `""` 表示清除该字段。
- 没有写出的字段保持不变。
- `outfit`、`dress`、`top + bottom` 是互斥的基础服装表示；设置其中一种时会自动清理冲突的旧表示。
- 中文键支持：`服装/整套服装`、`外套`、`上装`、`下装`、`连衣裙`、`腿部穿着/袜子`、`鞋子`、`头饰`、`配饰`。
- 修改后如果希望看到新图片，再单独发送明确的拍照请求。

### 4.5 重发上一张图片

Telegram 投递失败或只想重发最后结果时，不要重新生成。管理员可执行：

```bash
bin/avatarctl resend-last --foreground
```

### 4.6 管理员 CLI 快查

```bash
bin/avatarctl wardrobe
bin/avatarctl status
bin/avatarctl workflows
bin/avatarctl workflow-info yinyue_cosplay01
bin/avatarctl mcp-status
bin/avatarctl history --last 10
bin/avatarctl transaction-status TRANSACTION_ID
bin/avatarctl doctor
```

生产 Agent 不应手工使用 `prepare`、`verify-variant`、`claim-submit`、`bind`、`commit` 等内部事务命令；正常图片请求统一走一次 `yinyue_avatar_generate`。

## 5. 管理员日常检查

推荐按以下顺序检查，全部为只读操作：

```bash
hermes gateway status
hermes plugins doctor --ci yinyue-model-router
hermes plugins doctor --ci yinyue-visual
hermes config get platform_toolsets.telegram
hermes mcp list
bin/avatarctl workflows
bin/avatarctl mcp-status
bin/avatarctl doctor
```

判断标准：

- Gateway 为 `active (running)`。
- 两个插件 doctor 均通过。
- Telegram toolset 包含 `yinyue-avatar`。
- `comfy_3060` MCP 已配置并启用。
- `yinyue_cosplay01@comfy_3060` 同时满足 `workflow_exists=true` 与 `interface_verified=true`。
- `avatarctl doctor` 返回 `ok: true`。

`mcp-status` 只能确认 Hermes 配置里存在目标，不能证明远程主机此刻可连接，也不能证明 Workflow slot 仍正确。远程真实性必须使用 MCP 工具检查。

## 6. 更换或升级 ComfyUI Workflow

### 6.1 升级原则

1. 新 Workflow 使用新文件名，永不直接覆盖当前生产文件。
2. 必须保存 frontend format；仅有 API export 不能用于 MCP slot 发现和变更。
3. 所有 node ID 和输入名以真实 `list_workflow_slots` 结果为准，不沿用猜测。
4. 先验证候选文件，再修改 registry，再进行一次隔离或 `no_send` 端到端验收。
5. 升级期间不处理新的银月图片请求。
6. 已有 `prompt_id` 的事务不切 target、不换 Workflow、不重新提交。
7. 旧远程文件至少保留到新版本观察期结束，以便立即回滚。

### 6.2 第一步：确认没有活动事务

活动状态包括：`planned`、`variant_verified`、`submit_claimed`、`submitted`、`waiting`、`fetch_pending`、`generation_completed`。

可检查 `~/.hermes/state/yinyue-avatar/transactions/*.json` 中的 `status`。如果发现已绑定 `prompt_id` 的事务，先让它完成或按原 target/prompt_id 恢复；不要开始 Workflow 切换。

### 6.3 第二步：备份 Skill、状态和 registry

轻量备份：

```bash
bin/avatarctl backup --output /absolute/backup/yinyue-avatar-before-workflow-upgrade.tar.gz
```

这个命令包含 `state.json`、`history.jsonl`、`config.local.json` 和本地 `workflow/`，但不包含完整 `transactions/` 与 `output/`。需要完整灾备时，再单独复制整个 `~/.hermes/state/yinyue-avatar/`。

另外单独备份：

- `registry/workflows.json`
- `~/.hermes/plugins/yinyue-visual/`（仅当插件也会改）
- `~/.hermes/plugins/yinyue-model-router/`（仅当路由也会改）
- `~/.hermes/config.yaml`（仅当 Hermes/MCP 配置也会改）

不要把备份写进其他 Skill 目录。

### 6.4 第三步：从 ComfyUI 导出候选流程图

在 ComfyUI 中完成节点和模型调整后：

1. 使用 `File > Save (As)` 保存 frontend-format JSON。
2. 使用新版本文件名，例如 `Krea2_YINYUE_cosplay02.json`。
3. 不要覆盖 `Krea2_YINYUE_cosplay01.json`。
4. 如果仍需维护 `direct_http` 应急模式，再额外导出一份 API-format JSON；两种格式不要混用。

本地检查 frontend 文件：

```bash
python3 -m json.tool /absolute/Krea2_YINYUE_cosplay02.json >/dev/null
jq -e '(.nodes | type == "array") and (.links | type == "array")' \
  /absolute/Krea2_YINYUE_cosplay02.json >/dev/null
```

frontend-format 顶层应包含 `nodes` 和 `links`。API-format 通常以 node ID 为顶层键，不包含这两个数组。

### 6.5 第四步：以新文件名部署到 GPU

先 dry-run：

```bash
scripts/deploy-workflow.sh \
  --target comfy_3060 \
  --source /absolute/Krea2_YINYUE_cosplay02.json \
  --name Krea2_YINYUE_cosplay02.json
```

确认源、目标和远程路径正确后：

```bash
scripts/deploy-workflow.sh \
  --target comfy_3060 \
  --source /absolute/Krea2_YINYUE_cosplay02.json \
  --name Krea2_YINYUE_cosplay02.json \
  --apply
```

该脚本会拒绝覆盖同名远程文件。如果同名已存在，应重新选择新文件名或先人工审计现有文件，不要绕过保护。

### 6.6 第五步：真实检查远程 Workflow

通过 `comfy_3060` MCP 依次调用：

```text
server_info()
validate_workflow(workflow_path="D:\AI\YinyueAvatar\workflows\Krea2_YINYUE_cosplay02.json")
list_workflow_slots(workflow_path="D:\AI\YinyueAvatar\workflows\Krea2_YINYUE_cosplay02.json")
```

记录真实结果并确认：

- Workflow 能被 ComfyUI/MCP 解析。
- Prompt 输入 slot 可写。
- 画幅和像素量 slot 与新的节点定义一致。
- 所有实际 sampler seed slot 都已找到；需要同步 seed 的 sampler 不能漏掉。
- 输出节点能产生 image。
- 新 Workflow 所需模型、LoRA 和自定义节点在 3060 主机上均存在。

如果 `list_workflow_slots` 报 `workflow_not_frontend_format`，回到 ComfyUI 使用 `Save (As)`，不要在 registry 中伪造 slot。

### 6.7 第六步：做隔离 variant 验证

在维护上下文中使用 MCP `vary_workflow`：

1. 原文件指向候选 Workflow。
2. 输出 variant 放到独立升级测试目录，例如 `D:\AI\YinyueAvatar\temp\upgrade-<时间>\...`。
3. 写入一段带唯一标记的测试 Prompt、一个非默认画幅/像素量和一个确定 seed。
4. 再次对 variant 调用 `list_workflow_slots`。
5. 逐项确认 Prompt、尺寸和所有 seed slot 的实际值完全等于测试值。
6. 确认候选原文件本身没有被修改。

如需实际 GPU 冒烟测试，只对已验证的 variant 调用一次 `run_workflow(wait=false)`，保存返回的 `prompt_id`，随后只用该 ID 执行 `job(wait)` 和 `fetch_outputs(inline_images=true)`。绝对不要因等待超时再次 `run_workflow`。

这一步属于管理员维护，不应让角色扮演 Agent 手工编排。

### 6.8 第七步：更新 registry

在 `registry/workflows.json` 的 `yinyue_cosplay01` 条目中更新：

- `remote_paths.comfy_3060`：改为候选文件的新路径。
- `parameter_bindings`：按真实 slot 更新 `prompt`、`aspect_ratio`、`megapixels`、`seed`。
- `input_roles`：只保留实际支持并需要由控制面写入的角色。
- `default_parameters`：如新 Workflow 的推荐默认画幅或像素量发生变化再修改。
- `target_status.comfy_3060`：只有真实验证完成后才设置 `workflow_exists=true`、`interface_verified=true`，同时更新 `checked_at` 和可审计的 `reason`。

不要为了升级模型、LoRA、采样器或内部节点而建立整图 SHA/topology baseline。registry 只描述业务接口；Workflow 内部画质和人物一致性由 GPU 流程图负责。

如果增加的是全新用途，而不是替换 `yinyue_cosplay01`：

1. 新增独立 workflow entry，不覆盖旧 entry。
2. 填写 `id`、`purpose`、`description`、targets、paths、capabilities、roles、bindings 和 status。
3. 只有新用途无法归入现有意图类型时才修改 `route_intent`。
4. 当前未验证的 `yinyue_edit01` 不应直接标记为 ready。

### 6.9 第八步：本地验证并激活

```bash
python3 -m json.tool registry/workflows.json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bin/avatarctl workflows
bin/avatarctl workflow-info yinyue_cosplay01
bin/avatarctl doctor
```

如果修改发生在独立源码目录，使用 `scripts/install.sh` dry-run 后再 `--apply`。如果只在当前生产 Skill 中更新 registry，则新的生成调用会读取新 registry，一般不需要重启 Gateway。

如果同时修改了 `yinyue-visual` 插件、工具 schema 或 router hook，则同步对应插件、运行 plugin doctor，并重启 Gateway。

### 6.10 第九步：端到端验收

推荐先在受控维护会话中调用一次 `yinyue_avatar_generate`，显式指定：

```json
{
  "intent": "保持当前人物与穿着，生成一张工作流升级验收照片",
  "workflow": "yinyue_cosplay01",
  "target": "comfy_3060",
  "no_send": true
}
```

注意：`no_send=true` 只跳过 Telegram 投递；成功结果仍会 commit，更新 revision、last image 和 continuity。如果不能接受任何生产状态变化，应只做上一节的隔离 MCP variant 冒烟，或在完全隔离的 state 目录中验收。

端到端检查：

- 实际 transaction 使用候选远程路径的 variant。
- `submit_count` 等于 1。
- Prompt 中包含本次用户要求，不再残留旧主题词。
- Prompt、画幅、像素量和两个 seed slot 均正确。
- 两个 seed slot 值相同。
- `prompt_id` 已绑定且 job 最终 completed。
- `fetch_outputs` 返回真实 Linux `MEDIA:/absolute/path`。
- commit 后本地图片存在且能打开。
- `no_send=true` 时没有 Telegram 消息；正常验收时只发送一次结果。

通过后再恢复用户流量，并保留旧 Workflow 和 registry 备份一段观察期。

## 7. 验收清单

### Skill/插件

- [ ] JSON、shell 和单元测试全部通过。
- [ ] `yinyue-model-router` plugin doctor 通过。
- [ ] `yinyue-visual` plugin doctor 通过。
- [ ] Telegram toolset 包含 `yinyue-avatar`。
- [ ] Gateway 正常运行。

### Workflow

- [ ] 候选文件是 frontend format。
- [ ] 候选使用新文件名，旧文件未覆盖。
- [ ] `server_info`、`validate_workflow`、`list_workflow_slots` 真实通过。
- [ ] registry slot 来自真实发现，不是沿用猜测。
- [ ] Prompt/尺寸/所有 seed 在 variant 中精确匹配。
- [ ] 原 Workflow 未被 vary 或提交。
- [ ] 实际运行仅提交一次。
- [ ] 输出能够 fetch、commit 并正常显示。

### 状态与投递

- [ ] 当前穿着和其他未要求修改的字段没有意外变化。
- [ ] revision 只按预期增加。
- [ ] last image、last target、last transaction 和远端连续图片记录一致。
- [ ] Telegram 失败时使用 `resend-last`，没有重新生成。

## 8. 回滚步骤

### 8.1 仅 Workflow/registry 升级失败

1. 停止接受新的银月图片请求。
2. 检查失败事务是否已经有 `prompt_id`。
3. 如果已有 `prompt_id`，只恢复/等待这个原任务；不要用旧 Workflow 再提交一次。
4. 把 `registry/workflows.json` 恢复为升级前备份，使 `remote_paths` 和 `parameter_bindings` 回到旧的已验证值。
5. 运行 JSON 检查、单元测试、`avatarctl workflow-info` 和 `avatarctl doctor`。
6. 发起一项受控验收，确认新事务重新使用旧 Workflow。
7. 保留失败候选文件和事务记录用于分析，不立即删除。

因为升级使用新文件名，回滚不需要覆盖或重新上传旧生产 Workflow。

### 8.2 Skill 安装失败

`scripts/install.sh --apply` 会在失败切换时自动恢复旧 Skill。成功安装后若需要人工回滚，使用它输出的：

```text
~/.hermes/backups/yinyue-avatar/install-<UTC时间>/previous-skill-directory/
```

回滚前先备份升级后的 registry、state 和 transactions，以免丢失升级后产生的有效结果。Skill 安装器本身不会回滚或清空 production state。

### 8.3 插件升级失败

只恢复发生变化的 `yinyue-visual` 或 `yinyue-model-router` 备份，随后分别运行 plugin doctor 并重启 Gateway。不要恢复整个 `~/.hermes/plugins`，以免破坏其他技能和插件。

## 9. 常见故障定位

| 现象 | 常见原因 | 正确处理 |
|---|---|---|
| Telegram 只回文字、不生图 | 视觉工具未暴露、toolset 缺失、router/plugin 未加载 | 查两个 plugin doctor、Telegram toolset 和 Gateway 日志 |
| `invalid tool call: yinyue_avatar_generate` | 模型调用名可见但真实 schema/bridge 未生效 | 查 `yinyue-model-router` 与 `yinyue-visual` 版本和加载状态，不要让模型改用虚构工具 |
| 图片生成但不遵从 Prompt | Prompt slot 绑定错误、variant 未写入、Workflow 内部 prompt 节点另有覆盖 | 对 candidate/variant 执行 `list_workflow_slots`，核对 registry 和实际 Prompt 值 |
| 仍残留旧服装/旧主题 | 结构化状态未清除冲突字段，或 Workflow 内部存在固定文本 | 先用 `/yinyue-avatar 穿着` 查看状态；清空冲突字段，再检查 Prompt slot 与 Workflow 内部固定词 |
| `workflow_not_frontend_format` | 上传了 API export | 用 ComfyUI `Save (As)` 重新导出 frontend JSON |
| `no workflow ready` | registry 的存在或接口验证为 false | 真实验证文件与 slots 后再更新 `target_status`，不要强行设 true |
| 等待超时 | GPU job 慢、MCP 通道暂时中断 | 查询同一个 transaction/prompt_id；不得再次 `run_workflow` |
| 图片已有但 Telegram 未收到 | delivery failure | 使用 `resend-last`，不要重新生图 |
| 重启后状态变化 | 读到了错误的 `state_dir` 或错误 profile | 核对 `config.local.json` 与实际加载 Skill；不要手工改写 state |

更深入的实现细节见：

- `docs/ARCHITECTURE.md`
- `docs/MCP_WORKFLOW_GUIDE.md`
- `docs/TROUBLESHOOTING.md`
- `docs/MIGRATION.md`
