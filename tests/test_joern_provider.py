from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lucent import LucentConfig, resume_lucent, run_lucent
from lucent.deep.joern import JoernRequest, context_for_module


_IMAGE = "ghcr.io/joernio/joern@sha256:" + "a" * 64


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class FakeJoernRunner:
    """External-runner contract fake: writes the same artifacts Lucent consumes."""

    def __init__(self, *, bad_manifest: bool = False):
        self.requests: list[JoernRequest] = []
        self.staged_files: list[set[str]] = []
        self.bad_manifest = bad_manifest

    def run(self, request: JoernRequest) -> dict:
        self.requests.append(request)
        files = []
        for path in sorted(request.target.rglob("*")):
            if path.is_file():
                data = path.read_bytes()
                files.append({"path": path.relative_to(request.target).as_posix(),
                              "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.staged_files.append({item["path"] for item in files})
        manifest = "0" * 64 if self.bad_manifest else _digest({"files": files})
        request.outdir.mkdir(parents=True, exist_ok=True)
        (request.outdir / "cpg.bin").write_bytes(b"fake-cpg")

        if request.mode == "behavior-flow":
            profile = json.loads(request.profile.read_text())
            nodes = [
                {"id": "n-source", "label": "CALL", "name": "requests.get",
                 "code": "requests.get(url)", "parentFile": "app.py",
                 "parentMethod": "run", "lineNumber": 5, "typeFullName": "requests.Response"},
                {"id": "n-sink", "label": "CALL", "name": "subprocess.run",
                 "code": "subprocess.run(cmd)", "parentFile": "app.py",
                 "parentMethod": "run", "lineNumber": 6, "typeFullName": "CompletedProcess"},
            ]
            edges = [{"src": "n-source", "dst": "n-sink", "label": "REACHING_DEF"}]
            paths = [{"id": "p-flow", "nodes": ["n-source", "n-sink"],
                      "sinkContext": "n-sink", "relation": "explicit-reaching-def"},
                     {"id": "p-selected", "nodes": ["n-source"],
                      "sinkContext": None, "relation": "slice-selected-by-sink"}]
            findings = [{"id": "f-flow", "kind": "indexed-code-flow",
                         "sourceKind": "source-001", "sinkKind": "sink-001",
                         "path": "p-flow", "confidence": "structural"},
                        {"id": "f-selected", "kind": "indexed-code-flow",
                         "sourceKind": "source-001", "sinkKind": "sink-002",
                         "path": "p-selected", "confidence": "structural"}]
            profile_id, profile_digest = profile["id"], _digest(profile)
        else:
            assert request.reuse_cpg and request.reuse_cpg.is_file()
            nodes = [{"id": "n-usage", "label": "CALL_USAGE", "name": "subprocess.run",
                      "code": "subprocess.run", "parentFile": "app.py",
                      "parentMethod": "run", "lineNumber": 6,
                      "typeFullName": "<unresolved>"}]
            edges, paths, findings = [], [], []
            profile_id = profile_digest = None

        evidence = {
            "schemaVersion": 1,
            "producer": {"tool": "joern-slice", "joernVersion": "test",
                         "revision": "fixture", "image": _IMAGE, "runtime": "fake"},
            "target": {"path": str(request.target), "files": len(files),
                       "bytes": sum(item["bytes"] for item in files), "excluded": [],
                       "manifestSha256": manifest},
            "analysis": {"mode": request.mode, "language": request.frontend,
                         "sliceDepth": request.slice_depth, "profile": profile_id,
                         "profileSha256": profile_digest, "proofDepth": "interprocedural-cpg",
                         "limits": {"timeoutSeconds": request.timeout,
                                    "maxInputBytes": 536870912, "maxInputFiles": 10000}},
            "coverage": {"inputFiles": len(files),
                         "inputBytes": sum(item["bytes"] for item in files),
                         "filesObservedInSlice": ["app.py"], "excluded": [],
                         "unresolved": ([{"file": "app.py", "line": 6,
                                          "code": "subprocess.run",
                                          "typeFullName": "<unresolved>"}]
                                        if request.mode == "usages" else []),
                         "truncated": False,
                         "limitations": ["one frontend; no cross-language flow"]},
            "graph": {"graphType": "DataFlowSlice" if request.mode == "behavior-flow"
                      else "ProgramUsageSlice", "nodes": nodes, "edges": edges,
                      "paths": paths, "findings": findings},
            "metrics": {"parseSeconds": 0.0, "sliceSeconds": 0.0, "totalSeconds": 0.0,
                        "cpgBytes": 8, "rawNodes": len(nodes), "rawEdges": len(edges),
                        "normalizedNodes": len(nodes), "normalizedEdges": len(edges),
                        "findings": len(findings)},
        }
        (request.outdir / "evidence.json").write_text(json.dumps(evidence))
        return evidence


def test_optional_joern_uses_index_selected_candidates_and_one_cpg(tmp_path):
    target = tmp_path / "pkg"
    target.mkdir()
    (target / "app.py").write_text(
        "import requests, subprocess\nfrom helper import adapt\n\n"
        "def run(url, cmd):\n    data = requests.get(url)\n"
        "    return subprocess.run(adapt(cmd))\n")
    (target / "helper.py").write_text("def adapt(value):\n    return value\n")
    (target / "unrelated.py").write_text("def add(a, b):\n    return a + b\n")
    runner = FakeJoernRunner()

    result = run_lucent(
        str(target), LucentConfig(storage_root=str(tmp_path / ".lucent"), joern=True),
        joern_runner=runner)
    report = json.loads(Path(result.report_paths["json"]).read_text())

    assert result.status == "completed"
    assert [request.mode for request in runner.requests] == ["behavior-flow", "usages"]
    staged = runner.staged_files[0]
    assert "app.py" in staged
    assert "unrelated.py" not in staged
    assert runner.requests[1].reuse_cpg == runner.requests[0].outdir / "cpg.bin"
    deep = report["deepAnalysis"]
    assert deep["provider"] == "joern"
    behavior = next(run for run in deep["runs"] if run["mode"] == "behavior-flow")
    relations = {path["relation"] for path in behavior["evidence"]["graph"]["paths"]}
    assert relations == {"explicit-reaching-def", "slice-selected-by-sink"}
    assert behavior["evidence"]["analysis"]["profileSha256"]
    usage = next(run for run in deep["runs"] if run["mode"] == "usages")
    assert usage["evidence"]["coverage"]["unresolved"][0]["typeFullName"] == "<unresolved>"
    context = context_for_module(deep["runs"], "app.py")
    assert {item.get("relation") for item in context if item["mode"] == "behavior-flow"} == relations
    assert report["summary"]["deepSliceCount"] == 2
    assert "Focused code-property-graph slices" in Path(result.report_paths["markdown"]).read_text()
    assert "id='deep-analysis'" in Path(result.report_paths["html"]).read_text()


def test_joern_skips_when_index_has_no_focused_candidate(tmp_path):
    target = tmp_path / "quiet"
    target.mkdir()
    (target / "math.py").write_text("def add(a, b):\n    return a + b\n")
    runner = FakeJoernRunner()

    result = run_lucent(
        str(target), LucentConfig(storage_root=str(tmp_path / ".lucent"), joern=True),
        joern_runner=runner)
    report = json.loads(Path(result.report_paths["json"]).read_text())

    assert result.status == "completed"
    assert runner.requests == []
    assert report["summary"]["fileCount"] == 1
    assert report["deepAnalysis"]["status"] == "skipped"
    assert "no Joern-supported behavior" in report["deepAnalysis"]["runs"][0]["error"]


def test_bad_joern_provenance_degrades_without_losing_baseline(tmp_path):
    target = tmp_path / "bad-provenance"
    target.mkdir()
    (target / "app.py").write_text(
        "import subprocess\ndef run(cmd):\n    return subprocess.run(cmd)\n")

    result = run_lucent(
        str(target), LucentConfig(storage_root=str(tmp_path / ".lucent"), joern=True),
        joern_runner=FakeJoernRunner(bad_manifest=True))
    report = json.loads(Path(result.report_paths["json"]).read_text())

    assert result.status == "completed"
    assert result.summary["atomCount"] > 0 and result.summary["findingCount"] > 0
    assert report["deepAnalysis"]["status"] == "unavailable"
    behavior = next(run for run in report["deepAnalysis"]["runs"]
                    if run["mode"] == "behavior-flow")
    assert behavior["status"] == "failed"
    assert "manifest does not match" in behavior["error"]


def test_resume_reuses_only_matching_language_cpg_provenance(tmp_path):
    target = tmp_path / "cache"
    target.mkdir()
    (target / "app.py").write_text(
        "import subprocess\ndef run(cmd):\n    return subprocess.run(cmd)\n")
    config = LucentConfig(storage_root=str(tmp_path / ".lucent"), joern=True)
    first = run_lucent(str(target), config, joern_runner=FakeJoernRunner())

    matching = FakeJoernRunner()
    resume_lucent(first.run_dir, joern_runner=matching)
    assert matching.requests[0].mode == "behavior-flow"
    assert matching.requests[0].reuse_cpg is not None

    # A target change invalidates the cached manifest before the external runner is called.
    (target / "app.py").write_text(
        "import subprocess\ndef run(cmd):\n    return subprocess.run([cmd, '--verbose'])\n")
    changed = FakeJoernRunner()
    resume_lucent(first.run_dir, joern_runner=changed)
    assert changed.requests[0].mode == "behavior-flow"
    assert changed.requests[0].reuse_cpg is None
