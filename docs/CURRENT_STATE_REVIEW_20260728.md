# yinyue-avatar 开发前当前状态审计（2026-07-28）

## 1. Executive Summary

审计已完成。Hermes 当前生产加载路径是 `/home/james/.hermes/skills/roleplay/yinyue-avatar`；它是普通目录，不是软链接，也不是 Git 工作树。独立开发源位于 `/mnt/data_nvme/projects/hermes-skills/roleplay/yinyue-avatar`，是 `master` 分支、commit `5ac9055`、工作树干净、无配置的 remote。部署由 `scripts/install.sh` 的删除后复制机制完成，而不是软链接。

当前生产运行链可用：生产 workflow 的有效 masked SHA-256 与生产 `config.local.json` baseline 一致，配置中的 ComfyUI `/system_stats` 健康检查成功，最近 189 个任务为 completed，最近任务的生成和投递均成功。未发现当前正在运行的 avatar worker。

但目前不具备“直接安全继续功能开发”的干净基线，存在两个 High 问题：

1. 开发源与生产部署已分叉：workflow 固定提示词不同，masked hash 也不同；生产额外含有 `docs/yinyue_history.md`，本地配置也不同。
2. 测试、README、默认配置与生产 baseline 不一致；实际单元测试 8 项中 1 项失败。

没有发现 Critical 问题。建议下一阶段先建立单一可信源码与可复现部署基线，再做功能开发；不要先改运行逻辑。

审计严格遵守只读约束。除本报告外，没有修改 Skill、workflow、baseline、生产状态、日志或输出。

## 2. Current Production Path

- `pwd`：`/home/james/.hermes/skills/roleplay/yinyue-avatar`
- `realpath .`：`/home/james/.hermes/skills/roleplay/yinyue-avatar`
- 生产目录：普通目录，非软链接。
- Hermes Skill 约定路径、`SKILL.md` 固定 helper 路径及用户提供的当前使用路径三者一致。
- 固定入口：`/home/james/.hermes/skills/roleplay/yinyue-avatar/bin/avatarctl`
- 运行状态：`/home/james/.hermes/state/yinyue-avatar`
- ComfyUI：`http://192.168.100.211:8188`（来自生产 `config.local.json`，未猜测）
- Telegram channel：存在于本地配置；本报告不披露具体私人 channel 标识。

全盘限定搜索还发现：

- 开发源：`/mnt/data_nvme/projects/hermes-skills/roleplay/yinyue-avatar`
- 垃圾箱旧副本：`/home/james/.local/share/Trash/files/yinyue-avatar`
- 备份恢复副本：`/mnt/data_nvme/backups/hermes/upgrade-20260723-192036/restore-stage-yinyue-avatar-20260723-201440/.hermes/skills/roleplay/yinyue-avatar`
- 下载包：`~/Downloads/yinyue-avatar-skill-v0.1.0.zip`、`v0.2.0.zip`、`v0.2.1.zip`、`v0.2.2.zip`

垃圾箱、备份恢复目录和压缩包不属于当前运行链。

## 3. Source and Deployment Relationship

开发源：

```text
/mnt/data_nvme/projects/hermes-skills/roleplay/yinyue-avatar
```

生产部署：

```text
/home/james/.hermes/skills/roleplay/yinyue-avatar
```

二者均为独立普通目录，没有软链接关系。`scripts/install.sh` 默认把源目录完整复制到生产目录：先暂存生产 `config.local.json`，然后 `rm -rf "$DEST_ROOT"`、`cp -a "$SOURCE_ROOT" "$DEST_ROOT"`，最后恢复本地配置和状态目录。

逐文件比较结果：

- `config.local.json` 不同（预期包含机器本地配置，但也包含不同 workflow baseline）。
- `workflow/Krea2_YINYUE_cosplay01.json` 不同。
- 生产独有 `docs/yinyue_history.md`。
- 其余审计范围内文件一致。

workflow 唯一结构差异为 `87.inputs.string_a`：生产加入“画面外不露脸的男子、第一人称视角、POV”等固定提示词，并调整了重复词。源和生产的 raw/masked hash 均因此不同。

无法从仓库内找到自动同步、manifest、部署日志或 source→deployment 内容清单；能确认的部署机制只有破坏性复制安装脚本。生产目录本身无 Git 元数据，存在生产直接修改后未回灌源码的现实风险。

## 4. Skill Architecture

元数据：

- 名称：`yinyue-avatar`
- 版本：`0.2.2`
- description：当用户提及银月并询问外观、穿着、位置、照片，或要求改变衣着、姿势、场景、表情时必须优先使用；显式 `/yinyue-avatar` 也触发。
- 平台：Linux
- Python 要求：README 声明 3.10+；实现仅使用标准库。

小模型/Agent 的职责：

1. 首次调用 `avatarctl context` 读取人格、状态和最近五条历史。
2. 判断只读对话、展示当前形象或最小状态补丁。
3. 仅提取白名单中的 `visual.*`/`internal.*` 字段。
4. 调用固定 helper 的 `show`、`render` 或 `update`。
5. 异步排队返回 `agent_action=stop_silently` 后立即停止。

固定 helper：

- Shell 入口：`bin/avatarctl`
- 实际实现：`python3 lib/avatarctl.py "$@"`
- 成功输出：单行 JSON，退出码 0。
- 可预期业务错误：stderr `ERROR: ...`，退出码 2。
- 未预期异常：stderr 含 traceback，退出码 3。
- 后台 worker：同一 Python 文件隐藏子命令 `_worker --job PATH`。

Telegram 媒体由 helper 内的 `deliver_text_and_media()` 执行：先以 `hermes send --to CHANNEL TEXT` 发送文字，再独立发送 `MEDIA:/absolute/path/image`。Agent 本身不发送媒体，也不依赖 `telegram-media-sender`。

实现总体符合“固定 helper + 轻量 Skill”架构；代码检索未发现对其他 Skill、其他 helper、会话历史或模型记忆的引用。外部依赖仅为 Python、ComfyUI、Hermes CLI、Telegram channel、workflow 模型/LoRA/节点及文件系统。

## 5. Complete Runtime Call Chain

```text
Hermes 触发 SKILL.md
  → bin/avatarctl
  → 系统 PATH 中的 python3
  → lib/avatarctl.py
  → load_config(): config.json 深合并 config.local.json
  → ensure_runtime(): 状态目录/默认 state 初始化
  → context/status/update 或 queue_job()
  → jobs/<uuid>.json 原子写入
  → systemd-run --user（优先）或 detached subprocess
  → _worker --job jobs/<uuid>.json
  → avatar.lock 独占 flock
  → validate_workflow() masked hash 校验
  → POST ComfyUI /prompt
  → GET /history/<prompt_id> 轮询
  → GET /view 下载并校验 PNG/JPEG/WebP
  → output/yinyue-YYYYMMDD-HHMMSS-rNNNN.ext 原子写入
  → state.json 原子替换 + history.jsonl 追加
  → 释放生成锁
  → hermes send 文字
  → hermes send MEDIA:/absolute/path
  → job completed 或 pending_delivery/failed
```

主要函数对应：

- 参数解析：`build_parser()` / `main()`
- 配置：`load_config()`
- workflow：`validate_workflow()` / `masked_workflow_hash()`
- 排队与去重：`queue_job()` / `request_fingerprint()` / `find_duplicate_job()`
- worker 启动：`launch_worker()`
- 生成：`run_generation_job()`
- ComfyUI：`submit_comfyui()` / `poll_comfyui()` / `download_image()`
- 状态提交：`atomic_write_json()` / `append_jsonl()`
- 投递：`deliver_text_and_media()` / `run_send_with_retry()`
- 重发：`run_resend_job()`

输入传递：

- `--set path=value` 经白名单和类型校验后形成 patch。
- `--say` 仅用于 Telegram 文字。
- visual 状态由 `serialize_visual_prompt()` 固定序列化，写入 node `63.inputs.value`。
- seed 用 `secrets.randbelow()` 生成，写入 node `85.inputs.seed`。

超时：

- ComfyUI 单次 HTTP/connect：生产有效值 10 秒。
- ComfyUI 总生成：900 秒。
- 轮询间隔：2 秒。
- `hermes send`：75 秒/次，最多 2 次，间隔 3 秒。
- `systemd-run` 启动：10 秒。
- CLI `wait` 默认 900 秒。

并发：

- 生成、下载、状态提交由单个 `avatar.lock` 串行化。
- 去重扫描和 job 创建本身没有锁，两个真正同时到达的相同请求仍可能竞态创建两个 job。
- 投递发生在生成锁释放之后，因此下一次生成可在上一张图仍在发送时开始。

失败边界：

- 生成成功后先提交图片、state 和 history，再发送 Telegram。
- 媒体发送失败时 job 为 `pending_delivery`，保存 pending 文件；前台仍早已返回成功排队，避免自动重复生成。
- 当前实现不会从目录“找最新图片”；重发严格使用 state 的 `continuity.last_image`，且先验证文件存在。因此正常路径不易误发目录中的旧图片。
- 但是手工/异常篡改 state 的 `last_image` 可导致发错旧图；没有内容 hash 或 job/revision 一致性校验。

## 6. File and Directory Inventory

源码/部署内容：

```text
SKILL.md                         Hermes 路由与行为契约
README.md                        v0.2.2 架构、安装和运行说明
persona.md                       角色人格
config.json                      默认配置和默认 workflow baseline
config.local.json                生产机器覆盖配置
config.local.example.json        本地配置示例
bin/avatarctl                    固定 Shell 入口
lib/avatarctl.py                 全部运行实现
defaults/state.default.json      初始状态
schemas/state.schema.json        状态 schema（目前只验证顶层 required）
scripts/install.sh               删除后复制部署
scripts/package.sh               zip/tar 打包及 sha256
scripts/smoke-test.sh            py_compile、unittest、doctor
tests/test_avatarctl.py          8 个 unittest/mock 测试
workflow/Krea2_YINYUE_cosplay01.json
workflow/Krea2_YINYUE_cosplay01.json.backup-20260719-175536
docs/TEST-PLAN.md
docs/yinyue_history.md           仅生产存在的角色前史
lib/__pycache__/...pyc           已存在的运行缓存
```

不存在 `src/`、`config/`、`workflows/`（实际为单数 `workflow/`）、虚拟环境、requirements、pyproject、lockfile、manifest 或独立 baseline 文件。Python 包依赖为标准库，不需要 venv。

未发现 Skill 专属 cron、持久 systemd unit 或常驻后台脚本。后台 unit 是按 job 动态创建并 `--collect`；systemd user manager 不可用时退回 detached worker。用户系统中存在 `hermes-gateway.service`，但它不是本 Skill 专属 unit。

## 7. Commands and Subcommands

`bin/avatarctl --help` 实际列出：

- `context`：返回 persona、完整当前 state、文字状态、最近 5 条历史；名义只读，但会初始化缺失的运行目录/state。
- `status`：返回 state；名义只读，但同样调用 `ensure_runtime()`。
- `history --last N`：返回最近历史；同样可能初始化运行目录/state。
- `update --set ... --remember ...`：修改状态并增加 revision。
- `show [--say/--channel/--no-send/--foreground]`：按当前状态生成。
- `render [--set/...同上]`：最小补丁后生成。
- `resend-last [--say/--channel/--foreground]`：重发 state 指向的最后图片，不生成、不加 revision。
- `doctor`：检查 Python、workflow、state、写权限、Hermes、systemd-run、ComfyUI；会调用 `ensure_runtime()`。
- `jobs --last N`：列出任务。
- `job-status JOB_ID`：读取任务。
- `wait JOB_ID --timeout N`：轮询任务。
- `backup --output PATH`：创建包含 state/history/local config/workflow 的 tar.gz。
- `_worker --job PATH`：隐藏后台入口，但 argparse help 中仍显示名字和 `==SUPPRESS==`。

不存在用户示例中提到的 `generate`、`send`、`reset`、`rebuild-hash`。真实等价生成命令为 `show`/`render`；没有 baseline 重建命令。

本审计只执行了 `--help`。因 `doctor`、`status`、`context` 都可能通过 `ensure_runtime()` 写入缺失项，未直接执行；使用独立只读命令完成等价核验。

## 8. Configuration and Environment

配置优先级：`config.json` → 递归深合并 `config.local.json`。

生产本地覆盖：

- ComfyUI URL：LAN 固定 IP `192.168.100.211:8188`
- Telegram 默认 channel：已配置，本报告已脱敏
- state dir：`~/.hermes/state/yinyue-avatar`
- workflow masked baseline：生产专用值

代码没有读取未声明的环境变量；只有安装脚本支持 `YINYUE_AVATAR_INSTALL_DIR` 和 `YINYUE_AVATAR_STATE_DIR`。Shell profile 中与本 Skill 有关的唯一证据是 `.bashrc` 把 `~/.local/bin` 加入 PATH；这影响 `hermes` 和 `python3` 的解析。`bin/avatarctl` 使用 PATH 中 `python3`，未固定解释器。

生产敏感信息扫描未发现硬编码 token、password、secret 或 API key。Telegram channel 存在于 mode 0664 的 `config.local.json`，对同组用户可读。

## 9. ComfyUI Workflow and Hash Baseline

生产 workflow：

```text
/home/james/.hermes/skills/roleplay/yinyue-avatar/workflow/Krea2_YINYUE_cosplay01.json
```

- raw SHA-256：`6e5c6b879168e31ceb9af04fd6ffa4d4412618398699e415681b7d45a43a5f3d`
- actual masked SHA-256：`279d35360af5a1d5ed402cf11855732237b199130aeba1741d5483ce6db17208`
- 生产有效 baseline（`config.local.json`）：同上，匹配。
- 默认 baseline（`config.json`/README/test）：`54d041e0363aefcb4f42ca262b6ee3562973795cee3fcf20bf97c0787ad0ef8b`，不匹配生产 workflow。

开发源 workflow：

- raw SHA-256：`03865188cfe189ecd52b893e2e565ae4cd50509d1edb23ab0160172a38893ee9`
- actual/effective masked SHA-256：`ce331d1570e15c09726b5a2c9273b0f4aac1128b4078b3f729a8e1b33e5c9cb2`
- 源码自己的本地 baseline 与它匹配。

hash 实现在 `lib/avatarctl.py:masked_workflow_hash()` 和 `validate_workflow()`。计算时把 node 63 prompt 和 node 85 seed 替换成 mask 后，对 canonical JSON 做 SHA-256。

仓库没有 `rebuild-hash` 或更新 baseline 命令。当前只能人工/临时代码计算并手工更新配置；README 所说“重新生成基线”没有可执行流程。更新本地 baseline只影响 `config.local.json`；若要默认安装、README、测试一致，还必须同步至少 `config.json`、README、测试常量。

workflow 依赖资产：

- UNet：`Krea2-Turbo-int8-ConvRot.safetensors`
- CLIP：`qwen3vl_4b_fp8_scaled.safetensors`
- VAE：`qwen_image_vae.safetensors`
- LoRA：`realism_engine_krea2_v2.safetensors`
- LoRA：`Krea2 Lora\krea2_yinyue_test01.safetensors`
- 节点类型包括 `ResolutionSelector`、`Seed Generator`、`StringConcatenate`、`PreviewAny`、`PrimitiveStringMultiline` 等；哪些来自 core、扩展或特定版本没有 manifest，因此无法仅凭现有证据可靠确认 custom-node 包名。

JSON 中没有 Linux/Windows 绝对文件路径，但模型名、LoRA 子目录的 Windows 风格反斜杠及远端 LAN 服务属于机器/ComfyUI 安装约束。迁移时必须另行配置模型与节点，当前不可一键复现。

## 10. Runtime State and Output Data

状态根：`/home/james/.hermes/state/yinyue-avatar`

- `state.json`：1,634 bytes，revision 196，更新时间 2026-07-28 14:24 AEST；`last_image` 指向存在的 r0196 图片。
- `history.jsonl`：196 行、221,657 bytes；与 revision 数一致。
- `output/`：196 个文件、约 793 MiB。
- `jobs/`：200 个 JSON、约 1.4 MiB；189 completed、11 failed。
- `pending/`：1 个 2026-07-19 的遗留发送失败记录。
- `logs/`：目录存在，当前无实际日志文件。
- `avatar.lock`：0 bytes；这是正常 flock 载体，非失败残留。
- `baseline-backups/`：约 288 KiB，含 8 个时间戳备份目录；这是运行状态中的运维数据，不在当前代码描述的标准状态目录清单中。

最近 8 个任务均 completed，delivery ok；最近任务于 2026-07-28 14:25 AEST 完成。未发现 queued/running job 或活跃 worker。

旧 pending 记录来自早期 `MEDIA` 处理失败，结构与当前 job UUID 体系不同，当前代码不会自动清除；它可能让人工排障误判仍有待投递任务。jobs/history/output 均无轮转或保留策略，会持续增长。所有这些运行数据都不应纳入源码管理。

私人状态与历史仅检查了字段、计数、时间、revision、路径存在性和事件结构；报告没有复制完整私人内容。

## 11. External Dependencies

已安全验证：

- Hermes CLI：`/home/james/.local/bin/hermes`，v0.19.0 (2026.7.20)
- helper 实际 PATH Python：`/home/james/miniforge3/bin/python3`，Python 3.13.12
- Bash：5.2.21
- jq：1.7（仅运维/审计依赖，运行 Python 不依赖）
- curl：8.5.0（仅运维/健康检查，运行 Python 使用 urllib）
- sha256sum：coreutils 9.4（打包/人工核验）
- flock CLI：util-linux 2.39.3；运行代码实际使用 Python `fcntl`
- `systemd-run`：`/usr/bin/systemd-run`
- ComfyUI `/system_stats`：在线，ComfyUI 0.28.0，Windows 服务，Python 3.13.11，PyTorch 2.11.0+cu130，RTX 3060
- Python packages：运行时只用标准库，无 pip 声明

未执行、无法无副作用完全验证：

- 各模型/LoRA 文件是否在远端 ComfyUI 的精确目录存在。
- custom node 包名、版本及可迁移安装清单。
- Telegram 实际发送（禁止发消息）。
- systemd user 动态 unit 实际启动；沙箱内无法连接 user bus，但历史 job 的 launcher 信息及成功记录提供运行证据。

## 12. Static Validation Results

已执行并通过：

- `bash -n`：`bin/avatarctl`、`scripts/install.sh`、`scripts/package.sh`、`scripts/smoke-test.sh`
- Python 编译：使用 `compile()` 在内存中编译 `lib/avatarctl.py`，通过；为避免生成/改写 pyc，没有直接运行会落盘的 `py_compile`
- JSON 解析：默认/本地配置、默认 state、schema、生产 workflow 全部通过 `jq empty`
- 文件权限：入口和脚本为 0755；主要配置/文档/workflow 为 0644 或 0664

代码审查结论：

- `bin/avatarctl`、所有 Shell 脚本均有 `set -euo pipefail`；未使用 `-E`，但脚本没有 ERR trap。
- 大多数变量引用正确；安装脚本的删除范围由可覆盖环境变量控制，缺少目标安全防护。
- JSON state/job 使用临时文件 + fsync + `os.replace`，具备原子性。
- 图片也使用临时文件 + fsync + replace。
- history 使用 append+fsync，但并发安全依赖调用方持有生成锁；当前调用路径满足。
- HTTP、subprocess 和 wait 均设置超时。
- stderr 没有被静默丢弃；发送结果会进入 job JSON，但可能包含较多 CLI 输出。
- 图片路径由内部生成；`backup --output` 可写任意调用者有权限的路径，这是显式管理命令。
- `job-status` 的 job_id 直接拼接路径，argparse 不限制字符；`../../...` 可形成状态目录外 JSON 读取路径（仍要求 `.json` 后缀），属于路径穿越读风险。
- state schema 只声明顶层 required，未约束字段类型/嵌套结构，且运行代码没有调用 schema 验证。

## 13. Test Inventory and Test Results

测试资产：

- unittest/mock：`tests/test_avatarctl.py`
- smoke：`scripts/smoke-test.sh`
-人工验收：`docs/TEST-PLAN.md`
- doctor：`avatarctl doctor`
- ComfyUI 在线生成：`show --foreground --no-send`
- 异步/去重：真实 `show --no-send`
- Telegram：真实 `show`
- 自然语言端到端：通过 Hermes 对话

实际执行：

- unittest：8 项，7 pass，1 fail。
- 失败项：`test_masked_workflow_hash`，测试期望旧 hash `54d041...`，实际生产 workflow masked hash 为 `279d353...`。
- mock 覆盖并通过：最小 patch、字段拒绝、独立文字/MEDIA、队列去重、parser 默认值、prompt 序列化。
- 静态语法和 JSON 测试通过。
- ComfyUI 只读健康检查通过。

仅代码审查、未执行：

- `doctor`（会调用 `ensure_runtime()`，不严格只读）。
- 完整 `scripts/smoke-test.sh`（包含 `py_compile` 落盘及 doctor）。
- 所有真实 show/render、在线生成、Telegram、异步、重发和自然语言 E2E，因会生成、发送或改变生产状态。

## 14. Git and Deployment Status

开发源 Git：

- branch：`master`
- commit：`5ac9055 Import current working yinyue-avatar skill`
- status：clean
- remote：无
- log：仅观察到上述 1 个 commit

生产部署：

- 不是 Git 仓库。
- 无法用 Git 判定未提交/未跟踪文件；逐文件对比已证实相对源码存在三类差异。
- 生产 workflow 与生产 local baseline 自洽，但未同步回 Git 源。
- 当前 Git clean 不能代表生产 clean。

结论：生产可以继续运行，但不具备安全继续开发的版本控制基线。若直接从 Git 源安装，会覆盖生产 workflow 和生产独有角色历史；虽然安装脚本保留 local config，保留的生产 hash 会与源 workflow 不匹配，从而使后续生成全部被 hash 校验拒绝。

## 15. Current Confirmed Problems

### P1 — 源码与生产 workflow 分叉

Severity: High  
Status: 当前确认存在  
Evidence: `diff -qr` 显示 workflow 不同；具体差异为 node 87 固定提示词；raw hash 分别为 `038651...` 与 `6e5c6b...`，masked hash 分别为 `ce331d...` 与 `279d35...`。  
Affected files: 源/生产 `workflow/Krea2_YINYUE_cosplay01.json`、各自 `config.local.json`  
Runtime impact: 直接从 clean Git 源重装会产生 workflow/hash mismatch，生成任务全部失败；也可能静默改变人物构图语义。  
Recommended action: 下一阶段先决定哪个 workflow 是权威版本，把它及 baseline、测试、文档纳入同一 Git commit，再设计可验证部署。  
Safe to defer: 否，不应在继续功能开发或再次部署前推迟。

### P2 — baseline 文档、默认配置和测试不一致

Severity: High  
Status: 当前确认存在  
Evidence: 生产有效 hash 为 `279d353...`；README、`config.json` 和测试仍引用 `54d041...`；实际 unittest 1/8 失败。  
Affected files: `README.md`, `config.json`, `config.local.json`, `tests/test_avatarctl.py`, production workflow  
Runtime impact: 当前生产因 local override 可运行，但新安装、迁移、测试和故障恢复不可复现。  
Recommended action: 在确定权威 workflow 后，统一默认 baseline、生产覆盖、README 和测试；增加正式只读 hash 检查/显式重建命令。  
Safe to defer: 否，不应在建立开发基线前推迟。

### P3 — 安装脚本会删除目标，且缺少源=目标保护

Severity: High  
Status: 当前确认存在（静态）  
Evidence: `scripts/install.sh` 无条件 `rm -rf "$DEST_ROOT"` 后复制；若在已部署目录直接运行且 SOURCE_ROOT=DEST_ROOT，会先删除源再复制；可覆盖环境变量也没有空值、根目录、同路径或目录归属校验。  
Affected files: `scripts/install.sh`  
Runtime impact: 错误调用可破坏生产 Skill；从当前源码部署还会触发 P1 的 hash mismatch。  
Recommended action: 下一阶段加入 canonical path、安全目标校验、source≠destination、staging+原子切换和部署后只读验收。  
Safe to defer: 仅在明确禁止运行安装脚本时短期可推迟；部署前不可推迟。

### P4 — `job-status` 存在路径穿越式 JSON 读取

Severity: Medium  
Status: 当前确认存在（静态，未利用）  
Evidence: `cmd_job_status()` 使用 `jobs / f"{job_id}.json"`，未要求 UUID/文件名；`../` 可逃出 jobs 目录。  
Affected files: `lib/avatarctl.py`  
Runtime impact: 能调用 helper 的主体可能读取 state 根附近或更上层、名称以 `.json` 结尾的文件；受文件权限限制。  
Recommended action: 严格校验 32 位 hex UUID，并 resolve 后验证父目录。  
Safe to defer: 否，建议列入首轮安全修复。

### P5 — 去重检查与 job 创建不是原子操作

Severity: Medium  
Status: 当前确认存在（静态）；历史中未确认实际重复发送  
Evidence: `queue_job()` 在无锁状态下先扫描、后写新 UUID job；两个并发进程可能都看不到对方。  
Affected files: `lib/avatarctl.py`  
Runtime impact: 极端并发可重复生成、重复提交状态并重复发送；生成锁只会把重复任务串行化，不能消除它们。  
Recommended action: 在专用短时队列锁内完成 fingerprint 检查和 job 创建，避免持有生成锁。  
Safe to defer: 可短期推迟，但在并发测试/生产流量增加前应修复。

### P6 — schema 基本不提供结构保护

Severity: Medium  
Status: 当前确认存在  
Evidence: schema 只列顶层 required，未描述嵌套属性和类型；运行代码不加载 schema。  
Affected files: `schemas/state.schema.json`, `lib/avatarctl.py`  
Runtime impact: state 被截断、字段类型变化或嵌套缺失时会在运行深处以 KeyError/TypeError 失败，错误定位差。  
Recommended action: 完整定义 schema，并在读取/提交候选 state 时验证；保持失败不写入。  
Safe to defer: 可短期推迟，但迁移和状态演进前应完成。

### P7 — 没有正式 baseline 重建命令或单一 baseline 文件

Severity: Medium  
Status: 当前确认存在  
Evidence: CLI 没有 `rebuild-hash`；README 只有原则性描述；baseline 分散在默认配置、本地配置、文档和测试。  
Affected files: `lib/avatarctl.py`, `config.json`, `config.local.json`, `README.md`, `tests/test_avatarctl.py`  
Runtime impact: 人工更新容易再次形成当前分叉，迁移和审计不可重复。  
Recommended action: 增加明确、默认只预览、显式确认才写入的 baseline 工具；定义唯一权威来源和派生检查。  
Safe to defer: 不应晚于 P1/P2 的基线统一工作。

### P8 — 生产专属角色设定未纳入源码，且身份声明互相冲突

Severity: Medium  
Status: 当前确认存在  
Evidence: `docs/yinyue_history.md` 只在生产存在；`persona.md`/默认 state 声明成年角色，而历史文档包含角色未成年时期的露骨性暴力设定。  
Affected files: `docs/yinyue_history.md`, `persona.md`, `defaults/state.default.json`  
Runtime impact: 部署会丢失权威角色前史；年龄/内容边界冲突会造成路由、内容安全和角色一致性风险。当前运行代码并未读取该 history 文档，因此“canonical”声明实际上不生效。  
Recommended action: 明确是否应纳入源码及是否为运行输入；清理年龄和内容边界冲突，建立可审计的角色设定来源。  
Safe to defer: 不建议在扩展角色记忆/提示词前推迟。

### P9 — 运行数据无轮转，遗留 pending 不会自动收敛

Severity: Low  
Status: 当前确认存在  
Evidence: output 196 文件/793 MiB，history 196 行，jobs 200 文件；无清理/轮转配置；pending 保留 2026-07-19 失败记录。  
Affected files: `lib/avatarctl.py`, runtime state directories  
Runtime impact: 磁盘和目录扫描成本持续增长；旧 pending 可能误导人工排障。  
Recommended action: 后续增加只报告/显式执行的保留策略和 pending 生命周期，不在本阶段清理。  
Safe to defer: 是，当前容量下可推迟。

### P10 — 本地配置权限和 PATH 解释器不够确定

Severity: Low  
Status: 当前确认存在  
Evidence: `config.local.json` 为 0664；helper 使用未固定的 `python3`，当前解析到 Miniforge Python 3.13.12；Hermes 依赖 `.bashrc` 设置 PATH。  
Affected files: `config.local.json`, `bin/avatarctl`, user shell environment  
Runtime impact: 同组用户可读 channel；systemd/detached 环境 PATH 变化可能选择不同 Python 或找不到 Hermes。  
Recommended action: 本地配置改为最小权限；安装时记录/验证绝对 interpreter 和 Hermes CLI，或在 config 中显式设置。  
Safe to defer: 是，但部署可复现性工作应一并处理。

## 16. Historical Problems No Longer Reproduced

### H1 — Hermes CLI 不存在

Severity: Informational  
Status: 历史出现，当前证据表明已修复  
Evidence: 2026-07-19 有 5 个 failed job 报 `[Errno 2] No such file or directory: 'hermes'`；当前 `command -v hermes` 成功，最近任务投递成功。  
Affected files: 历史 job JSON；当前依赖 PATH  
Runtime impact: 当时生成后投递失败；当前未复现。  
Recommended action: 保留 doctor/部署后 PATH 验证。  
Safe to defer: 是。

### H2 — ComfyUI 请求超时

Severity: Informational  
Status: 历史出现，当前健康检查正常；无法保证不会间歇复发  
Evidence: 2026-07-23 有 3 个 timeout failed job；2026-07-28 `/system_stats` 成功且最近任务完成。  
Affected files: 历史 job JSON、ComfyUI/网络环境  
Runtime impact: 当时生成失败；当前未复现。  
Recommended action: 后续补充可观测性和错误分类，不自动重试生成。  
Safe to defer: 是。

### H3 — workflow hash mismatch

Severity: Informational  
Status: 历史生产故障已通过 local baseline 修正，但基线治理问题仍由 P1/P2 持续存在  
Evidence: 2026-07-23 有 3 个 hash mismatch failed job；当前生产 actual=expected，最近生成完成。  
Affected files: workflow/config/history jobs  
Runtime impact: 历史任务被安全拒绝；当前生产不受阻。  
Recommended action: 按 P1/P2 建立单一来源。  
Safe to defer: 当前运行可暂缓，开发/部署前不可。

### H4 — Telegram MEDIA 发送失败

Severity: Informational  
Status: 历史出现，当前未复现  
Evidence: pending 中保留 2026-07-19 “No deliverable text or media remained after processing MEDIA tags”；当前代码将文字与 MEDIA 分开，最近 delivery ok。  
Affected files: 旧 pending、`lib/avatarctl.py`  
Runtime impact: 历史图片生成成功但媒体未送达；当前最近任务成功。  
Recommended action: 用 mock 回归保持分开发送；不要用真实 Telegram 测试作为常规单测。  
Safe to defer: 是。

## 17. Risks and Technical Debt

除上述确认问题外，以下事项尚无法从现有证据确认：

- ComfyUI custom nodes 的准确包名和版本。
- 远端模型/LoRA 是否有可恢复副本及 checksum。
- systemd user manager 在 Hermes 实际非沙箱环境中的长期可靠性。
- Telegram 重试时是否可能因“服务端已接收、CLI 超时”造成重复发送；当前重试没有幂等键。
- `systemd-run` 成功后 worker 极快完成时的 job metadata 合并竞态已做注释性缓解，但 `job_update()` 本身无文件锁，多进程同时更新同一 job 仍可能丢字段。
- 日志目录为空意味着 detached worker 的 stdout 日志要么没有产生，要么历史任务主要由 systemd journal 承载；当前没有统一日志采集/保留说明。
- backup 会包含本地 Telegram channel 配置，备份文件权限和存放位置由调用者决定。
- `docs/yinyue_history.md` 标为 canonical，但当前运行代码完全不读取，角色设定来源存在文档/实现漂移。

## 18. Migration and Independence Assessment

逻辑独立性：较好。Skill 不调用其他 Skill、`telegram-media-sender` 或其他 helper；Python 仅标准库；状态、workflow、发送逻辑均自带。

部署独立性：不足。缺少远端 ComfyUI 节点/模型 manifest、checksums 和安装映射；ComfyUI 使用机器专属 LAN IP；LoRA 含安装目录语义；Hermes/Telegram/PATH 依赖机器配置。

迁移完整性：当前不合格。Git 源不含生产角色历史，源 workflow 不等于生产 workflow，且生产 local baseline 与源 workflow 不匹配。直接重装会导致功能中断。

可复制性：不足。没有 release manifest、部署内容 hash、正式 baseline 工具、remote 或 CI；生产目录不是 Git 工作树。

结论：符合“固定 helper + 轻量 Skill”，但尚不满足可靠的独立迁移和可验证部署要求。

## 19. Recommended Next Development Priorities

1. 冻结生产写操作，确认生产 workflow 是否为权威版本。
2. 将权威 workflow、角色设定决策和有效 baseline 回灌开发源，形成新的 clean Git commit。
3. 统一 `config.json`、本地覆盖策略、README 和测试；让测试全绿。
4. 修复安装器安全边界，加入 staging、source/target 校验和部署后验证。
5. 增加只读 `verify-baseline` 与受控 `rebuild-hash` 工作流。
6. 修复 `job-status` job_id 路径校验和队列去重竞态。
7. 完整化 state schema 与验证。
8. 建立 ComfyUI 节点/模型/LoRA manifest 和迁移检查。
9. 设计明确的 jobs/history/output/pending 保留与日志策略。

## 20. Safe Starting Point for the Next Codex Task

下一条 Codex 指令建议聚焦：

> “以当前生产 workflow 为候选权威版本，先做源码与部署基线统一方案；在不生成图片、不发送 Telegram、不清理状态的前提下，把生产差异安全回灌 Git 源，统一 baseline/README/tests，并改造安装器为可验证的安全部署。先展示拟变更清单和回滚方案，再实施。”

开始前应再次确认生产没有 running/queued job，并备份（只读核对既有备份不足以替代新的受控备份）。不要直接运行现有 `scripts/install.sh`。

## 21. Commands Executed

以下为按用途归并的实际命令；所有写入型运行命令均未执行：

```text
pwd
realpath .
ls -ld /home/james/.hermes/skills/... /mnt/data_nvme/apps/hermes-skills
readlink -f <production-path>
find /home/james /mnt/data_nvme -name yinyue-avatar / *yinyue-avatar*.zip|tar.gz
find/tree-like inventory（排除 .git、venv、cache、output）
sed/tail 读取 SKILL、README、Python、Shell、测试、schema、persona、docs
rg 搜索绝对路径、环境变量、敏感关键词、日志错误、systemd/cron/profile 引用
jq 解析配置、workflow nodes、state/history/jobs/pending 元数据
sha256sum workflow files
Python 只读计算 canonical masked workflow hash 和 workflow diff
diff -qr source deployment（排除 .git/__pycache__/本报告）
git status/log/remote/branch（生产及开发源，只读）
bin/avatarctl --help
bash -n bin/avatarctl scripts/*.sh
Python compile() 内存语法编译
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
jq empty JSON files
python3/bash/jq/curl/sha256sum/flock/hermes 版本与 command -v
curl --max-time 5 http://192.168.100.211:8188/system_stats
find/stat/du/wc/ps/systemctl/crontab 只读状态检查
```

明确未执行：`avatarctl context/status/doctor/history/jobs/job-status/wait/update/show/render/resend-last/backup/_worker`、`smoke-test.sh`、任何生成/发送/重置/清理/hash 更新、Git 写操作或依赖安装。

## 22. Files Read

生产 Skill：

```text
SKILL.md
README.md
persona.md
config.json
config.local.json（仅分析结构和脱敏值）
config.local.example.json
bin/avatarctl
lib/avatarctl.py
defaults/state.default.json
schemas/state.schema.json
scripts/install.sh
scripts/package.sh
scripts/smoke-test.sh
tests/test_avatarctl.py
workflow/Krea2_YINYUE_cosplay01.json
workflow/Krea2_YINYUE_cosplay01.json.backup-20260719-175536
docs/TEST-PLAN.md
docs/yinyue_history.md
```

开发源：

```text
.git metadata（通过 git 命令）
config.local.json（仅结构/hash）
workflow/Krea2_YINYUE_cosplay01.json
其余文件通过 diff 元数据比较
```

运行状态：

```text
state.json（结构、continuity 和计数）
history.jsonl（事件结构、行数、时间；未复制私人内容）
jobs/*.json（状态、错误签名、投递结果）
pending/*.json（状态和错误签名）
baseline-backups/*（文件元数据）
logs/*（目录为空）
output/*（仅名称、大小、时间、计数和 last_image 存在性）
```

系统只读信息：相关 shell profile 行、systemd/cron 文件名与进程/依赖版本；未读取或报告无关私人配置内容。

## 23. Files Created or Modified

仅创建：

```text
docs/CURRENT_STATE_REVIEW_20260728.md
```

未修改任何现有 Python、Shell、JSON、YAML、Markdown、workflow、配置、baseline、状态、历史、job、pending、日志或图片文件。测试使用 `PYTHONDONTWRITEBYTECODE=1`，Python 语法验证使用内存 `compile()`，没有创建新的 pyc。
