"""`lucent` command-line interface — understand a Python file or package."""

from __future__ import annotations

import argparse
import json


def _cmd_scan(args: argparse.Namespace) -> int:
    from lucent import LucentConfig, run_lucent

    result = run_lucent(args.target, LucentConfig(storage_root=args.storage_root))
    if args.json:
        print(json.dumps(result.__dict__, indent=2))
        return 0
    s = result.summary
    print(f"Run:      {result.run_id}")
    print(f"Dir:      {result.run_dir}")
    print(f"Status:   {result.status}")
    print(f"Modules:  {s['modules']}   Symbols: {s['symbols']} "
          f"({s['functions']} fn, {s['classes']} cls, {s['methods']} meth, {s['imports']} imp)")
    print(f"Coverage: {result.coverage['done']}/{result.coverage['workItemsTotal']} work items done")
    print(f"Report:   {result.report_path}")
    return 0 if result.status == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lucent", description="Code understanding (a muster consumer)")
    sub = p.add_subparsers(dest="cmd")
    sc = sub.add_parser("scan", help="understand a Python file or package")
    sc.add_argument("target")
    sc.add_argument("--storage-root", default=".lucent")
    sc.add_argument("--json", action="store_true")
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
