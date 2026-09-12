#!/usr/bin/env bash
set -euo pipefail

apply=0
target=""
source_file=""
remote_name=""

usage() {
  printf '%s\n' \
    'Usage: scripts/deploy-workflow.sh --target comfy_3060|comfy_4080s|comfy_5090 --source ABSOLUTE_JSON [--name FILE.json] [--apply]' \
    'Default is dry-run. --apply creates missing YinyueAvatar directories and refuses to overwrite an existing remote file.'
}

while (($#)); do
  case "$1" in
    --apply) apply=1; shift ;;
    --target) target=${2:?missing target}; shift 2 ;;
    --source) source_file=${2:?missing source}; shift 2 ;;
    --name) remote_name=${2:?missing name}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[[ "$source_file" = /* && -f "$source_file" ]] || {
  printf 'ERROR: --source must be an existing absolute file\n' >&2
  exit 3
}
python3 -m json.tool "$source_file" >/dev/null
remote_name=${remote_name:-$(basename -- "$source_file")}
[[ "$remote_name" =~ ^[A-Za-z0-9._-]+\.json$ ]] || {
  printf 'ERROR: unsafe remote filename\n' >&2
  exit 3
}

case "$target" in
  comfy_5090)
    key=/home/james/.ssh/comfy_5090
    remote=Admin@192.168.1.200
    remote_root='F:\AI\YinyueAvatar'
    scp_root='/F:/AI/YinyueAvatar'
    ;;
  comfy_4080s)
    key=/home/james/.ssh/comfy_4080s
    remote=Admin@192.168.1.241
    remote_root='F:\AI\YinyueAvatar'
    scp_root='/F:/AI/YinyueAvatar'
    ;;
  comfy_3060)
    key=/home/james/.ssh/comfy_3060
    remote=ryjdl@192.168.100.211
    remote_root='D:\AI\YinyueAvatar'
    scp_root='/D:/AI/YinyueAvatar'
    ;;
  *) printf 'ERROR: unsupported target: %s\n' "$target" >&2; exit 3 ;;
esac
windows_path="$remote_root\\workflows\\$remote_name"
scp_path="$scp_root/workflows/$remote_name"

printf 'Target: %s\nSource: %s\nRemote: %s\n' "$target" "$source_file" "$windows_path"
if ((apply == 0)); then
  printf 'DRY RUN ONLY: no remote files changed.\n'
  exit 0
fi

if ssh -T -i "$key" -o BatchMode=yes -o LogLevel=ERROR "$remote" \
  cmd.exe /d /q /c dir /b "$windows_path" >/dev/null 2>&1; then
  printf 'ERROR: remote workflow already exists; refusing overwrite: %s\n' "$windows_path" >&2
  exit 4
fi
for directory in "$remote_root" "$remote_root\\workflows" \
  "$remote_root\\temp" "$remote_root\\output"; do
  ssh -T -i "$key" -o BatchMode=yes -o LogLevel=ERROR "$remote" \
    cmd.exe /d /q /c if not exist "$directory\\NUL" mkdir "$directory"
done
scp -p -i "$key" -o BatchMode=yes -o LogLevel=ERROR \
  "$source_file" "$remote:$scp_path"
printf 'Deployed without overwrite: %s\n' "$windows_path"
