"""Optional agentic-review overlay.

Off by default and behind the ``lucent[review]`` extra (pydantic-ai). When enabled, a bounded
model step reads the code behind each finding and explains what it does. When no model is
configured the overlay is skipped and the deterministic report is unchanged.
"""

from __future__ import annotations

from lucent.review.adjudicate import build_review_overlay
from lucent.review.agent import build_reviewer, review_finding
from lucent.review.config import ReviewConfigError, ReviewModelConfig
from lucent.review.schemas import FindingReview
from lucent.review.synth import PurposeSynthesis, synthesize_purpose

__all__ = ["build_review_overlay", "build_reviewer", "review_finding",
           "ReviewConfigError", "ReviewModelConfig", "FindingReview",
           "PurposeSynthesis", "synthesize_purpose"]
