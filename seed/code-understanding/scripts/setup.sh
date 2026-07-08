#!/bin/sh
# Set up the code-understanding skill's own uv venv with the parallax engine's
# pinned deps. The heavy deps (tree-sitter) live HERE, in the skill's venv, so they
# never leak into rekit. Idempotent: re-running re-syncs.
# Usage: scripts/setup.sh
set -eu

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../.." && pwd)"

command -v uv >/dev/null 2>&1 || {
    echo "code-understanding/setup: 'uv' not found on PATH — install uv first" >&2
    echo "  (https://docs.astral.sh/uv/). It manages this skill's isolated venv." >&2
    exit 1
}

echo "code-understanding/setup: creating venv in $SKILL_DIR/.venv"
uv venv "$SKILL_DIR/.venv"

# Pinned to match parallax/prlx/pyproject.toml [ast] extra + engine deps.
echo "code-understanding/setup: installing pinned engine deps"
VIRTUAL_ENV="$SKILL_DIR/.venv" uv pip install \
    "tree-sitter==0.25.2" \
    "tree-sitter-language-pack==1.12.0" \
    "jsonschema>=4.18"

# Smoke-check: engine imports and tree-sitter loaded (not just regex fallback).
echo "code-understanding/setup: verifying"
PYTHONPATH="$REPO_ROOT" "$SKILL_DIR/.venv/bin/python" - <<'PY'
from engine import rules
mode = rules.ast_mode()
print(f"  engine import OK; observation mode = {mode}")
if mode != "tree-sitter":
    print("  WARNING: tree-sitter did not load; engine will use the regex fallback.")
PY

echo "code-understanding/setup: done. Run: scripts/run.sh <input> <out_dir>"
