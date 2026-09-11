# yinyue-avatar v0.2.4 测试计划

## 1. 安装检查

```bash
AVATARCTL="$HOME/.hermes/skills/roleplay/yinyue-avatar/bin/avatarctl"
"$AVATARCTL" doctor
```

## 2. 前台隔离生成，不发送

```bash
"$AVATARCTL" show --foreground --no-send
```

确认生成、下载、状态提交均成功。

## 3. 后台排队与 60 秒规避

```bash
START=$(date +%s)
RESULT=$("$AVATARCTL" show --no-send)
END=$(date +%s)
echo "$RESULT"
echo "elapsed=$((END-START))s"
```

应在 10 秒内返回 `queued=true`。

取得 `job_id` 后：

```bash
"$AVATARCTL" job-status JOB_ID
```

最终应为 `completed`。

## 4. 重复调用去重

连续执行：

```bash
"$AVATARCTL" show --no-send
"$AVATARCTL" show --no-send
```

当第一项仍为 queued/running 时，第二项应返回相同 `job_id` 和 `deduplicated=true`。

## 5. Telegram 投递

```bash
"$AVATARCTL" show
```

后台任务完成后，Telegram 应收到：

1. 一条短文字
2. 一条真实图片附件

任务中的 `delivery.media.ok` 应为 true。

## 6. 自然语言路由

依次发送：

```text
银月，你现在穿的什么？给我看看。
银月，你现在穿什么？只告诉我，不要发图片。
银月，把鞋换成白色运动鞋，其他不变，坐在床边给我看看。
银月，再拍一张，衣服和场景都别变。
```

验收：

- 第一条：`context` → `show` → Agent 静默
- 第二条：只读 `context`，不出图
- 第三条：只 patch footwear 与 pose，然后 `render`
- 第四条：只调用 `show`
- 不得调用其他 Skill
- 不得调用 `wait`
- 不得出现 60 秒 terminal timeout
- 不得重复生成或重复发送
