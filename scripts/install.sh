#!/usr/bin/env bash
set -euo pipefail
umask 077

SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
DEST_ROOT="${YINYUE_AVATAR_INSTALL_DIR:-$HOME/.hermes/skills/roleplay/yinyue-avatar}"
APPLY=0

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [--apply] [--destination ABSOLUTE_PATH]

Default is dry-run. The only permitted destination is exactly:
  $HOME/.hermes/skills/roleplay/yinyue-avatar

This installer never migrates state, starts a worker, calls ComfyUI, or sends
Telegram.
EOF
}

while (($#)); do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --destination) DEST_ROOT=${2:?missing destination}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$DEST_ROOT" && "$DEST_ROOT" = /* ]] ||
  { echo "ERROR: destination must be a non-empty absolute path" >&2; exit 3; }
[[ "$DEST_ROOT" != / && "$DEST_ROOT" != "$HOME" && "$DEST_ROOT" != "$HOME/" ]] ||
  { echo "ERROR: dangerous destination: $DEST_ROOT" >&2; exit 3; }

ALLOWED_DEST=$(realpath -m -- "$HOME/.hermes/skills/roleplay/yinyue-avatar")
CANONICAL_SOURCE=$(realpath -- "$SOURCE_ROOT")
CANONICAL_DEST=$(realpath -m -- "$DEST_ROOT")
[[ "$CANONICAL_DEST" == "$ALLOWED_DEST" ]] ||
  { echo "ERROR: destination is outside the exact allowed Skill path" >&2; exit 3; }
[[ "$CANONICAL_SOURCE" != "$CANONICAL_DEST" ]] ||
  { echo "ERROR: source and destination must differ" >&2; exit 3; }
[[ ! -L "$DEST_ROOT" ]] ||
  { echo "ERROR: destination must not be a symbolic link" >&2; exit 3; }
[[ -f "$SOURCE_ROOT/SKILL.md" && -x "$SOURCE_ROOT/bin/avatarctl" ]] ||
  { echo "ERROR: incomplete source package: $SOURCE_ROOT" >&2; exit 4; }

echo "Source: $CANONICAL_SOURCE"
echo "Destination: $CANONICAL_DEST"
echo "Mode: $([[ "$APPLY" -eq 1 ]] && echo apply || echo dry-run)"
echo "State migration: disabled"
echo "Worker/ComfyUI/Telegram: disabled"
if ((APPLY == 0)); then
  echo "DRY RUN ONLY: no files changed. Re-run with --apply to install."
  exit 0
fi

DEST_PARENT=$(dirname -- "$CANONICAL_DEST")
BACKUP_ROOT="$HOME/.hermes/backups/yinyue-avatar"
STAMP=$(TZ=UTC date +%Y%m%dT%H%M%SZ)
RELEASE_DIR="$BACKUP_ROOT/install-$STAMP"
mkdir -p -- "$DEST_PARENT" "$RELEASE_DIR"
chmod 0700 "$BACKUP_ROOT" "$RELEASE_DIR"
STAGING=$(mktemp -d -- "$DEST_PARENT/.yinyue-avatar.install-stage.XXXXXX")
OLD_PATH="$DEST_PARENT/.yinyue-avatar.pre-install.$STAMP"
SWITCHED=0

cleanup() {
  if [[ -n "${STAGING:-}" && -d "$STAGING" ]]; then
    case "$STAGING" in "$DEST_PARENT"/.yinyue-avatar.install-stage.*) rm -rf -- "$STAGING" ;; esac
  fi
}

rollback() {
  code=$?
  if ((SWITCHED == 1)); then
    if [[ -e "$CANONICAL_DEST" ]]; then
      FAILED_PATH="$DEST_PARENT/.yinyue-avatar.failed-install.$STAMP"
      mv -- "$CANONICAL_DEST" "$FAILED_PATH"
    fi
    if [[ -e "$OLD_PATH" ]]; then
      mv -- "$OLD_PATH" "$CANONICAL_DEST"
    fi
  fi
  cleanup
  echo "ERROR: installation failed; previous Skill restored when a switch occurred" >&2
  exit "$code"
}
trap rollback ERR INT TERM

if [[ -d "$CANONICAL_DEST" ]]; then
  (
    cd "$CANONICAL_DEST"
    find . -type f -print0 | sort -z | xargs -0 sha256sum
  ) > "$RELEASE_DIR/MANIFEST_BEFORE_SHA256.txt"
  tar --acls --xattrs --numeric-owner -C "$DEST_PARENT" -czpf \
    "$RELEASE_DIR/skill-before-install.tar.gz" "$(basename -- "$CANONICAL_DEST")"
  chmod 0600 "$RELEASE_DIR/skill-before-install.tar.gz" \
    "$RELEASE_DIR/MANIFEST_BEFORE_SHA256.txt"
fi

cp -a -- "$SOURCE_ROOT/." "$STAGING/"
if [[ -f "$CANONICAL_DEST/config.local.json" ]]; then
  cp -a -- "$CANONICAL_DEST/config.local.json" "$STAGING/config.local.json"
fi

# Staging-only static and unit validation. No avatarctl command is executed.
find "$STAGING" -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
find "$STAGING" -type f -name '*.json' -print0 |
  xargs -0 -n1 python3 -m json.tool >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$STAGING/tests" -v
PYTHONDONTWRITEBYTECODE=1 python3 - "$STAGING" <<'PY'
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("install_validate", root / "lib/avatarctl.py")
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
config = module.load_config()
module.workflow_registry(config)
module.validate_workflow(config)
PY

(
  cd "$STAGING"
  find . -type f -print0 | sort -z | xargs -0 sha256sum
) > "$RELEASE_DIR/MANIFEST_STAGING_SHA256.txt"
chmod 0600 "$RELEASE_DIR/MANIFEST_STAGING_SHA256.txt"

if [[ -e "$CANONICAL_DEST" ]]; then
  mv -- "$CANONICAL_DEST" "$OLD_PATH"
fi
mv -- "$STAGING" "$CANONICAL_DEST"
STAGING=""
SWITCHED=1

# Test-only failpoint is accepted only under a dedicated /tmp HOME.
if [[ "${YINYUE_AVATAR_INSTALL_FAILPOINT:-}" == after-switch ]]; then
  case "$HOME" in /tmp/*) false ;; *) echo "ERROR: failpoint refused outside /tmp HOME" >&2; exit 5 ;; esac
fi

# Read-only post-switch verification.
find "$CANONICAL_DEST" -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
PYTHONDONTWRITEBYTECODE=1 python3 - "$CANONICAL_DEST" <<'PY'
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
json.load(open(root / "config.json"))
json.load(open(root / "schemas/state.schema.json"))
spec = importlib.util.spec_from_file_location("post_validate", root / "lib/avatarctl.py")
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
config = module.load_config()
module.workflow_registry(config)
module.validate_workflow(config)
PY
(
  cd "$CANONICAL_DEST"
  find . -type f -print0 | sort -z | xargs -0 sha256sum
) > "$RELEASE_DIR/MANIFEST_AFTER_SHA256.txt"
chmod 0600 "$RELEASE_DIR/MANIFEST_AFTER_SHA256.txt"

if [[ -e "$OLD_PATH" ]]; then
  mv -- "$OLD_PATH" "$RELEASE_DIR/previous-skill-directory"
fi
SWITCHED=0
trap - ERR INT TERM
cleanup
echo "Installed safely: $CANONICAL_DEST"
echo "Backup and manifests: $RELEASE_DIR"
echo "State was not migrated; no worker, ComfyUI prompt, or Telegram send ran."
