"""lucent — figure out a codebase, as a ledgered investigation (a muster consumer).

lucent reads a target and produces a coverage-guaranteed *understanding* of it: a judgment-
free inventory of what each file can do (observation atoms from the parallax taxonomy,
across every language its extractor parses), the Python module's structure and dependency
graph, and an interpretation of both through four lenses —

    does        — what the code actually does (its capabilities)
    decides     — where behaviour forks at runtime (dispatch, entry points, config)
    brittle     — where it is fragile (opaque, remote-dependent, destructive, high-blast-radius)
    surprising  — mismatches (capability that doesn't fit a module's role, orphans)

muster owns the machinery (run identity, the SQLite ledger, the coverage-gated work-queue
drain, resume); lucent brings the domain: the observation engine, the reference graph, the
lenses, and the report. Same durable, resumable spine unmask uses for malicious-code
detection, re-pointed from "is this malicious?" to "what is this, and where is it fragile?".
"""

from __future__ import annotations

from lucent._version import __version__
from lucent.graph import LucentConfig
from lucent.run import LucentResult, resume_lucent, run_lucent

__all__ = ["LucentConfig", "LucentResult", "run_lucent", "resume_lucent", "__version__"]
