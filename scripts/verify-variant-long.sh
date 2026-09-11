#!/usr/bin/env bash
# verify-variant-long.sh: 处理超长 avatarctl verify-variant 命令
# 当命令超过 8KB 被 shell parser block 时使用

# 使用方法：
#   1. 先用 write_file 保存命令到这个文件
#   2. 然后运行：bash /home/james/.hermes/skills/roleplay/yinyue-avatar/scripts/verify-variant-long.sh

set -euo pipefail

# 默认值
TRANSACTION_ID=""
VARIANT_WORKFLOW_PATH=""
OBSERVED_SLOTS_JSON=""

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --transaction)
            TRANSACTION_ID="$2"
            shift 2
            ;;
        --variant-workflow-path)
            VARIANT_WORKFLOW_PATH="$2"
            shift 2
            ;;
        --observed-slots-json)
            OBSERVED_SLOTS_JSON="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# 检查必填参数
if [[ -z "$TRANSACTION_ID" || -z "$VARIANT_WORKFLOW_PATH" || -z "$OBSERVED_SLOTS_JSON" ]]; then
    echo "Usage: verify-variant-long.sh \\" >&2
    echo "  --transaction <ID> \\" >&2
    echo "  --variant-workflow-path <PATH> \\" >&2
    echo "  --observed-slots-json <JSON>" >&2
    exit 1
fi

# 执行命令
AVATARCTL="$HOME/.hermes/skills/roleplay/yinyue-avatar/bin/avatarctl"
"$AVATARCTL" verify-variant \
    --transaction "$TRANSACTION_ID" \
    --variant-workflow-path "$VARIANT_WORKFLOW_PATH" \
    --observed-slots-json "$OBSERVED_SLOTS_JSON"
