#!/usr/bin/env bash
set -euo pipefail

: "${GITLAB_TOKEN:?Set GITLAB_TOKEN to a GitLab token with the api scope}"

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

uv sync --all-extras --group package
uv run --group package python packaging/build.py --upload
