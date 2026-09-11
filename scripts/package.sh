#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname -- "$ROOT")"
NAME="$(basename -- "$ROOT")"
OUT="${1:-$PARENT}"
mkdir -p "$OUT"
(
  cd "$PARENT"
  zip -qr "$OUT/${NAME}.zip" "$NAME" -x '*/__pycache__/*' '*.pyc'
  tar --exclude='__pycache__' --exclude='*.pyc' -czf "$OUT/${NAME}.tar.gz" "$NAME"
)
sha256sum "$OUT/${NAME}.zip" "$OUT/${NAME}.tar.gz" > "$OUT/${NAME}.sha256"
echo "$OUT/${NAME}.zip"
echo "$OUT/${NAME}.tar.gz"
echo "$OUT/${NAME}.sha256"
