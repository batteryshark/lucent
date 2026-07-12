"""`lucent` command-line interface — understand a codebase."""

from __future__ import annotations

import argparse
import json


def _cmd_scan(args: argparse.Namespace) -> int:
    from lucent import LucentConfig, run_lucent

    result = run_lucent(args.target, LucentConfig(
        storage_root=args.storage_root, review=args.review or bool(args.model),
        model=args.model, goal=args.goal))
    if args.json:
        print(json.dumps(result.__dict__, indent=2))
        return 0
    s = result.summary
    langs = ", ".join(f"{k} ({v})" for k, v in (s.get("languages") or {}).items()) or "—"
    by_lens = s.get("byLens") or {}
    lens_bits = ", ".join(f"{v} {k}" for k, v in by_lens.items() if v) or "none"
    print(f"Run:       {result.run_id}")
    print(f"Dir:       {result.run_dir}")
    print(f"Status:    {result.status}")
    print()
    print(f"Synopsis:  {result.synopsis}")
    print()
    print(f"Files:     {s.get('fileCount', 0)}  ({s.get('componentCount', 0)} component(s), "
          f"{s.get('moduleCount', 0)} Python module(s), {s.get('symbolCount', 0)} symbol(s))")
    print(f"Languages: {langs}")
    print(f"Observed:  {s.get('atomCount', 0)} behaviour atom(s)")
    frag = s.get("highestFragility")
    print(f"Findings:  {s.get('findingCount', 0)}  ({lens_bits})"
          + (f"; most fragile: {frag}" if frag else ""))
    if s.get("reviewedCount"):
        print(f"Reviewed:  {s['reviewedCount']} finding(s) by an agentic reviewer")
    print(f"Coverage:  {result.coverage['done']}/{result.coverage['workItemsTotal']} work items done")
    print(f"Report:    {result.report_paths.get('html')}")
    return 0 if result.status == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lucent", description="Code understanding (a muster consumer)")
    sub = p.add_subparsers(dest="cmd")
    sc = sub.add_parser("scan", help="understand a codebase (a file, package, or repo)")
    sc.add_argument("target")
    sc.add_argument("--storage-root", default=".lucent")
    sc.add_argument("--json", action="store_true", help="print the run result as JSON")
    sc.add_argument("--review", action="store_true",
                    help="deepen each finding with an agentic reviewer (needs lucent[review] "
                         "and LUCENT_REVIEW_* env or --model)")
    sc.add_argument("--model", default=None,
                    help="review model spec, e.g. 'openai:gpt-4o' or 'lmstudio:qwen2.5' (implies --review)")
    sc.add_argument("--goal", default=None,
                    help="an optional goal or question to nudge the reviewer toward, e.g. "
                         "'how does auth work?' or 'focus on network egress' (only affects --review)")
    sc.set_defaults(func=_cmd_scan)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "cmd", None):
        build_parser().print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
