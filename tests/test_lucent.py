"""lucent end-to-end — the cross-domain proof that muster's contract holds.

lucent is built on muster's public seam alone (never imports unmask). A full run over a
small package must record symbols, drain every module to done, and finish completed. The
other tests exercise the pieces that would break if the seam were wrong: coverage over a
mixed good/broken surface, follow-up enqueue, resume (muster's reset wipes the domain
table), and that lucent pulls in no unmask code.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lucent import LucentConfig, resume_lucent, run_lucent


def _pkg(tmp_path):
    d = tmp_path / "pkg"
    (d / "sub").mkdir(parents=True)
    (d / "__init__.py").write_text("")
    (d / "core.py").write_text(
        "import os\n"
        "from pathlib import Path\n\n"
        "def top():\n    return 1\n\n"
        "class Widget:\n"
        "    def method_a(self):\n        return os.getcwd()\n\n"
        "    def method_b(self):\n        return Path('.')\n")
    (d / "sub" / "__init__.py").write_text("")
    (d / "sub" / "util.py").write_text(
        "from os import getcwd as cwd\n\ndef helper():\n    return cwd()\n")
    (d / "broken.py").write_text("def x(:\n")   # syntax error → tracked failure, not a crash
    return d


def _report(result):
    return json.loads(Path(result.report_path).read_text())


def test_run_understands_a_package(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    assert result.status == "completed"
    s = result.summary
    assert s["functions"] >= 2 and s["classes"] == 1 and s["methods"] == 2
    assert s["imports"] >= 3                      # os, Path, cwd(alias)
    core = _report(result)["modules"]["core.py"]
    kinds = {(x["name"], x["kind"]) for x in core}
    assert {("top", "function"), ("Widget", "class"), ("method_a", "method")} <= kinds


def test_coverage_drains_every_module(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    cov = result.coverage
    assert cov["queued"] == 0                                  # nothing left actionable
    assert cov["workItemsTotal"] == cov["done"] + cov["failed"]
    assert cov["failed"] == 1                                  # broken.py, tracked not fatal
    assert cov["done"] >= 4                                    # modules + link-imports follow-ups


def test_resume_reunderstands_without_duplication(tmp_path):
    cfg = LucentConfig(storage_root=str(tmp_path / ".lucent"))
    r1 = run_lucent(str(_pkg(tmp_path)), cfg)
    r2 = resume_lucent(r1.run_dir)                             # muster reset wipes symbols, re-record
    assert r2.status == "completed"
    assert r2.summary["symbols"] == r1.summary["symbols"]      # exactly N, not 2N


def test_lucent_imports_only_muster():
    """The cross-domain proof, checked in a fresh interpreter so a prior unmask import in
    the shared test session can't mask a real dependency: lucent must pull in no unmask."""
    code = ("import lucent, lucent.graph, lucent.ledger, lucent.run, lucent.cli, sys; "
            "bad=[m for m in sys.modules if m == 'unmask' or m.startswith('unmask.')]; "
            "assert not bad, bad")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
