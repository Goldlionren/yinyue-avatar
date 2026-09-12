#!/usr/bin/env bash
set -euo pipefail
umask 077

SKILL_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TEST_ROOT=$(mktemp -d /tmp/yinyue-safe-scripts.XXXXXX)
TEST_HOME="$TEST_ROOT/home"
mkdir -p "$TEST_HOME"
cleanup() {
  case "$TEST_ROOT" in /tmp/yinyue-safe-scripts.*) rm -rf -- "$TEST_ROOT" ;; esac
}
trap cleanup EXIT

INSTALL="$SKILL_ROOT/scripts/install.sh"
DEST="$TEST_HOME/.hermes/skills/roleplay/yinyue-avatar"
DEPLOY="$SKILL_ROOT/scripts/deploy-workflow.sh"

# Workflow deployment is dry-run by default and accepts every registered GPU.
for target in comfy_3060 comfy_4080s comfy_5090; do
  bash "$DEPLOY" --target "$target" \
    --source "$SKILL_ROOT/workflow/Krea2_YINYUE_cosplay01.json" \
    --name yinyue_cosplay01.json > "$TEST_ROOT/deploy-$target-dry.txt"
  grep -q 'DRY RUN ONLY' "$TEST_ROOT/deploy-$target-dry.txt"
done

# Dry-run must not write.
HOME="$TEST_HOME" bash "$INSTALL" > "$TEST_ROOT/install-dry.txt"
[[ ! -e "$DEST" ]]

# Dangerous and non-allowlisted paths must be rejected.
if HOME="$TEST_HOME" bash "$INSTALL" --destination / --apply >/dev/null 2>&1; then
  echo "install accepted /" >&2; exit 1
fi
if HOME="$TEST_HOME" bash "$INSTALL" --destination "$TEST_HOME/not-allowed" --apply >/dev/null 2>&1; then
  echo "install accepted non-allowlisted path" >&2; exit 1
fi

# Existing local config must survive a successful isolated install.
mkdir -p "$DEST"
printf '%s\n' old-sentinel > "$DEST/old-sentinel"
printf '%s\n' '{"local_secret_sentinel":"preserve-me"}' > "$DEST/config.local.json"
HOME="$TEST_HOME" bash "$INSTALL" --apply > "$TEST_ROOT/install-apply.txt"
grep -q preserve-me "$DEST/config.local.json"
find "$TEST_HOME/.hermes/backups/yinyue-avatar" \
  -path '*/install-*/MANIFEST_AFTER_SHA256.txt' -type f | grep -q .

# Inject a failure after switching; trap must restore the previous Skill.
before=$(sha256sum "$DEST/SKILL.md" "$DEST/config.local.json")
if HOME="$TEST_HOME" YINYUE_AVATAR_INSTALL_FAILPOINT=after-switch \
  bash "$INSTALL" --apply >"$TEST_ROOT/install-fail.txt" 2>&1; then
  echo "install failpoint unexpectedly succeeded" >&2; exit 1
fi
after=$(sha256sum "$DEST/SKILL.md" "$DEST/config.local.json")
[[ "$before" == "$after" ]]

echo "safe installer dry-run/path/local-config/rollback tests passed"

if [[ "${RUN_STAGING_SCRIPT_TESTS:-0}" == 1 ]]; then
  PROD_SKILL="$TEST_ROOT/production-skill-fixture"
  PROD_STATE="$TEST_ROOT/production-state-fixture"
  cp -a "$SKILL_ROOT" "$PROD_SKILL"
  mkdir -p "$PROD_STATE"/{jobs,pending,logs,output}
  cp "$SKILL_ROOT/defaults/state.default.json" "$PROD_STATE/state.json"
  jq -n \
    '{comfyui:{base_url:"http://127.0.0.1:9"},execution:{mode:"direct_http"}}' \
    > "$PROD_SKILL/config.local.json"
  STAGING_ROOT="/tmp/yinyue-avatar-staging-script-test-$$"
  PREPARE="$SKILL_ROOT/scripts/prepare-staging.sh"
  CLEANUP="$SKILL_ROOT/scripts/cleanup-staging.sh"
  bash "$PREPARE" --root "$STAGING_ROOT" \
    --production-skill "$PROD_SKILL" --production-state "$PROD_STATE" \
    > "$TEST_ROOT/staging-dry.txt"
  [[ ! -e "$STAGING_ROOT" ]]
  bash "$PREPARE" --apply --root "$STAGING_ROOT" \
    --production-skill "$PROD_SKILL" --production-state "$PROD_STATE" \
    > "$TEST_ROOT/staging-apply.txt"
  [[ "$(jq -r '.telegram.enabled' "$STAGING_ROOT/skill/config.local.json")" == false ]]
  [[ "$(jq -r '.runtime.state_dir' "$STAGING_ROOT/skill/config.local.json")" == "$STAGING_ROOT/state" ]]
  [[ -f "$STAGING_ROOT/.yinyue-avatar-staging.json" ]]
  bash "$CLEANUP" --root "$STAGING_ROOT" > "$TEST_ROOT/cleanup-dry.txt"
  [[ -d "$STAGING_ROOT" ]]
  ln -s /tmp "$STAGING_ROOT/escape-link"
  if bash "$CLEANUP" --root "$STAGING_ROOT" --apply >/dev/null 2>&1; then
    echo "cleanup accepted a staging symlink" >&2; exit 1
  fi
  unlink "$STAGING_ROOT/escape-link"
  bash "$CLEANUP" --root "$STAGING_ROOT" --apply > "$TEST_ROOT/cleanup-apply.txt"
  [[ ! -e "$STAGING_ROOT" ]]
  echo "isolated staging path/Telegram/cleanup tests passed"
fi
