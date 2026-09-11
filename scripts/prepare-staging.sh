#!/usr/bin/env bash
set -euo pipefail
umask 077

SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
PRODUCTION_SKILL=/home/james/.hermes/skills/roleplay/yinyue-avatar
PRODUCTION_STATE=/home/james/.hermes/state/yinyue-avatar
STAMP=$(TZ=UTC date +%Y%m%dT%H%M%SZ)
STAGING_ROOT="/mnt/data_nvme/tmp/yinyue-avatar-staging-$STAMP"
APPLY=0

usage() {
  cat <<'EOF'
Usage: prepare-staging.sh [--apply] [--root /mnt/data_nvme/tmp/yinyue-avatar-staging-NAME]
                          [--production-skill PATH] [--production-state PATH]

Default is dry-run. Preparation copies data only. It never runs avatarctl,
starts a worker, submits ComfyUI, or sends Telegram.
EOF
}

while (($#)); do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --root) STAGING_ROOT=${2:?missing root}; shift 2 ;;
    --production-skill) PRODUCTION_SKILL=${2:?missing production skill}; shift 2 ;;
    --production-state) PRODUCTION_STATE=${2:?missing production state}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "$STAGING_ROOT" = /* && -n "$STAGING_ROOT" ]] ||
  { echo "ERROR: staging root must be absolute" >&2; exit 3; }
CANONICAL_ROOT=$(realpath -m -- "$STAGING_ROOT")
case "$CANONICAL_ROOT" in
  /mnt/data_nvme/tmp/yinyue-avatar-staging-*|/tmp/yinyue-avatar-staging-*) ;;
  *) echo "ERROR: staging root must be a dedicated yinyue staging path" >&2; exit 3 ;;
esac
[[ "$CANONICAL_ROOT" != /mnt/data_nvme/tmp && "$CANONICAL_ROOT" != /tmp && "$CANONICAL_ROOT" != / ]] ||
  { echo "ERROR: dangerous staging root" >&2; exit 3; }
[[ ! -L "$STAGING_ROOT" ]] ||
  { echo "ERROR: staging root must not be a symbolic link" >&2; exit 3; }
[[ -d "$PRODUCTION_SKILL" && -f "$PRODUCTION_SKILL/config.local.json" ]] ||
  { echo "ERROR: production Skill source is incomplete" >&2; exit 4; }
[[ -f "$PRODUCTION_STATE/state.json" ]] ||
  { echo "ERROR: production state source is incomplete" >&2; exit 4; }
ACTIVE_JOBS=$(find "$PRODUCTION_STATE/jobs" -maxdepth 1 -type f -name '*.json' -print0 2>/dev/null |
  xargs -0 -r jq -r 'select(.status == "queued" or .status == "running") | .job_id // input_filename')
if [[ -n "$ACTIVE_JOBS" ]]; then
  echo "ERROR: production state has an active job; staging copy refused" >&2
  exit 4
fi
if [[ -e "$PRODUCTION_STATE/avatar.lock" ]] && command -v fuser >/dev/null &&
  fuser "$PRODUCTION_STATE/avatar.lock" >/dev/null 2>&1; then
  echo "ERROR: production avatar.lock is held; staging copy refused" >&2
  exit 4
fi
[[ "$(realpath -m -- "$PRODUCTION_SKILL")" != "$CANONICAL_ROOT"* ]] ||
  { echo "ERROR: staging root overlaps production Skill" >&2; exit 3; }
[[ "$(realpath -m -- "$PRODUCTION_STATE")" != "$CANONICAL_ROOT"* ]] ||
  { echo "ERROR: staging root overlaps production state" >&2; exit 3; }

echo "Source checkout: $SOURCE_ROOT"
echo "Read-only production Skill source: $(realpath -- "$PRODUCTION_SKILL")"
echo "Read-only production state source: $(realpath -- "$PRODUCTION_STATE")"
echo "Staging root: $CANONICAL_ROOT"
echo "Mode: $([[ "$APPLY" -eq 1 ]] && echo apply || echo dry-run)"
echo "Telegram: disabled"
echo "Worker and ComfyUI prompt: not started"
if ((APPLY == 0)); then
  echo "DRY RUN ONLY: no files changed."
  exit 0
fi

[[ ! -e "$CANONICAL_ROOT" ]] ||
  { echo "ERROR: staging root already exists" >&2; exit 5; }
mkdir -p -- "$CANONICAL_ROOT/skill" "$CANONICAL_ROOT/state"
chmod 0700 "$CANONICAL_ROOT"
cp -a -- "$SOURCE_ROOT/." "$CANONICAL_ROOT/skill/"
cp -a -- "$PRODUCTION_STATE/." "$CANONICAL_ROOT/state/"
cp -a -- "$PRODUCTION_SKILL/workflow/." "$CANONICAL_ROOT/skill/workflow/"

BLOCKER="$CANONICAL_ROOT/skill/bin/hermes-send-disabled"
cat > "$BLOCKER" <<'EOF'
#!/usr/bin/env bash
echo "ERROR: Telegram is disabled in yinyue-avatar staging" >&2
exit 97
EOF
chmod 0700 "$BLOCKER"

COMFY_URL=$(jq -r '.comfyui.base_url' "$PRODUCTION_SKILL/config.local.json")
jq -n \
  --arg state "$CANONICAL_ROOT/state" \
  --arg comfy "$COMFY_URL" \
  --arg blocker "$BLOCKER" \
  '{
    runtime:{state_dir:$state,launcher:"disabled"},
    execution:{mode:"direct_http"},
    comfyui:{base_url:$comfy},
    telegram:{enabled:false,default_channel:"DISABLED",hermes_cli:$blocker}
  }' > "$CANONICAL_ROOT/skill/config.local.json"
chmod 0600 "$CANONICAL_ROOT/skill/config.local.json"

jq -n \
  --arg root "$CANONICAL_ROOT" \
  --arg created "$(TZ=UTC date --iso-8601=seconds)" \
  --arg id "$(python3 -c 'import uuid; print(uuid.uuid4())')" \
  '{schema_version:1,kind:"yinyue-avatar-isolated-staging",root:$root,created_at:$created,staging_id:$id}' \
  > "$CANONICAL_ROOT/.yinyue-avatar-staging.json"
chmod 0600 "$CANONICAL_ROOT/.yinyue-avatar-staging.json"

(
  cd "$CANONICAL_ROOT"
  find skill state -type f -print0 | sort -z | xargs -0 sha256sum
) > "$CANONICAL_ROOT/MANIFEST_SHA256.txt"
chmod 0600 "$CANONICAL_ROOT/MANIFEST_SHA256.txt"

echo "Prepared isolated staging: $CANONICAL_ROOT"
echo "No worker, ComfyUI prompt, or Telegram send was executed."
echo "After separate authorization, suggested commands:"
echo "  $CANONICAL_ROOT/skill/bin/avatarctl context"
echo "  $CANONICAL_ROOT/skill/bin/avatarctl transition --json '<strict JSON>' --render --foreground --no-send"
echo "Cleanup dry-run:"
echo "  $CANONICAL_ROOT/skill/scripts/cleanup-staging.sh --root $CANONICAL_ROOT"
