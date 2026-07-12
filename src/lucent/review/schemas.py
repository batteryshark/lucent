"""Typed reviewer output.

Bounded judgment: a reviewer reads ONE finding's evidence and returns a narrow, validated
review that *deepens* the understanding — what is actually going on at these sites, and how
much the finding's reading holds. It may not change a brittle finding's fragility rating or
write report prose beyond its explanation. Malformed or uncertain output becomes
``needs_human``, never a silent drop.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal[
    "confirm",       # the finding's reading holds as stated
    "refine",        # holds, but with important context the mechanical finding missed
    "refute",        # the reading is wrong (dead code, test-only, misidentified)
    "needs_human",   # genuinely can't tell from the cited evidence alone
]


class FindingReview(BaseModel):
    finding_id: str
    verdict: Verdict
    reviewed_confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(
        description="2-4 plain sentences on what is ACTUALLY happening at the cited sites, in "
                    "context — the real behaviour or purpose, not a restatement of the finding.")
    consideration: str = Field(
        default="", description="One sentence on what this means for someone changing this code.")
    relevance: str = Field(
        default="", description="If the reader gave a goal or question, one sentence on how this "
                               "finding bears on it — empty if it does not bear on the goal.")
    disproof_checked: list[str] = Field(default_factory=list)
