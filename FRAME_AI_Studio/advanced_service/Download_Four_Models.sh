#!/usr/bin/env bash
# FRAME v5.1: run sequentially to limit network and disk pressure.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
MODE="${1:---plan}"
case "$MODE" in
  --plan|--download|--verify) ;;
  *) printf '%s\n' 'Usage: bash Download_Four_Models.sh [--plan|--download|--verify]'; exit 2 ;;
esac
if [[ -n "${FRAME_PYTHON:-}" ]]; then
  PYTHON_BIN="$FRAME_PYTHON"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
else
  PYTHON_BIN="python3"
fi
if [[ "$MODE" == "--download" ]]; then
  for EXPERT_ID in liveportrait flux-klein ltx-video cogvideox; do
    "$PYTHON_BIN" install.py "$EXPERT_ID" --plan
  done
  "$PYTHON_BIN" - <<'PY'
import json, shutil
from registry import expert_dir
from download_support import validate_plan, safe_path
remaining = 0
for expert in ('liveportrait', 'flux-klein', 'ltx-video', 'cogvideox'):
    home = expert_dir(expert)
    plan = validate_plan(expert, json.loads((home/'download-plan.json').read_text()))
    for model in plan['models']:
        for item in model['files']:
            path = safe_path(home, 'models/'+model['name']+'/'+item['path'])
            if not path.is_file() or path.stat().st_size != item['bytes']:
                remaining += item['bytes']
free = shutil.disk_usage(expert_dir('liveportrait')).free
print(f'All four models: estimated remaining {remaining/1e9:.3f} GB; free {free/1e9:.3f} GB.', flush=True)
if remaining + 1024**3 > free:
    raise SystemExit('Not enough free space for all four. Set FRAME_EXPERT_HOME to a larger drive, or download individual models.')
PY
  MODE="--weights-only"
fi
for EXPERT_ID in liveportrait flux-klein ltx-video cogvideox; do
  "$PYTHON_BIN" install.py "$EXPERT_ID" "$MODE"
done
