#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${APP_DIR}/venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
APP_ENTRY="${APP_DIR}/sentinel_crt.py"

export SDL_VIDEODRIVER="x11"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

cd "${APP_DIR}"
exec "${PYTHON_BIN}" "${APP_ENTRY}" --fullscreen
