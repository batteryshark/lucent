"""lucent's phase graph: thin domain nodes over muster's scaffolding.

    InitializeRun -> InventorySources -> ProcessWorkQueue (drain) -> ComposeFindings
                  -> RenderReport -> End

muster provides the machinery (identity, the ledger, the work-queue drain, resume,
coverage); the nodes here provide the domain. The drain covers every source file with two
operations: ``understand-file`` (observe behaviour atoms across any language, plus extract
Python structure) and ``link-imports`` (resolve the Python reference graph). After the
surface is fully observed, ``ComposeFindings`` reads the atoms and structure through the
four lenses, and ``RenderReport`` builds an assessment and renders it.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_graph import BaseNode, End, Graph, GraphBuilder, GraphRunContext

from muster import GraphDeps, GraphState, WorkDispatcher
from muster import atomic_write as _atomic_write
from muster import enter as _enter
from muster import stable_key

from lucent import assess as _assess
from lucent import lens as _lens
from lucent import observe as _observe
from lucent import reachability as _reachability
from lucent import report as _report
from lucent import structure as _structure
from lucent.signatures import Signatures

# Runaway backstop for the drain loop (far above any real file count).
_MAX_WORK_ITEMS = 20000
# How many finding reviews to keep in flight at once. Reviews are IO-bound model calls, and
# muster's single-threaded asyncio makes concurrent ledger writes safe (each commits between
# awaits), so running them concurrently cuts wall-clock time versus one at a time.
_REVIEW_CONCURRENCY = 6
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
              ".mypy_cache", ".pytest_cache", ".tox", "build", "dist", ".idea", ".vscode"}


@dataclass
class LucentConfig:
    storage_root: str = ".lucent"
    max_iterations: int = 2000
    # Optional agentic-review overlay (requires lucent[review]); off by default. `model` is a
    # default `[provider:]model_id` spec; `models` overrides it per role (only "reviewer" so far).
    review: bool = False
    model: str | None = None
    models: dict = field(default_factory=dict)
    # Optional goal or question that steers the agentic reviewer toward one area, capability,
    # or question. It does not touch the deterministic passes: those stay exhaustive so the
    # coverage guarantee holds. The goal only affects interpretation and what the report
    # surfaces.
    goal: str | None = None

    def config_hash(self) -> str:
        # model/models/goal are volatile routing, not identity; drop them so a run's id is stable
        # across model and goal choices. `review` stays: it changes what the run produces.
        stable = {k: v for k, v in self.__dict__.items() if k not in {"model", "models", "goal"}}
        return hashlib.sha256(
            json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()[:12]


@dataclass(kw_only=True)
class LucentState(GraphState):
    """lucent's transient run context: muster's identity and counter fields, unchanged."""


@dataclass(kw_only=True)
class LucentDeps(GraphDeps):
    """Heavy objects live here. Adds the lucent config and an optional injected review model
    (tests pass a pydantic-ai TestModel; None resolves from LUCENT_REVIEW_* at review time).
    The ledger/paths/scratch/resume come from muster's GraphDeps base."""
    config: LucentConfig = field(default_factory=LucentConfig)
    review_model: Any = None

    def model_for(self, role: str):
        """Resolve the pydantic-ai model for a bounded model step's role. An injected
        `review_model` overrides every role; otherwise the fallback order is
        `config.models[role]`, then `config.model`, then the LUCENT_REVIEW_* env. Raises
        ReviewConfigError if nothing is configured. The caller treats that as "skip review",
        so the deterministic report is unaffected."""
        if self.review_model is not None:
            return self.review_model
        from lucent.review.config import ReviewModelConfig
        spec = (self.config.models or {}).get(role) or self.config.model
        return ReviewModelConfig.from_spec(spec).build_model()


_Ctx = GraphRunContext[LucentState, LucentDeps]
_SIGS = Signatures.load()


@dataclass
class InitializeRun(BaseNode[LucentState, LucentDeps, dict]):
    async def run(self, ctx: _Ctx) -> "InventorySources":
        d, s = ctx.deps, ctx.state
        _enter(ctx, "InitializeRun")
        _atomic_write(d.paths.run_json, json.dumps(
            {"runId": s.run_id, "projectId": s.project_id, "status": "running"}, indent=2))
        d.ledger.event(s.run_id, "InitializeRun", "note", {"runId": s.run_id})
        return InventorySources()


@dataclass
class InventorySources(BaseNode[LucentState, LucentDeps, dict]):
    """Enumerate the surface: one ``understand-file`` work item per source file lucent can
    parse (any language its extractor covers), across every supported extension. This is
    lucent's coverage predicate: everything enqueued here must drain to a terminal state."""

    async def run(self, ctx: _Ctx) -> "ProcessWorkQueue":
        d, s = ctx.deps, ctx.state
        _enter(ctx, "InventorySources")
        root = Path(str(s.target_path))
        if root.is_file():
            base, candidates = root.parent, [root]
        else:
            base = root
            candidates = [p for p in sorted(root.rglob("*"))
                          if p.is_file() and not any(part in _SKIP_DIRS
                                                     for part in p.relative_to(root).parts)]
        count = 0
        for p in candidates:
            lang = _observe.language_for(p.name)
            if lang is None:
                continue
            rel = p.name if root.is_file() else str(p.relative_to(base))
            aid = d.ledger.add_artifact(run_id=s.run_id, kind="source-file", origin="inventory",
                                        path=str(p), logical_path=rel, language=lang)
            d.ledger.enqueue(run_id=s.run_id, key=stable_key(rel, "understand-file"), target=rel,
                             operation="understand-file", category="file",
                             title=f"Understand {rel}",
                             payload={"artifactId": aid, "path": str(p), "language": lang})
            count += 1
        d.ledger.event(s.run_id, "InventorySources", "note", {"files": count})
        return ProcessWorkQueue()


@dataclass
class ProcessWorkQueue(BaseNode[LucentState, LucentDeps, dict]):
    """muster's drain loop, lucent's handlers: lease the next file, understand it (observe
    atoms + Python structure, maybe enqueue a link-imports follow-up), self-loop until
    covered."""

    async def run(self, ctx: _Ctx) -> "ProcessWorkQueue | ComposeFindings":
        d, s = ctx.deps, ctx.state
        _enter(ctx, "ProcessWorkQueue")
        processed = d.scratch.get("wq_processed", 0)
        if processed >= _MAX_WORK_ITEMS:  # runaway backstop; records an event before bailing out
            d.ledger.event(s.run_id, "ProcessWorkQueue", "note",
                           {"stopped": "max-work-items", "processed": processed})
            return ComposeFindings()
        item = _DISPATCHER.run_one(ctx)
        if item is None:
            d.ledger.event(s.run_id, "ProcessWorkQueue", "note",
                           {"drained": True, "processed": processed})
            return ComposeFindings()
        d.scratch["wq_processed"] = processed + 1
        return ProcessWorkQueue()


@dataclass
class ComposeFindings(BaseNode[LucentState, LucentDeps, dict]):
    """Read the fully-observed surface through the four lenses and record findings. This runs
    after the drain, so the whole atom + structure substrate is known and composition is
    deterministic."""

    async def run(self, ctx: _Ctx) -> "ReviewFindings":
        d, s = ctx.deps, ctx.state
        _enter(ctx, "ComposeFindings")
        obs = d.ledger.observations(s.run_id)
        deps = d.ledger.dependency_graph(s.run_id)
        failed = d.ledger.failed_work(s.run_id, "understand-file")
        module_langs = d.ledger.module_languages(s.run_id)
        reach = d.ledger.reachability(s.run_id)
        findings = _lens.compose(obs, deps, failed, module_langs, reach)
        for f in findings:
            d.ledger.add_finding(
                run_id=s.run_id, lens=f["lens"], title=f["title"], claim=f["claim"],
                confidence=f["confidence"], fragility=f.get("fragility"), conf_label=f["conf_label"],
                module=f.get("module"), composition=f.get("composition"),
                evidence=f["evidence"], disproof=f["disproof"], verify=f["verify"])
        d.ledger.event(s.run_id, "ComposeFindings", "note", {"findings": len(findings)})
        return ReviewFindings()


@dataclass
class ReviewFindings(BaseNode[LucentState, LucentDeps, dict]):
    """Optional agentic overlay: read the code behind each finding and deepen it. Gated on
    ``config.review`` and a resolvable model. If review is off, no model is configured, or
    pydantic-ai is not installed, this skips cleanly and the deterministic report is unchanged."""

    async def run(self, ctx: _Ctx) -> "RenderReport":
        d, s = ctx.deps, ctx.state
        if not d.config.review:
            return RenderReport()
        _enter(ctx, "ReviewFindings")
        try:
            model = d.model_for("reviewer")
        except Exception as exc:                 # not configured / pydantic-ai missing
            d.ledger.event(s.run_id, "ReviewFindings", "note",
                           {"skipped": "no-review-model", "error": repr(exc)})
            return RenderReport()

        from lucent.review import build_reviewer, review_finding
        findings = d.ledger.findings(s.run_id)
        file_map = d.ledger.artifact_paths(s.run_id)
        obs_by_id = {o["id"]: _assess._obs_to_dict(o, file_map)
                     for o in d.ledger.observations(s.run_id)}
        model_name = getattr(model, "model_name", None) or d.config.model
        agent = build_reviewer(model)
        sem = asyncio.Semaphore(_REVIEW_CONCURRENCY)

        goal = d.config.goal

        async def _review(f: dict) -> None:
            evidence = [obs_by_id[ev["obs"]] for ev in f.get("evidence", [])
                        if isinstance(ev, dict) and ev.get("obs") in obs_by_id]
            async with sem:                         # bound concurrent model calls
                review = await review_finding(f, evidence, goal=goal, agent=agent)
            d.ledger.record_review(s.run_id, review, model=model_name)  # sync commit, no await held

        await asyncio.gather(*(_review(f) for f in findings))
        d.ledger.event(s.run_id, "ReviewFindings", "note", {"reviewed": len(findings)})
        return RenderReport()


@dataclass
class RenderReport(BaseNode[LucentState, LucentDeps, dict]):
    async def run(self, ctx: _Ctx) -> End[dict]:
        d, s = ctx.deps, ctx.state
        _enter(ctx, "RenderReport")
        coverage = d.ledger.coverage(s.run_id)
        summary = {
            "fileCount": d.ledger.count_files(s.run_id),
            "moduleCount": d.ledger.count_files(s.run_id, "python"),
            "languages": d.ledger.language_counts(s.run_id),
            "symbolCount": d.ledger.count_symbols(s.run_id),
            "atomCount": d.ledger.count_observations(s.run_id),
            "capabilities": d.ledger.atom_counts(s.run_id),
        }
        assessment = _assess.build_assessment(
            target_path=str(s.target_path),
            findings=d.ledger.findings(s.run_id),
            observations=d.ledger.observations(s.run_id),
            deps=d.ledger.dependency_graph(s.run_id),
            summary=summary, file_map=d.ledger.artifact_paths(s.run_id),
            extraction_mode=_observe.extraction_mode(), coverage=coverage,
            reviews=d.ledger.reviews(s.run_id), goal=d.config.goal,
            docstrings=d.ledger.docstrings(s.run_id))

        # Optional agentic purpose + mechanism synthesis: "what is this for, and how does it do
        # that?" Runs only when review is on and a model resolves; failure leaves the
        # docstring-derived purpose untouched.
        if d.config.review:
            try:
                from lucent.review import synthesize_purpose
                synth = await synthesize_purpose(
                    assessment["overview"], assessment["composition"],
                    goal=d.config.goal, model=d.model_for("reviewer"))
                if synth is not None:
                    assessment["overview"]["purpose"] = synth.purpose
                    assessment["overview"]["howItWorks"] = synth.how_it_works
                    d.ledger.event(s.run_id, "RenderReport", "note", {"synthesized": True})
            except Exception as exc:
                d.ledger.event(s.run_id, "RenderReport", "note",
                               {"synthesis_skipped": repr(exc)})

        reports_dir = d.paths.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_paths: dict[str, str] = {}
        for fmt, ext, render in (("json", "json", _report.render_json),
                                 ("markdown", "md", _report.render_markdown),
                                 ("html", "html", _report.render_html)):
            path = reports_dir / f"understanding.{ext}"
            _atomic_write(path, render(assessment))
            d.ledger.add_report(s.run_id, fmt, str(path))
            report_paths[fmt] = str(path)

        final_summary = assessment["summary"]
        d.ledger.finish_run(s.run_id, "completed", coverage=coverage, summary=final_summary)
        _atomic_write(d.paths.run_json, json.dumps(
            {"runId": s.run_id, "projectId": s.project_id, "status": "completed",
             "reportPaths": {"json": "reports/understanding.json",
                             "markdown": "reports/understanding.md",
                             "html": "reports/understanding.html"}}, indent=2))
        d.ledger.event(s.run_id, "RenderReport", "note", final_summary)
        return End({"runId": s.run_id, "projectId": s.project_id, "runDir": str(s.run_dir),
                    "status": "completed", "coverage": coverage, "summary": final_summary,
                    "synopsis": assessment["synopsis"]["text"], "reportPaths": report_paths})


def build_graph() -> Graph:
    g = GraphBuilder(name="lucent", state_type=LucentState, deps_type=LucentDeps,
                     input_type=InitializeRun, output_type=dict)
    g.add(
        g.edge_from(g.start_node).to(InitializeRun),
        g.node(InitializeRun),
        g.node(InventorySources),
        g.node(ProcessWorkQueue),
        g.node(ComposeFindings),
        g.node(ReviewFindings),
        g.node(RenderReport),
    )
    return g.build()


# --- work-queue handlers (lucent's domain operations) ----------------------

def _handle_understand_file(ctx: _Ctx, item: dict) -> None:
    """Observe one file's behaviour atoms (any language) and, for Python, extract its symbols
    and enqueue a ``link-imports`` follow-up. A file that will not parse is recorded as a
    tracked failure rather than crashing the run."""
    d, s = ctx.deps, ctx.state
    rel = item["target"]
    payload = json.loads(item.get("payload_json") or "{}")
    path, lang = payload.get("path", ""), payload.get("language", "")
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        d.ledger.set_work_status(item["id"], "failed", error=f"{type(exc).__name__}: {exc}")
        return

    py_tree = None
    n_defs = n_imports = 0
    if lang == "python":
        try:
            py_tree = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError) as exc:
            d.ledger.set_work_status(item["id"], "failed", error=f"{type(exc).__name__}: {exc}")
            return
        defs, imports = _structure.extract_symbols(py_tree)
        for name, kind, lineno, detail in defs:
            d.ledger.add_symbol(run_id=s.run_id, module=rel, name=name, kind=kind,
                                lineno=lineno, detail=detail)
        doc = ast.get_docstring(py_tree)
        if doc and doc.strip():
            d.ledger.add_docstring(run_id=s.run_id, module=rel, text=doc.strip())
        n_defs, n_imports = len(defs), len(imports)
        for r in _reachability.analyze(py_tree):
            d.ledger.add_reachability(run_id=s.run_id, module=rel, kind=r["kind"],
                                      name=r.get("name"), lineno=r.get("lineno", 0),
                                      detail=r.get("detail"))
        if imports:
            d.ledger.enqueue(run_id=s.run_id, key=stable_key(rel, "link-imports"), target=rel,
                             operation="link-imports", category="imports",
                             title=f"Link imports of {rel}", payload={"imports": imports})

    obs = _observe.observe_source(rel, text, lang, sigs=_SIGS, py_tree=py_tree)
    for o in obs:
        d.ledger.add_observation(run_id=s.run_id, module=rel, atom=o.atom, confidence=o.confidence,
                                 method=o.method, lineno=o.line, evidence=o.evidence, rule_id=o.rule_id)
    d.ledger.set_work_status(item["id"], "done",
                             result={"defs": n_defs, "imports": n_imports, "atoms": len(obs)})


def _handle_link_imports(ctx: _Ctx, item: dict) -> None:
    """Record each Python import as a symbol and as a resolved reference edge. The edge points
    to the internal module the import names, or is marked external. The full module inventory
    is known by now, so resolution is deterministic."""
    d, s = ctx.deps, ctx.state
    src = item["target"]
    payload = json.loads(item.get("payload_json") or "{}")
    imps = payload.get("imports", [])
    root = Path(str(s.target_path))
    root_pkg = root.name if root.is_dir() else ""
    index = _structure.build_module_index(d.ledger.module_paths(s.run_id), root_pkg)
    internal = 0
    for imp in imps:
        d.ledger.add_symbol(run_id=s.run_id, module=src, name=imp["name"], kind="import",
                            lineno=imp["lineno"], detail=imp["target"])
        dst, resolved = _structure.resolve_import(index, src, imp)
        kind = "internal" if dst else ("unresolved" if imp["level"] else "external")
        internal += kind == "internal"
        d.ledger.add_ref(run_id=s.run_id, src_module=src, dst_module=dst, target=resolved,
                         name=imp["name"], lineno=imp["lineno"], kind=kind)
    d.ledger.set_work_status(item["id"], "done",
                             result={"linked": len(imps), "internal": internal})


# Work registry mapping operation names to handlers; WorkDispatcher (from muster) handles
# the lease and dispatch mechanism.
_DISPATCHER = WorkDispatcher({
    "understand-file": _handle_understand_file,
    "link-imports": _handle_link_imports,
}, node_label="ProcessWorkQueue")
