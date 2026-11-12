#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
CLAB_PYTHON="${PYTHON:-python3.12}"
if ! command -v "$CLAB_PYTHON" >/dev/null 2>&1; then CLAB_PYTHON=python3; fi
exec "$CLAB_PYTHON" bootstrap.py "$@"
