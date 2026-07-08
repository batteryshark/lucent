#!/usr/bin/env python3
"""Wrapper that drives the vendored parallax engine and writes observation atoms.

Usage: observe.py <input> <out_dir>

Runs ``engine.observe_report(<input>)`` — the deterministic source -> taxonomy-atom
path (tree-sitter extraction, degrading to regex without it) — and writes
``<out_dir>/observations.json``: the observation atoms plus the full engine
scan-report. This is the artifact that re-enters the ledger for the brain to reason
over.

``import engine`` resolves to the shared ``parallax-goalpacks/engine/`` package;
``run.sh`` puts the repo root on ``PYTHONPATH``. As a fallback (running this script
directly), we add the repo root ourselves so ``import engine`` still resolves.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def _ensure_engine_importable() -> None:
    """Make ``import engine`` resolve to the shared repo-root package.

    Layout: parallax-goalpacks/skills/code-understanding/scripts/observe.py
    Repo root is three parents up from this file's dir.
    """
    try:
        import engine  # noqa: F401
        return
    except ImportError:
        pass
    repo_root = Path(__file__).resolve().parents[3]
    if (repo_root / "engine" / "__init__.py").is_file():
        sys.path.insert(0, str(repo_root))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: observe.py <input> <out_dir>", file=sys.stderr)
        return 2

    target = argv[1]
    out_dir = Path(argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    _ensure_engine_importable()
    from engine import engine as eng, rules

    report = eng.observe_report(target)
    observations = report.get("observations", []) or []

    by_atom = Counter(o.get("atom") for o in observations if o.get("atom"))
    payload = {
        "target": target,
        "scanner": report.get("scan", {}).get("scanner", "prlx"),
        "scannerVersion": report.get("scan", {}).get("scannerVersion"),
        # tree-sitter vs regex fallback — surfaced explicitly so the ledger records
        # the extraction fidelity, not just the atoms.
        "astMode": rules.ast_mode(),
        "counts": {
            "observations": len(observations),
            "byAtom": dict(sorted(by_atom.items())),
        },
        "observations": observations,
        # The full engine scan-report (notes, dataflow/reachability, summary) for
        # callers that want more than the atom list.
        "report": report,
    }

    out_file = out_dir / "observations.json"
    out_file.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")

    print(
        f"code-understanding: {len(observations)} observation(s) "
        f"[{payload['astMode']}] -> {out_file}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
