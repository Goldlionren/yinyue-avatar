# MCP Workflow guide

## Workflow 要求

生产 MCP Workflow 放在各 GPU 主机 registry 指定路径。使用 ComfyUI `File > Save (As)` 保存 frontend-format（含 `nodes[]` / `links[]`），不要只提供 `Export (API)`：当前 Comfy MCP 可运行 API export，但不能列出或设置其 slots。

Workflow 内部负责人物模型、固定人物 LoRA、风格/画质词和 prompt pipeline。Agent 只传简单事实 prompt 或局部编辑指令。

建议文件：

```text
F:\AI\YinyueAvatar\workflows\yinyue_cosplay01.json  # 5090
F:\AI\YinyueAvatar\workflows\yinyue_edit01.json
D:\AI\YinyueAvatar\workflows\Krea2_YINYUE_cosplay01.json  # 3060 当前生产 frontend
D:\AI\YinyueAvatar\workflows\yinyue_edit01.json
```

## 部署与验证

MCP 没有通用的“上传任意 workflow JSON 到任意目录”工具；`upload_file` 只把 MCP 主机已有文件送入 ComfyUI input。使用人工复制，或 dry-run-first 工具：

```bash
scripts/deploy-workflow.sh --target comfy_3060 --source /absolute/yinyue_cosplay01.json
scripts/deploy-workflow.sh --target comfy_3060 --source /absolute/yinyue_cosplay01.json --apply
```

工具拒绝覆盖已存在文件。部署后依次用对应 MCP 调用：

```text
server_info()
list_workflow_slots(workflow_path=...)
validate_workflow(workflow_path=...)
```

把真实 slot address 写入 `parameter_bindings`，再把该 target 的 `workflow_exists` 和 `interface_verified` 改为 true。不要凭 node ID 猜 slot。

当前 3060 cosplay Workflow 的业务参数只有 `63.value`、`49.aspect_ratio`、`49.megapixels`、`92.noise_seed` 与 `93.noise_seed`，默认分辨率为 `9:16`、`1.5MP`。helper 为每个新事务生成一个 8 位整数，并把同一个值写入两个 sampler seed 槽。Comfy MCP 转换器只会丢弃 frontend 的 `randomize` 标记，不会执行随机化，因此不能依赖静态 Workflow 文件中的 control-after-generate，也不要让两个 sampler 使用不同 seed。

## 添加第三个 Workflow

1. 在 GPU 上保存新的 frontend workflow，不覆盖旧文件。
2. 用 MCP 验证 workflow 和 slots。
3. 在 registry `workflows` 添加一个 entry：id/purpose/description/allowed_targets/remote_paths/capabilities/input_roles/output_role/default_parameters/parameter_bindings/target_status。
4. 若新 purpose 可归入已有 router 类，仅改 registry；全新自然语言 intent 类才需要扩展 `route_intent`。
5. 运行 unit tests 和 `avatarctl workflows`。

## 添加第三台 GPU

1. 在 Hermes 配置新的 MCP server。
2. 在 registry `targets` 添加 MCP 名称、remote root/output root 和 rank。
3. 在每个可用 Workflow 添加 allowed target、remote path、已验证 status。
4. 将 target 加入 `config.json` 的 `execution.allowed_targets`，按需改 default target。

## 为什么没有 SHA baseline

Workflow 是用户可随时修改的生产资产。模型、LoRA、strength、sampler、scheduler、steps、resolution、prompt optimizer、node topology 和 output processing 都不应触发 hash 错误。系统只检查当前任务需要的语义 slot 和输出接口。
