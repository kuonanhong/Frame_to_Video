#!/bin/bash
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
if [ -x "$ROOT/.venv-native/bin/python" ]; then
  exec "$ROOT/.venv-native/bin/python" "$HERE/server.py" "$@"
fi
exec python3 "$HERE/server.py" "$@"
