#!/usr/bin/env bash
set -euo pipefail
exec uv run --no-project "$(dirname "$0")/forge.py" sync "$@"
