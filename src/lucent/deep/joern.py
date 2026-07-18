"""Index-first adapter for Rekit's bounded Joern slicer.

Lucent first inventories and understands the broad source surface. This provider then chooses
a small set of files from that index, stages one language at a time, and asks the proven Rekit
runner for two views over one CPG: a declarative behavior-flow slice and a usage slice. The
runner accepts no Scala or caller-authored Joern program.

Rekit owns the hardened container, immutable image, resource enforcement, CPG construction,
and stable graph normalization. This adapter owns Lucent-specific candidate selection,
provenance validation, CPG reuse coordination, graceful degradation, and projection into the
understanding report and reviewer context.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


_FRONTENDS = {
    "python": "pythonsrc",
    "javascript": "jssrc",
    "typescript": "jssrc",
    "tsx": "jssrc",
    "c": "c",
    "cpp": "c",
    "csharp": "csharpsrc",
    "go": "golang",
    "java": "javasrc",
    "kotlin": "kotlin",
    "php": "php",
    "ruby": "rubysrc",
    "rust": "rust",
    "swift": "swiftsrc",
}
_INPUT_ATOMS = ("FSYS.READ", "NETW.", "ENVI.", "CRED.STORE", "LOAD.DESER")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IMAGE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


class JoernProviderError(RuntimeError):
    """The optional provider could not produce trustworthy evidence."""


@dataclass(frozen=True)
class JoernRequest:
    target: Path
    outdir: Path
    frontend: str
    mode: str
    timeout: int
    slice_depth: int
    profile: Path | None = None
    reuse_cpg: Path | None = None


class JoernRunner(Protocol):
    """Narrow external-runner seam used by production and fake integration tests."""

    def run(self, request: JoernRequest) -> dict: ...


class RekitJoernRunner:
    """Invoke only Rekit's declarative ``joern-slice`` interface, never a shell or script.

    The fixed command prefix is intentionally not exposed through Lucent's CLI.
    """

    def run(self, request: JoernRequest) -> dict:
        argv = ["rekit", "run", "joern-slice", str(request.target), str(request.outdir),
                "--language", request.frontend, "--mode", request.mode,
                "--timeout", str(request.timeout), "--format", "json"]
        if request.mode in ("behavior-flow", "data-flow"):
            argv.extend(["--slice-depth", str(request.slice_depth)])
        if request.profile is not None:
            argv.extend(["--profile", str(request.profile)])
        if request.reuse_cpg is not None:
            argv.extend(["--reuse-cpg", str(request.reuse_cpg)])
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, check=False,
                                  timeout=request.timeout + 30)
        except FileNotFoundError as exc:
            raise JoernProviderError(
                "Rekit is not installed or is not on PATH; install its joern-slice skill to "
                "enable optional deep understanding") from exc
        except subprocess.TimeoutExpired as exc:
            raise JoernProviderError(
                f"Joern runner exceeded its {request.timeout}-second budget") from exc
        except OSError as exc:
            raise JoernProviderError(f"could not start the Joern runner: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "unknown runner error").strip()[-3000:]
            raise JoernProviderError(f"Joern runner failed: {detail}")
        evidence_path = request.outdir / "evidence.json"
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JoernProviderError(f"Joern runner produced no valid evidence.json: {exc}") from exc
        return evidence


@dataclass(frozen=True)
class _Group:
    language: str
    frontend: str
    candidates: tuple[str, ...]
    excluded: tuple[dict, ...]
    score: tuple[tuple[str, int], ...]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _goal_terms(goal: str | None) -> set[str]:
    return {term.lower() for term in re.findall(r"[A-Za-z0-9_]+", goal or "")
            if len(term) >= 3}


def _candidate_groups(*, observations: list[dict], findings: list[dict],
                      module_languages: dict[str, str], file_map: dict[str, str],
                      symbols: dict[str, list[dict]], deps: dict, goal: str | None,
                      max_files: int, max_bytes: int) -> list[_Group]:
    """Choose focused files from Lucent's completed index, never from a fresh repo walk."""
    scores: dict[str, int] = {}
    indexed_text: dict[str, list[str]] = {}
    for observation in observations:
        module = observation.get("module")
        if module in file_map and module_languages.get(module) in _FRONTENDS:
            scores[module] = scores.get(module, 0) + 20
            indexed_text.setdefault(module, []).extend([
                str(observation.get("atom") or ""), str(observation.get("evidence") or "")])
    for finding in findings:
        module = finding.get("module")
        if module in scores:
            scores[module] += 3
        if module in file_map:
            indexed_text.setdefault(module, []).extend([
                str(finding.get("title") or ""), str(finding.get("claim") or "")])

    terms = _goal_terms(goal)
    if terms:
        for module, language in module_languages.items():
            if language not in _FRONTENDS or module not in file_map:
                continue
            searchable = [module, *indexed_text.get(module, []),
                          *(str(s.get("name") or "") for s in symbols.get(module, []))]
            hits = sum(term in " ".join(searchable).lower() for term in terms)
            if hits:
                scores[module] = scores.get(module, 0) + hits * 12

    # Add one structural hop around strong seeds. This is enough context for common call chains
    # without turning the optional provider into a repository-wide CPG build.
    neighbors: dict[str, set[str]] = {}
    for src, destinations in (deps.get("dependsOn") or {}).items():
        neighbors.setdefault(src, set()).update(destinations)
        for destination in destinations:
            neighbors.setdefault(destination, set()).add(src)
    for seed, seed_score in list(scores.items()):
        for neighbor in neighbors.get(seed, set()):
            if module_languages.get(neighbor) == module_languages.get(seed):
                scores[neighbor] = max(scores.get(neighbor, 0), max(1, seed_score // 4))

    grouped: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for module, score in scores.items():
        language = module_languages.get(module)
        frontend = _FRONTENDS.get(language or "")
        if frontend:
            grouped.setdefault((language, frontend), []).append((module, score))

    groups: list[_Group] = []
    for (language, frontend), ranked in sorted(grouped.items()):
        selected: list[str] = []
        excluded: list[dict] = []
        selected_bytes = 0
        for module, score in sorted(ranked, key=lambda item: (-item[1], item[0])):
            source = Path(file_map[module])
            if source.is_symlink():
                excluded.append({"path": module, "reason": "symlink"})
                continue
            try:
                size = source.stat().st_size
            except OSError as exc:
                excluded.append({"path": module, "reason": f"unreadable: {exc}"})
                continue
            if len(selected) >= max_files:
                excluded.append({"path": module, "reason": "candidate-file-budget"})
                continue
            if selected_bytes + size > max_bytes:
                excluded.append({"path": module, "reason": "candidate-byte-budget"})
                continue
            selected.append(module)
            selected_bytes += size
        if selected:
            groups.append(_Group(language=language, frontend=frontend,
                                 candidates=tuple(sorted(selected)), excluded=tuple(excluded),
                                 score=tuple(sorted(((m, scores[m]) for m in selected),
                                                    key=lambda item: (-item[1], item[0])))))
    return groups


def _patterns(group: _Group, observations: list[dict], symbols: dict[str, list[dict]]) -> list[dict]:
    seen: set[str] = set()
    items: list[dict] = []
    for observation in observations:
        if observation.get("module") not in group.candidates:
            continue
        value = str(observation.get("evidence") or "").strip()
        if value and value not in seen:
            seen.add(value)
            items.append({"value": value, "atom": str(observation.get("atom") or "")})
    if not items:
        for module in group.candidates:
            for symbol in symbols.get(module, []):
                value = str(symbol.get("name") or "").strip()
                if value and value not in seen and symbol.get("kind") != "import":
                    seen.add(value)
                    items.append({"value": value, "atom": "SYMBOL"})
    if not items:
        items = [{"value": Path(module).stem, "atom": "FILE"} for module in group.candidates]
    return items[:50]


def _profile(group: _Group, observations: list[dict], symbols: dict[str, list[dict]]) -> dict:
    patterns = _patterns(group, observations, symbols)
    source_patterns = [p for p in patterns if p["atom"].startswith(_INPUT_ATOMS)] or patterns
    sink_patterns = patterns

    def entries(kind: str, values: list[dict]) -> list[dict]:
        return [{"id": f"{kind}-{i:03d}", "pattern": re.escape(item["value"])}
                for i, item in enumerate(values, 1)]

    return {
        "schemaVersion": 1,
        "id": "lucent-indexed-code-flow-v1",
        "findingKind": "indexed-code-flow",
        "sources": entries("source", source_patterns),
        "sinks": entries("sink", sink_patterns),
    }


def _stage(group: _Group, file_map: dict[str, str], root: Path) -> tuple[Path, str]:
    target = root / "target"
    target.mkdir(parents=True)
    entries = []
    for module in group.candidates:
        data = Path(file_map[module]).read_bytes()
        destination = target / module
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o444)
        entries.append({"path": Path(module).as_posix(), "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    return target, _digest({"files": entries})


def _cached_cpg(outdir: Path, *, manifest: str, frontend: str) -> tuple[Path, str] | None:
    cpg = outdir / "cpg.bin"
    evidence_path = outdir / "evidence.json"
    if not cpg.is_file() or cpg.stat().st_size <= 0 or not evidence_path.is_file():
        return None
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    image = evidence.get("producer", {}).get("image")
    if (evidence.get("target", {}).get("manifestSha256") != manifest
            or evidence.get("analysis", {}).get("language") != frontend
            or not isinstance(image, str) or not _IMAGE.fullmatch(image)):
        return None
    return cpg, image


def _normalize_file(value: object) -> object:
    if not isinstance(value, str):
        return value
    return value.removeprefix("/input/").removeprefix("input/")


def _validate_evidence(evidence: dict, *, request: JoernRequest, manifest: str,
                       profile_digest: str | None, target_label: str,
                       reused_image: str | None = None) -> dict:
    if not isinstance(evidence, dict) or evidence.get("schemaVersion") != 1:
        raise JoernProviderError("Joern evidence is not a schemaVersion 1 object")
    producer = evidence.get("producer")
    target = evidence.get("target")
    analysis = evidence.get("analysis")
    coverage = evidence.get("coverage")
    graph = evidence.get("graph")
    metrics = evidence.get("metrics")
    if not all(isinstance(value, dict) for value in
               (producer, target, analysis, coverage, graph, metrics)):
        raise JoernProviderError("Joern evidence is missing a required object")
    image = producer.get("image")
    if not isinstance(image, str) or not _IMAGE.fullmatch(image):
        raise JoernProviderError("Joern evidence does not identify an immutable image digest")
    if reused_image is not None and image != reused_image:
        raise JoernProviderError("reused CPG image provenance does not match the selected image")
    if target.get("manifestSha256") != manifest or not _DIGEST.fullmatch(str(manifest)):
        raise JoernProviderError("Joern evidence target manifest does not match staged candidates")
    if analysis.get("language") != request.frontend or analysis.get("mode") != request.mode:
        raise JoernProviderError("Joern evidence frontend or mode does not match the request")
    if request.mode == "behavior-flow" and analysis.get("profileSha256") != profile_digest:
        raise JoernProviderError("Joern evidence profile digest does not match Lucent's profile")
    if analysis.get("sliceDepth") != request.slice_depth:
        raise JoernProviderError("Joern evidence does not preserve the requested slice depth")
    for field in ("nodes", "edges", "paths", "findings"):
        if not isinstance(graph.get(field), list):
            raise JoernProviderError(f"Joern evidence graph has no {field} array")
    if request.mode == "behavior-flow":
        relations = {path.get("relation") for path in graph["paths"] if isinstance(path, dict)}
        if not relations <= {"explicit-reaching-def", "slice-selected-by-sink"}:
            raise JoernProviderError("Joern evidence contains an unknown path relation")
    for field in ("filesObservedInSlice", "excluded", "unresolved", "limitations"):
        if not isinstance(coverage.get(field), list):
            raise JoernProviderError(f"Joern evidence coverage has no {field} array")
    limits = analysis.get("limits")
    if not isinstance(limits, dict) or limits.get("timeoutSeconds") != request.timeout:
        raise JoernProviderError("Joern evidence does not preserve the requested resource budget")

    # Rekit's IDs are stable already. Sorting the containers makes the evidence deterministic
    # even if an external runner serializes those arrays in a different order.
    normalized = json.loads(json.dumps(evidence))
    normalized["target"]["path"] = target_label
    for node in normalized["graph"]["nodes"]:
        if isinstance(node, dict) and "parentFile" in node:
            node["parentFile"] = _normalize_file(node.get("parentFile"))
    for unresolved in normalized["coverage"]["unresolved"]:
        if isinstance(unresolved, dict) and "file" in unresolved:
            unresolved["file"] = _normalize_file(unresolved.get("file"))
    normalized["coverage"]["filesObservedInSlice"] = sorted(
        (_normalize_file(path) for path in normalized["coverage"]["filesObservedInSlice"]),
        key=str)
    normalized["graph"]["nodes"].sort(key=lambda item: str(item.get("id")) if isinstance(item, dict) else "")
    normalized["graph"]["edges"].sort(key=lambda item: (
        str(item.get("src")), str(item.get("dst")), str(item.get("label"))) if isinstance(item, dict) else ("", "", ""))
    normalized["graph"]["paths"].sort(key=lambda item: str(item.get("id")) if isinstance(item, dict) else "")
    normalized["graph"]["findings"].sort(key=lambda item: str(item.get("id")) if isinstance(item, dict) else "")
    return normalized


def _record(group: _Group, *, mode: str, status: str, max_files: int, max_bytes: int,
            evidence: dict | None = None, error: str | None = None) -> dict:
    graph = (evidence or {}).get("graph") or {}
    stable_evidence = {
        "producer": (evidence or {}).get("producer"),
        "target": (evidence or {}).get("target"),
        "analysis": (evidence or {}).get("analysis"),
        "coverage": (evidence or {}).get("coverage"),
        "graph": graph,
    } if evidence else None
    return {
        "provider": "joern",
        "sourceLanguage": group.language,
        "frontend": group.frontend,
        "mode": mode,
        "status": status,
        "selection": {
            "strategy": "lucent-index",
            "candidates": list(group.candidates),
            "scores": [{"path": path, "score": score} for path, score in group.score],
            "excluded": list(group.excluded),
            "limits": {"maxFilesPerLanguage": max_files, "maxBytesPerLanguage": max_bytes},
        },
        "evidenceSha256": _digest(stable_evidence) if stable_evidence else None,
        "evidence": evidence,
        "error": error,
    }


def run_joern_provider(*, target_path: Path, run_dir: Path, observations: list[dict],
                       findings: list[dict], module_languages: dict[str, str],
                       file_map: dict[str, str], symbols: dict[str, list[dict]], deps: dict,
                       goal: str | None, max_files: int, max_bytes: int, timeout: int,
                       slice_depth: int, runner: JoernRunner | None = None) -> list[dict]:
    """Run bounded per-language slices and return durable records; never raise per-run errors."""
    runner = runner or RekitJoernRunner()
    groups = _candidate_groups(
        observations=observations, findings=findings, module_languages=module_languages,
        file_map=file_map, symbols=symbols, deps=deps, goal=goal,
        max_files=max_files, max_bytes=max_bytes)
    if not groups:
        return [{
            "provider": "joern", "sourceLanguage": None, "frontend": None,
            "mode": "selection", "status": "skipped",
            "selection": {"strategy": "lucent-index", "candidates": [], "excluded": [],
                          "limits": {"maxFilesPerLanguage": max_files,
                                     "maxBytesPerLanguage": max_bytes}},
            "evidenceSha256": None, "evidence": None,
            "error": "Lucent's index found no Joern-supported behavior or goal-matched code",
        }]

    records: list[dict] = []
    for group in groups:
        profile = _profile(group, observations, symbols)
        profile_digest = _digest(profile)
        base_out = run_dir / "deep" / "joern" / f"{group.language}-{group.frontend}"
        behavior_out = base_out / "behavior-flow"
        usage_out = base_out / "usages"
        with tempfile.TemporaryDirectory(prefix="lucent-joern-") as temporary:
            stage_root = Path(temporary)
            try:
                staged_target, manifest = _stage(group, file_map, stage_root)
                profile_path = stage_root / "profile.json"
                profile_path.write_bytes(_canonical(profile) + b"\n")
            except OSError as exc:
                records.append(_record(group, mode="selection", status="failed",
                                       max_files=max_files, max_bytes=max_bytes,
                                       error=f"could not stage index-selected candidates: {exc}"))
                continue

            cached = _cached_cpg(behavior_out, manifest=manifest, frontend=group.frontend)
            reuse_cpg, reused_image = cached if cached else (None, None)
            behavior_request = JoernRequest(
                target=staged_target, outdir=behavior_out, frontend=group.frontend,
                mode="behavior-flow", timeout=timeout, slice_depth=slice_depth,
                profile=profile_path, reuse_cpg=reuse_cpg)
            try:
                behavior = runner.run(behavior_request)
                behavior = _validate_evidence(
                    behavior, request=behavior_request, manifest=manifest,
                    profile_digest=profile_digest,
                    target_label=f"{target_path} (index-selected {group.language} subset)",
                    reused_image=reused_image)
                records.append(_record(group, mode="behavior-flow", status="completed",
                                       max_files=max_files, max_bytes=max_bytes,
                                       evidence=behavior))
            except Exception as exc:
                records.append(_record(group, mode="behavior-flow", status="failed",
                                       max_files=max_files, max_bytes=max_bytes, error=str(exc)))
                records.append(_record(group, mode="usages", status="skipped",
                                       max_files=max_files, max_bytes=max_bytes,
                                       error="usage slice skipped because the shared language CPG was unavailable"))
                continue

            cpg = behavior_out / "cpg.bin"
            usage_request = JoernRequest(
                target=staged_target, outdir=usage_out, frontend=group.frontend,
                mode="usages", timeout=timeout, slice_depth=slice_depth, reuse_cpg=cpg)
            try:
                usage = runner.run(usage_request)
                usage = _validate_evidence(
                    usage, request=usage_request, manifest=manifest, profile_digest=None,
                    target_label=f"{target_path} (index-selected {group.language} subset)",
                    reused_image=behavior.get("producer", {}).get("image"))
                records.append(_record(group, mode="usages", status="completed",
                                       max_files=max_files, max_bytes=max_bytes,
                                       evidence=usage))
            except Exception as exc:
                records.append(_record(group, mode="usages", status="failed",
                                       max_files=max_files, max_bytes=max_bytes, error=str(exc)))
    return records


def context_for_module(records: list[dict], module: str | None, *, limit: int = 4) -> list[dict]:
    """Project file-relevant Joern paths/usages into a small, model-safe context."""
    if not module:
        return []
    contexts: list[dict] = []
    for record in records:
        if record.get("status") != "completed" or module not in (
                record.get("selection", {}).get("candidates") or []):
            continue
        evidence = record.get("evidence") or {}
        graph = evidence.get("graph") or {}
        nodes = {str(node.get("id")): node for node in graph.get("nodes", [])
                 if isinstance(node, dict)}
        if record.get("mode") == "behavior-flow":
            for path in graph.get("paths", []):
                steps = [nodes.get(str(identifier)) for identifier in path.get("nodes", [])]
                steps = [step for step in steps if step]
                if not any(_normalize_file(step.get("parentFile")) == module for step in steps):
                    continue
                contexts.append({
                    "mode": "behavior-flow", "language": record.get("sourceLanguage"),
                    "relation": path.get("relation"),
                    "steps": [{"file": _normalize_file(step.get("parentFile")),
                               "line": step.get("lineNumber"), "method": step.get("parentMethod"),
                               "code": step.get("code"), "type": step.get("typeFullName")}
                              for step in steps[:12]],
                })
                if len(contexts) >= limit:
                    return contexts
        else:
            related = [node for node in nodes.values()
                       if _normalize_file(node.get("parentFile")) == module]
            if related:
                ids = {str(node.get("id")) for node in related}
                edges = [edge for edge in graph.get("edges", [])
                         if str(edge.get("src")) in ids or str(edge.get("dst")) in ids]
                contexts.append({
                    "mode": "usages", "language": record.get("sourceLanguage"),
                    "nodes": [{"file": module, "line": node.get("lineNumber"),
                               "method": node.get("parentMethod"), "name": node.get("name"),
                               "code": node.get("code"), "type": node.get("typeFullName")}
                              for node in related[:12]],
                    "relations": [str(edge.get("label")) for edge in edges[:12]],
                })
                if len(contexts) >= limit:
                    return contexts
    return contexts
