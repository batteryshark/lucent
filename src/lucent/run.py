"""Top-level run orchestration for lucent: set up storage and the ledger, drive the graph.

The orchestration shape (compute identity, create the run dir, create the ledger, drive the
graph, close) comes from muster. The domain supplies only the ledger class, the deps, and
the graph.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from muster.paths import RunPaths, compute_project_id, compute_run_id, new_run_paths, resolve_run_dir

from lucent.graph import InitializeRun, LucentConfig, LucentDeps, LucentState, build_graph
from lucent.ledger import LucentLedger


@dataclass
class LucentResult:
    run_id: str
    project_id: str
    run_dir: str
    status: str
    coverage: dict
    summary: dict
    synopsis: str
    report_paths: dict


def _drive(paths: RunPaths, config: LucentConfig, target_path: Path,
           ledger: LucentLedger, *, review_model=None, joern_runner=None,
           resume: bool = False) -> LucentResult:
    state = LucentState(run_id=paths.run_id, project_id=paths.project_id, run_dir=paths.run_dir,
                        db_path=paths.db_path, target_path=target_path,
                        max_iterations=config.max_iterations)
    deps = LucentDeps(ledger=ledger, paths=paths, config=config, resume=resume,
                      review_model=review_model, joern_runner=joern_runner)
    graph = build_graph()
    try:
        result = graph.run_sync(inputs=InitializeRun(), state=state, deps=deps)
    except Exception as exc:
        ledger.finish_run(paths.run_id, "failed", error=repr(exc))
        raise
    finally:
        ledger.close()
    return LucentResult(
        run_id=result["runId"], project_id=result["projectId"], run_dir=result["runDir"],
        status=result["status"], coverage=result["coverage"], summary=result["summary"],
        synopsis=result["synopsis"], report_paths=result["reportPaths"])


def run_lucent(target: str, config: LucentConfig | None = None, *, review_model=None,
               joern_runner=None) -> LucentResult:
    config = config or LucentConfig()
    target_path = Path(target).resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"target does not exist: {target_path}")
    target_root = target_path if target_path.is_dir() else target_path.parent

    project_id, _meta = compute_project_id(target_root)
    run_id, run_hash = compute_run_id(project_id, target_path, config.config_hash())
    paths = new_run_paths(config.storage_root, project_id, run_id, run_hash)

    ledger = LucentLedger(paths.db_path)
    ledger.create_run(
        run_id=run_id, project_id=project_id, target_path=target_path,
        target_root=target_root, storage_root=Path(config.storage_root).resolve(),
        run_dir=paths.run_dir, config_json=json.dumps(config.__dict__),
    )
    return _drive(paths, config, target_path, ledger, review_model=review_model,
                  joern_runner=joern_runner)


def resume_lucent(run_dir: str, *, review_model=None, joern_runner=None) -> LucentResult:
    """Re-drive an existing run from its ledger: reconstruct config and target from the DB,
    clear derived state (reset_run_derived wipes the base tables and the `symbols` table),
    then re-drive."""
    paths = resolve_run_dir(run_dir)
    ledger = LucentLedger(paths.db_path)
    row = ledger.get_run(paths.run_id)
    if row is None:
        ledger.close()
        raise ValueError(f"no run {paths.run_id!r} recorded in {paths.db_path}")
    try:
        config = LucentConfig(**json.loads(row["config_json"] or "{}"))
    except (ValueError, TypeError) as exc:
        ledger.close()
        raise ValueError(f"cannot reconstruct config for {paths.run_id!r}: {exc}") from exc
    target_path = Path(row["target_path"])
    ledger.reset_run_derived(paths.run_id)
    ledger.create_run(
        run_id=paths.run_id, project_id=paths.project_id, target_path=target_path,
        target_root=Path(row["target_root"]), storage_root=Path(row["storage_root"]),
        run_dir=paths.run_dir, config_json=row["config_json"],
    )
    ledger.event(paths.run_id, "ResumeRun", "note", {"resumedFrom": row["status"]})
    return _drive(paths, config, target_path, ledger, review_model=review_model,
                  joern_runner=joern_runner, resume=True)
