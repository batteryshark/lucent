"""lucent end-to-end — observe → link → compose → render, with guaranteed coverage.

A full run over a small mixed-language package must observe behaviour atoms, resolve the
Python reference graph, compose findings across the four lenses, drain every file to a
terminal state, and render all three report formats. The other tests exercise the pieces
that would break if a seam were wrong: coverage over a good/broken surface, the reference
graph, multi-language observation, resume (muster's reset wipes the domain tables), and that
lucent pulls in no unmask code.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lucent import LucentConfig, resume_lucent, run_lucent
from lucent.observe import observe_source


def _pkg(tmp_path):
    d = tmp_path / "pkg"
    (d / "sub").mkdir(parents=True)
    (d / "__init__.py").write_text("")
    (d / "core.py").write_text(
        "import subprocess, os\n"
        "import requests\n"
        "from .sub.util import helper\n\n"          # internal edge: core -> sub/util.py
        "def top():\n    return helper()\n\n"
        "class Widget:\n"
        "    def run(self, cmd):\n"
        "        subprocess.run(['ls'])\n"           # EXEC.PROC
        "        requests.get('https://example.com')\n"   # NETW.HTTP
        "        os.remove('/tmp/x')\n")             # FSYS.DELETE
    (d / "sub" / "__init__.py").write_text("")
    (d / "sub" / "util.py").write_text(
        "import pickle\n\n"
        "def helper(data=b''):\n"
        "    obj = pickle.loads(data)\n"             # LOAD.DESER
        "    return eval('1+1')\n")                  # LOAD.EVAL
    # A passive-looking module that nonetheless runs a process -> surprising role mismatch.
    (d / "utils.py").write_text(
        "import subprocess\n\n"
        "def sh(c):\n    return subprocess.run(c)\n")
    # A non-Python file, observed for behaviour (EXEC.SHELL via child_process).
    (d / "app.js").write_text(
        "const cp = require('child_process');\n"
        "function go(x){ cp.execSync('ls ' + x); }\n")
    (d / "broken.py").write_text("def x(:\n")        # syntax error -> tracked failure
    return d


def _report(result):
    return json.loads(Path(result.report_paths["json"]).read_text())


def test_run_produces_understanding(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    assert result.status == "completed"
    s = result.summary
    assert s["moduleCount"] >= 4 and s["symbolCount"] > 0
    assert s["atomCount"] >= 4                       # exec/http/deser/eval/delete, at least
    assert s["findingCount"] >= 3
    assert result.synopsis                            # a non-empty plain-language paragraph


def test_observes_capability_atoms(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    atoms = {a for o in _report(result)["observations"] for a in [o["atom"]]}
    caps = set(result.summary["capabilities"])       # atom -> count, so keys are the atoms seen
    assert {"EXEC.PROC", "NETW.HTTP", "LOAD.DESER", "LOAD.EVAL", "FSYS.DELETE"} <= caps
    assert "EXEC.SHELL" in caps                        # from app.js (multi-language, regex fallback)


def test_coverage_drains_every_file(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    cov = result.coverage
    assert cov["queued"] == 0
    assert cov["workItemsTotal"] == cov["done"] + cov["failed"]
    assert cov["failed"] == 1                          # broken.py, tracked not fatal


def test_reference_graph_resolves_internal_edges(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    deps = _report(result)["dependencies"]
    assert "sub/util.py" in deps["dependsOn"].get("core.py", [])
    assert "core.py" in deps["dependents"].get("sub/util.py", [])


def test_lenses_compose_findings(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    findings = _report(result)["findings"]
    by_lens = {f["lens"] for f in findings}
    assert "does" in by_lens and "brittle" in by_lens
    comps = {f.get("composition") for f in findings}
    assert "unparseable" in comps                      # broken.py surfaced as brittle
    assert "opaque-loading" in comps                   # eval / pickle.loads
    # understanding, not security: only brittle findings carry a fragility rating; the
    # descriptive lenses (does/decides/surprising) leave it null. confidence is universal.
    assert all("confidence" in f for f in findings)
    assert all(f.get("fragility") is None for f in findings if f["lens"] in ("does", "decides", "surprising"))
    assert all(f.get("fragility") in ("low", "medium", "high") for f in findings if f["lens"] == "brittle")


def test_surprising_role_mismatch(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    surprising = [f for f in _report(result)["findings"] if f["lens"] == "surprising"]
    assert any(f.get("module") == "utils.py" and f.get("composition") == "role-capability-mismatch"
               for f in surprising)


def test_purpose_from_docstrings(tmp_path):
    """The overview surfaces the package's stated purpose (its own docstring), and each component
    gets a role line from its docstring — deterministic, no model needed."""
    d = tmp_path / "pp"
    (d / "sub").mkdir(parents=True)
    (d / "__init__.py").write_text('"""Widget toolkit — assemble and paint widgets on screen."""\n')
    (d / "core.py").write_text('"""Core widget assembly logic."""\ndef go():\n    return 1\n')
    (d / "sub" / "__init__.py").write_text('"""The sub package: painting helpers."""\n')
    (d / "sub" / "util.py").write_text("def h():\n    return 2\n")
    result = run_lucent(str(d), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    rep = _report(result)
    assert "Widget toolkit" in (rep["overview"].get("purpose") or "")
    roles = {c["name"]: c.get("role") for c in rep["composition"]["components"]}
    assert roles.get("sub") and "painting helpers" in roles["sub"]
    html = Path(result.report_paths["html"]).read_text()
    assert "in its own words" in html.lower()                 # the purpose block is rendered


def test_overview_and_composition(tmp_path):
    """The report opens with an overall 'what is this' overview and a compositional analysis
    (components + how they depend on one another), and uses fragility, not severity."""
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    rep = _report(result)
    assert rep["overview"]["kind"] and rep["overview"]["text"]     # inferred nature + prose
    names = {c["name"] for c in rep["composition"]["components"]}
    assert {"(root)", "sub"} <= names                              # top-level components
    root = next(c for c in rep["composition"]["components"] if c["name"] == "(root)")
    assert "sub" in root["dependsOn"]                              # core.py imports sub/util.py
    html = Path(result.report_paths["html"]).read_text()
    assert "id='overview'" in html and "id='composition'" in html
    assert "class='chip frag-" in html                            # brittle carries fragility
    assert "class='chip sev-" not in html                         # no security-style severity chip


def test_reachability_finds_dead_and_unreachable(tmp_path):
    """The reachability pass surfaces code that doesn't run (unreachable, constant-guarded, dead
    private defs → surprising) and code reached only in deeply-nested cases (→ brittle)."""
    d = tmp_path / "rp"
    d.mkdir()
    (d / "__init__.py").write_text("")
    (d / "m.py").write_text(
        "def f(x):\n    return x\n    print('never')\n\n"                    # unreachable
        "def _dead():\n    return 1\n\n"                                      # dead private def
        "def g(a, b, c, d, e):\n"
        "    if a:\n        for i in b:\n            while c:\n"
        "                with d:\n                    if e:\n"
        "                        return i\n"                                  # nesting depth 5
        "    if False:\n        print('x')\n")                               # constant-guarded
    result = run_lucent(str(d), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    findings = _report(result)["findings"]
    comps = {f.get("composition") for f in findings}
    assert {"unreachable-code", "constant-guarded", "dead-definition", "deep-nesting"} <= comps
    deep = next(f for f in findings if f["composition"] == "deep-nesting")
    assert deep["lens"] == "brittle" and deep["fragility"] in ("low", "medium")
    dead = next(f for f in findings if f["composition"] == "dead-definition")
    assert dead["lens"] == "surprising" and dead["fragility"] is None


def test_all_report_formats_written(tmp_path):
    result = run_lucent(str(_pkg(tmp_path)), LucentConfig(storage_root=str(tmp_path / ".lucent")))
    for fmt in ("json", "markdown", "html"):
        p = Path(result.report_paths[fmt])
        assert p.is_file() and p.stat().st_size > 0
    html = Path(result.report_paths["html"]).read_text()
    assert html.startswith("<!doctype html>") and "</html>" in html
    assert "http://" not in html and "https://cdn" not in html.lower()   # self-contained


def test_resume_reobserves_without_duplication(tmp_path):
    cfg = LucentConfig(storage_root=str(tmp_path / ".lucent"))
    r1 = run_lucent(str(_pkg(tmp_path)), cfg)
    r2 = resume_lucent(r1.run_dir)                      # muster reset wipes observations/findings
    assert r2.status == "completed"
    assert r2.summary["atomCount"] == r1.summary["atomCount"]
    assert r2.summary["symbolCount"] == r1.summary["symbolCount"]
    assert r2.summary["findingCount"] == r1.summary["findingCount"]


def test_python_idiom_supplement_unit():
    """lucent's supplement catches common stdlib idioms the parallax pack misses, while the
    receiver gate keeps a local variable from being mistaken for a library."""
    src = (
        "import os, hashlib, threading, time\n"
        "from pathlib import Path\n"
        "def work(p):\n"
        "    p.write_text('x')\n"                  # FSYS.WRITE (pathlib, local receiver)
        "    Path('/e').read_text()\n"              # FSYS.READ (pathlib, call receiver)
        "    os.environ['API_TOKEN']\n"            # ENVI.VAR (subscript)
        "    hashlib.sha256(b'')\n"                 # CRPT.HASH
        "    threading.Thread(target=work)\n"       # RSRC.THREAD
        "    time.sleep(1)\n"                        # TIME.SLEEP
        "    junk = []\n    junk.append(1)\n")       # local list — must NOT be an atom
    atoms = {o.atom for o in observe_source("w.py", src, "python")}
    assert {"FSYS.WRITE", "FSYS.READ", "ENVI.VAR", "CRPT.HASH", "RSRC.THREAD",
            "TIME.SLEEP"} <= atoms
    assert not any(o.evidence == "junk.append" for o in observe_source("w.py", src, "python"))


def test_multilanguage_observation_unit():
    """The observer classifies non-Python callees too (regex fallback path here)."""
    js = "const cp = require('child_process');\nfunction f(){ cp.execSync('id'); }\n"
    atoms = {o.atom for o in observe_source("a.js", js, "javascript")}
    assert "EXEC.SHELL" in atoms
    # Python alias resolution: `from subprocess import run as r; r()` -> subprocess.run
    py = "from subprocess import run as r\ndef g():\n    r(['ls'])\n"
    assert "EXEC.PROC" in {o.atom for o in observe_source("b.py", py, "python")}


def test_review_overlay_deepens_findings(tmp_path):
    """With a model injected, the agentic overlay reviews every finding and the review lands in
    the ledger, the assessment, and the rendered report. Uses an in-process TestModel — no
    network."""
    import pytest
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.models.test import TestModel

    cfg = LucentConfig(storage_root=str(tmp_path / ".lucent"), review=True)
    result = run_lucent(str(_pkg(tmp_path)), cfg, review_model=TestModel())
    assert result.status == "completed"
    assert result.summary["reviewedCount"] == result.summary["findingCount"] > 0
    rep = _report(result)
    assert rep["review"] and rep["review"]["reviewedCount"] == result.summary["reviewedCount"]
    assert all("review" in f for f in rep["findings"])          # each finding annotated
    html = Path(result.report_paths["html"]).read_text()
    assert "Agentic review" in html and "class='rev-badge" in html


def test_goal_nudges_review_and_is_surfaced(tmp_path):
    """A goal is threaded to the reviewer, recorded on the overlay, and shown in the report."""
    import pytest
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.models.test import TestModel

    goal = "how is the reference graph built?"
    cfg = LucentConfig(storage_root=str(tmp_path / ".lucent"), review=True, goal=goal)
    result = run_lucent(str(_pkg(tmp_path)), cfg, review_model=TestModel())
    rep = _report(result)
    assert rep["goal"] == goal
    assert rep["review"]["goal"] == goal
    assert "relevant" in rep["review"]                            # relevance collection wired
    html = Path(result.report_paths["html"]).read_text()
    assert "class='goal'" in html and "reference graph" in html


def test_goal_shown_without_a_model(tmp_path):
    """The goal is recorded and shown even with no review — it just can't nudge without a model."""
    cfg = LucentConfig(storage_root=str(tmp_path / ".lucent"), goal="focus on network egress")
    result = run_lucent(str(_pkg(tmp_path)), cfg)
    rep = _report(result)
    assert rep["goal"] == "focus on network egress" and rep["review"] is None


def test_review_degrades_without_a_model(tmp_path, monkeypatch):
    """review=True but no model configured must not fail the run — it skips the overlay and the
    deterministic report is unchanged."""
    for var in ("LUCENT_REVIEW_MODEL", "LUCENT_REVIEW_PROVIDER", "LUCENT_REVIEW_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    cfg = LucentConfig(storage_root=str(tmp_path / ".lucent"), review=True)
    result = run_lucent(str(_pkg(tmp_path)), cfg)                 # no review_model injected
    assert result.status == "completed"
    assert result.summary["reviewedCount"] == 0
    assert result.summary["findingCount"] > 0                    # findings still produced


def test_lucent_imports_only_muster():
    """Checked in a fresh interpreter so a prior unmask import can't mask a real dependency:
    lucent must pull in no unmask."""
    code = ("import lucent, lucent.graph, lucent.observe, lucent.lens, lucent.assess, "
            "lucent.report, lucent.structure, lucent.signatures, sys; "
            "bad=[m for m in sys.modules if m == 'unmask' or m.startswith('unmask.')]; "
            "assert not bad, bad")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
