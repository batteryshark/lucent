"""lucent's phase graph — thin domain nodes over muster's scaffolding.

    InitializeRun -> InventoryModules -> ProcessWorkQueue (drain) -> RenderReport -> End

State/deps subclass muster's kw_only bases; the drain loop is muster's WorkDispatcher; the
helpers (enter/atomic_write) and the coverage oracle (ledger) are muster's. lucent adds
only: what modules to enumerate, how to understand one, and what the report says. Nothing
here imports unmask — the second domain is built on the public muster seam alone.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_graph import BaseNode, End, Graph, GraphBuilder, GraphRunContext

from muster import GraphDeps, GraphState, WorkDispatcher
from muster import atomic_write as _atomic_write
from muster import enter as _enter
from muster import stable_key

from lucent.ledger import LucentLedger

# Runaway backstop for the drain loop (far above any real module count).
_MAX_WORK_ITEMS = 2000
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
              ".mypy_cache", ".pytest_cache", ".tox", "build", "dist"}


@dataclass
class LucentConfig:
    storage_root: str = ".lucent"
    max_iterations: int = 500

    def config_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.__dict__, sort_keys=True).encode("utf-8")).hexdigest()[:12]


@dataclass(kw_only=True)
class LucentState(GraphState):
    """lucent's transient run context — muster's identity/counter fields, unchanged."""


@dataclass(kw_only=True)
class LucentDeps(GraphDeps):
    """Heavy objects live here. Adds the lucent config; the ledger/paths/scratch/resume
    come from muster's GraphDeps base."""
    config: LucentConfig = field(default_factory=LucentConfig)


_Ctx = GraphRunContext[LucentState, LucentDeps]


@dataclass
class InitializeRun(BaseNode[LucentState, LucentDeps, dict]):
    async def run(self, ctx: _Ctx) -> "InventoryModules":
        d, s = ctx.deps, ctx.state
        _enter(ctx, "InitializeRun")
        _atomic_write(d.paths.run_json, json.dumps(
            {"runId": s.run_id, "projectId": s.project_id, "status": "running"}, indent=2))
        d.ledger.event(s.run_id, "InitializeRun", "note", {"runId": s.run_id})
        return InventoryModules()


@dataclass
class InventoryModules(BaseNode[LucentState, LucentDeps, dict]):
    """Enumerate the surface: one `understand-module` work item per Python module. This is
    lucent's coverage predicate — everything enqueued here must drain to done."""

    async def run(self, ctx: _Ctx) -> "ProcessWorkQueue":
        d, s = ctx.deps, ctx.state
        _enter(ctx, "InventoryModules")
        root = Path(str(s.target_path))
        if root.is_file():
            base, modules = root.parent, ([root.name] if root.suffix == ".py" else [])
        else:
            base = root
            modules = [str(p.relative_to(root)) for p in sorted(root.rglob("*.py"))
                       if not any(part in _SKIP_DIRS for part in p.relative_to(root).parts)]
        for rel in modules:
            aid = d.ledger.add_artifact(run_id=s.run_id, kind="python-module", origin="inventory",
                                        path=str(base / rel), logical_path=rel)
            d.ledger.enqueue(run_id=s.run_id, key=stable_key(rel, "understand-module"), target=rel,
                             operation="understand-module", category="module",
                             title=f"Understand {rel}",
                             payload={"artifactId": aid, "path": str(base / rel)})
        d.ledger.event(s.run_id, "InventoryModules", "note", {"modules": len(modules)})
        return ProcessWorkQueue()


@dataclass
class ProcessWorkQueue(BaseNode[LucentState, LucentDeps, dict]):
    """muster's drain loop, lucent's handlers: lease the next module, understand it (may
    enqueue a follow-up), self-loop until the surface is covered."""

    async def run(self, ctx: _Ctx) -> "ProcessWorkQueue | RenderReport":
        d, s = ctx.deps, ctx.state
        _enter(ctx, "ProcessWorkQueue")
        processed = d.scratch.get("wq_processed", 0)
        if processed >= _MAX_WORK_ITEMS:  # runaway backstop; surfaced, never silent
            d.ledger.event(s.run_id, "ProcessWorkQueue", "note",
                           {"stopped": "max-work-items", "processed": processed})
            return RenderReport()
        item = _DISPATCHER.run_one(ctx)  # lease + dispatch to a registered handler
        if item is None:
            d.ledger.event(s.run_id, "ProcessWorkQueue", "note",
                           {"drained": True, "processed": processed})
            return RenderReport()
        d.scratch["wq_processed"] = processed + 1
        return ProcessWorkQueue()


@dataclass
class RenderReport(BaseNode[LucentState, LucentDeps, dict]):
    async def run(self, ctx: _Ctx) -> End[dict]:
        d, s = ctx.deps, ctx.state
        _enter(ctx, "RenderReport")
        coverage = d.ledger.coverage(s.run_id)
        summary = {
            "modules": d.ledger.count_artifacts(s.run_id, "python-module"),
            "symbols": d.ledger.count_symbols(s.run_id),
            "functions": d.ledger.count_symbols(s.run_id, "function"),
            "classes": d.ledger.count_symbols(s.run_id, "class"),
            "methods": d.ledger.count_symbols(s.run_id, "method"),
            "imports": d.ledger.count_symbols(s.run_id, "import"),
        }
        report = {"runId": s.run_id, "projectId": s.project_id, "target": str(s.target_path),
                  "coverage": coverage, "summary": summary,
                  "modules": d.ledger.symbols_by_module(s.run_id)}
        reports_dir = d.paths.reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / "understanding.json"
        _atomic_write(report_path, json.dumps(report, indent=2))
        d.ledger.add_report(s.run_id, "json", str(report_path))
        d.ledger.finish_run(s.run_id, "completed", coverage=coverage, summary=summary)
        _atomic_write(d.paths.run_json, json.dumps(
            {"runId": s.run_id, "projectId": s.project_id, "status": "completed",
             "reportPaths": {"json": "reports/understanding.json"}}, indent=2))
        d.ledger.event(s.run_id, "RenderReport", "note", summary)
        return End({"runId": s.run_id, "projectId": s.project_id, "runDir": str(s.run_dir),
                    "status": "completed", "coverage": coverage, "summary": summary,
                    "reportPath": str(report_path)})


def build_graph() -> Graph:
    g = GraphBuilder(name="lucent", state_type=LucentState, deps_type=LucentDeps,
                     input_type=InitializeRun, output_type=dict)
    g.add(
        g.edge_from(g.start_node).to(InitializeRun),
        g.node(InitializeRun),
        g.node(InventoryModules),
        g.node(ProcessWorkQueue),
        g.node(RenderReport),
    )
    return g.build()


# --- work-queue handlers (lucent's domain operations) ----------------------

def _extract_symbols(tree: ast.Module):
    """(defs, imports) — top-level functions/classes + their methods, and import targets."""
    defs: list[tuple[str, str, int, str | None]] = []
    imports: list[tuple[str, int, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append((node.name, "function", node.lineno, None))
        elif isinstance(node, ast.ClassDef):
            defs.append((node.name, "class", node.lineno, None))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.append((sub.name, "method", sub.lineno, node.name))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.append((a.asname or a.name, node.lineno, a.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                target = f"{mod}.{a.name}" if mod else a.name
                imports.append((a.asname or a.name, node.lineno, target))
    return defs, imports


def _handle_understand_module(ctx: _Ctx, item: dict) -> None:
    """Parse one module, record its defs, and enqueue a `link-imports` follow-up when it
    has imports — exercising muster's enqueue-more-work-mid-drain path."""
    d, s = ctx.deps, ctx.state
    rel = item["target"]
    payload = json.loads(item.get("payload_json") or "{}")
    try:
        tree = ast.parse(Path(payload.get("path", "")).read_text(encoding="utf-8"), filename=rel)
    except (OSError, SyntaxError, ValueError) as exc:  # a broken module is a tracked failure
        d.ledger.set_work_status(item["id"], "failed", error=f"{type(exc).__name__}: {exc}")
        return
    defs, imports = _extract_symbols(tree)
    for name, kind, lineno, detail in defs:
        d.ledger.add_symbol(run_id=s.run_id, module=rel, name=name, kind=kind,
                            lineno=lineno, detail=detail)
    if imports:
        d.ledger.enqueue(run_id=s.run_id, key=stable_key(rel, "link-imports"), target=rel,
                         operation="link-imports", category="imports",
                         title=f"Link imports of {rel}",
                         payload={"imports": [list(i) for i in imports]})
    d.ledger.set_work_status(item["id"], "done",
                             result={"defs": len(defs), "imports": len(imports)})


def _handle_link_imports(ctx: _Ctx, item: dict) -> None:
    """Record the import symbols a module pulled in (the follow-up enqueued above)."""
    d, s = ctx.deps, ctx.state
    payload = json.loads(item.get("payload_json") or "{}")
    imps = payload.get("imports", [])
    for name, lineno, target in imps:
        d.ledger.add_symbol(run_id=s.run_id, module=item["target"], name=name, kind="import",
                            lineno=lineno, detail=target)
    d.ledger.set_work_status(item["id"], "done", result={"linked": len(imps)})


# lucent's work registry — muster owns the lease/dispatch mechanism.
_DISPATCHER = WorkDispatcher({
    "understand-module": _handle_understand_module,
    "link-imports": _handle_link_imports,
}, node_label="ProcessWorkQueue")
