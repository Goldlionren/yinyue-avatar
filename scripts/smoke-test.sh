#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m py_compile "$ROOT/lib/avatarctl.py" "$ROOT/lib/visual_v030.py"
python3 -m unittest discover -s "$ROOT/tests" -v
"$ROOT/bin/avatarctl" doctor
