#!/usr/bin/env bash
set -euo pipefail

APPLY=0
STAGING_ROOT=""
while (($#)); do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --root) STAGING_ROOT=${2:?missing root}; shift 2 ;;
    -h|--help) echo "Usage: cleanup-staging.sh --root PATH [--apply]"; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$STAGING_ROOT" && "$STAGING_ROOT" = /* ]] ||
  { echo "ERROR: --root must be a non-empty absolute path" >&2; exit 3; }
CANONICAL_ROOT=$(realpath -m -- "$STAGING_ROOT")
case "$CANONICAL_ROOT" in
  /mnt/data_nvme/tmp/yinyue-avatar-staging-*|/tmp/yinyue-avatar-staging-*) ;;
  *) echo "ERROR: cleanup root is outside the staging namespace" >&2; exit 3 ;;
esac
[[ ! -L "$STAGING_ROOT" ]] ||
  { echo "ERROR: cleanup root must not be a symbolic link" >&2; exit 3; }
MARKER="$CANONICAL_ROOT/.yinyue-avatar-staging.json"
[[ -f "$MARKER" && ! -L "$MARKER" ]] ||
  { echo "ERROR: valid staging marker missing" >&2; exit 4; }
[[ "$(jq -r '.kind' "$MARKER")" == yinyue-avatar-isolated-staging ]] ||
  { echo "ERROR: invalid staging marker kind" >&2; exit 4; }
[[ "$(jq -r '.root' "$MARKER")" == "$CANONICAL_ROOT" ]] ||
  { echo "ERROR: staging marker root mismatch" >&2; exit 4; }
if find "$CANONICAL_ROOT" -type l -print -quit | grep -q .; then
  echo "ERROR: refusing cleanup because staging contains symbolic links" >&2
  exit 5
fi

echo "Validated staging root: $CANONICAL_ROOT"
if ((APPLY == 0)); then
  echo "DRY RUN ONLY: would remove exactly this staging root."
  exit 0
fi
rm -rf -- "$CANONICAL_ROOT"
[[ ! -e "$CANONICAL_ROOT" ]]
echo "Removed isolated staging root: $CANONICAL_ROOT"
