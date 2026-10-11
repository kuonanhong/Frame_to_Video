#!/bin/sh
# First run installs Python packages and explicitly downloads SD-Turbo (several GB).
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3.11 "$SCRIPT_DIR/setup_native.py" --model sd-turbo --launch "$@"
