"""Fold a batch of per-finding reviews into a review overlay for the assessment.

The engine finds the shapes deterministically; the reviewer reads the code behind each and
deepens it. This module tallies the verdicts and produces the ``review`` block the report
renders next to the findings — the run-level "what did a closer read change?" and each
finding's plain-language explanation. It never recomputes findings or fragility; it annotates.
"""

from __future__ import annotations

_VERDICTS = ("confirm", "refine", "refute", "needs_human")


def build_review_overlay(reviews: list[dict], *, model: str | None = None,
                         goal: str | None = None) -> dict | None:
    """``reviews`` are FindingReview dicts (from the ledger). Returns the overlay dict, or None
    when nothing was reviewed. When a ``goal`` was set, the findings the reviewer marked relevant
    to it are collected so the report can lead with what bears on the reader's question."""
    if not reviews:
        return None
    counts = {v: 0 for v in _VERDICTS}
    for r in reviews:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    refuted = [r["finding_id"] for r in reviews if r["verdict"] == "refute"]
    note = (
        "A reviewer read the code behind each finding and deepened it: what is actually "
        "happening at the cited sites, and how much the mechanical reading holds. Fragility is "
        "unchanged; the reviewer refines confidence and adds context.")
    relevant = [{"finding_id": r["finding_id"], "relevance": r.get("relevance", "")}
                for r in reviews if (r.get("relevance") or "").strip()] if goal else []
    return {
        "reviewer": {"model": model, "role": "code-understanding reviewer"},
        "counts": counts,
        "reviewedCount": len(reviews),
        "refutedFindingIds": refuted,
        "reviews": {r["finding_id"]: r for r in reviews},
        "goal": goal,
        "relevant": relevant,
        "note": note,
    }
