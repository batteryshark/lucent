#!/bin/sh
# Deterministic code understanding: source tree -> parallax observation atoms.
# Usage: run.sh <input> <out_dir>
#
# Activates the skill's own uv venv (heavy deps: tree-sitter, jsonschema — kept
# here, never in rekit), puts the parallax-goalpacks repo root on PYTHONPATH so
# `import engine` resolves to the shared parallax-goalpacks/engine/ package, and
# runs the observe.py wrapper. Falls back to `uv run` / system python3 if the venv
# isn't set up.
set -eu
[ $# -eq 2 ] || { echo "usage: run.sh <input> <out_dir>" >&2; exit 2; }
INPUT="$1"; OUT="$2"

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"
# repo root: parallax-goalpacks/  (skills/code-understanding -> ../..)
REPO_ROOT="$(cd "$SKILL_DIR/../.." && pwd)"

# The shared engine lives at the repo root; make `import engine` find it.
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$OUT"

VENV_PY="$SKILL_DIR/.venv/bin/python"
if [ -x "$VENV_PY" ]; then
    exec "$VENV_PY" "$SCRIPTS_DIR/observe.py" "$INPUT" "$OUT"
elif command -v uv >/dev/null 2>&1; then
    # No venv yet but uv is present — run in an ephemeral env with the pinned deps.
    exec uv run --with "tree-sitter==0.25.2" \
                --with "tree-sitter-language-pack==1.12.0" \
                --with "jsonschema>=4.18" \
                python "$SCRIPTS_DIR/observe.py" "$INPUT" "$OUT"
else
    echo "code-understanding: no skill venv (run scripts/setup.sh) and no 'uv' on PATH;" >&2
    echo "  falling back to system python3 — tree-sitter may be missing (regex fallback)." >&2
    exec python3 "$SCRIPTS_DIR/observe.py" "$INPUT" "$OUT"
fi
