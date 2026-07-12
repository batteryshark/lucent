"""lucent: understand a codebase as a ledgered investigation (a muster consumer).

lucent reads a target and produces a coverage-guaranteed understanding of it, in three
parts: a judgment-free inventory of what each file can do (observation atoms from the
parallax taxonomy, across every language its extractor parses), the Python modules'
structure and dependency graph, and an interpretation of both through four lenses.

    does        what the code does (its capabilities)
    decides     where behaviour forks at runtime (dispatch, entry points, config)
    brittle     where the code is fragile (opaque, remote-dependent, destructive, wide blast radius)
    surprising  mismatches (capability that does not fit a module's role, orphans)

muster provides the machinery: run identity, the SQLite ledger, the coverage-gated
work-queue drain, and resume. lucent provides the domain: the observation engine, the
reference graph, the lenses, and the report.
"""

from __future__ import annotations

from lucent._version import __version__
from lucent.graph import LucentConfig
from lucent.run import LucentResult, resume_lucent, run_lucent

__all__ = ["LucentConfig", "LucentResult", "run_lucent", "resume_lucent", "__version__"]
