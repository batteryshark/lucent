"""Bounded finding reviewer (pydantic-ai).

One finding in, one typed :class:`FindingReview` out. The model reads the finding and the
exact code it cites, then reports what is happening at those sites, whether the mechanical
reading holds, and what it means for someone changing the code. It does not change a finding's
fragility rating and does not decide completion. Any failure, such as an unreachable endpoint or
malformed output, produces a ``needs_human`` review that keeps the finding rather than dropping it.
"""

from __future__ import annotations

from lucent.review.config import ReviewModelConfig
from lucent.review.schemas import FindingReview

REVIEW_INSTRUCTIONS = (
    "You are a senior engineer helping a colleague understand a codebase. You are given ONE "
    "finding about the code, from one of four lenses: does (a capability), decides (a runtime "
    "fork), brittle (a fragility), surprising (a mismatch). You also get the exact code it "
    "cites. Read the evidence and explain what it means.\n\n"
    "Rules:\n"
    "- Judge only THIS finding, from the cited evidence. Do not invent evidence.\n"
    "- verdict: confirm (the reading holds as stated), refine (it holds, but with important "
    "context the mechanical finding missed, such as it being guarded, scoped, or having a "
    "narrow real purpose), refute (the reading is wrong: dead code, test-only, or a "
    "misidentified callee), needs_human (you genuinely can't tell from the evidence).\n"
    "- explanation: 2-4 plain sentences on what is ACTUALLY happening at these sites in "
    "context, meaning the real behaviour or purpose, not a restatement of the finding. This is "
    "the part that turns a mechanical fact into something a reader can use.\n"
    "- consideration: one sentence on what this means for someone modifying this code (or empty).\n"
    "- reviewed_confidence in [0,1]: how much the finding's reading holds after you read the "
    "evidence. Be willing to refute. A confident 'this is fine because X' helps more than "
    "hedging. This is understanding, not security: findings have no severity, and you do not "
    "change a brittle finding's fragility rating.\n"
    "- If the reader gave a GOAL or question, set `relevance` to one sentence on how this "
    "finding bears on it, and leave it empty if it does not. Do not stretch: an honest 'not "
    "relevant' (empty) is more useful than a forced connection. The goal never changes your "
    "verdict; it only decides what you highlight.\n"
    "- List which of the finding's disproof criteria you actually checked against the evidence."
)


def build_reviewer(model=None):
    """Build an Agent that emits a validated :class:`FindingReview`. ``model`` may be any
    pydantic-ai model, including TestModel or FunctionModel for tests. If omitted, the config
    resolves one from the environment."""
    from pydantic_ai import Agent

    if model is None:
        model = ReviewModelConfig.from_env().build_model()
    return Agent(model, output_type=FindingReview, instructions=REVIEW_INSTRUCTIONS, retries=2)


_MAX_EVIDENCE_CHARS = 600     # a cited line can be long/minified; a sample is enough to judge


def _clip(s: str) -> str:
    return s if len(s) <= _MAX_EVIDENCE_CHARS else f"{s[:_MAX_EVIDENCE_CHARS]}…[+{len(s) - _MAX_EVIDENCE_CHARS} chars]"


def _evidence_lines(evidence: list[dict]) -> list[str]:
    out: list[str] = []
    for o in evidence:
        loc = o.get("location") or {}
        ev = o.get("evidence") or {}
        matched = ev.get("matchedText") or ev.get("summary") or ""
        head = f"- {o.get('atom') or ''} @ {loc.get('path')}:{loc.get('line')} · {_clip(str(matched))}"
        out.append(head)
        snip = ev.get("snippet")
        if snip:
            for ln in snip.get("lines", []):
                mark = ">" if ln.get("match") else " "
                out.append(f"    {mark} {ln['n']}: {_clip(ln['text'])}")
    return out or ["(no cited code evidence; this finding is structural)"]


def build_prompt(finding: dict, evidence: list[dict], goal: str | None = None) -> str:
    lines = [
        f"Finding {finding.get('id')}: {finding.get('title')}  [lens: {finding.get('lens')}"
        f" · {finding.get('composition')}]",
        (f"Fragility: {finding.get('fragility')} · " if finding.get("fragility") else "")
        + f"mechanical confidence: {finding.get('confidence')}",
        f"Claim: {finding.get('claim')}",
        "",
        "What would disprove this finding:",
        *[f"- {d}" for d in finding.get("disproof", [])],
        "",
        "Cited evidence:",
        *_evidence_lines(evidence),
        "",
    ]
    if goal:
        lines += [f"The reader's goal / question: {goal}", ""]
    lines.append(
        f"Review finding {finding.get('id')}: read the evidence, pick the verdict, set "
        "reviewed_confidence, write the explanation and consideration"
        + (", and set `relevance` if this bears on the reader's goal." if goal else "."))
    return "\n".join(lines)


def _deep_context_lines(contexts: list[dict]) -> list[str]:
    if not contexts:
        return []
    out = [
        "Focused Joern context (bounded, index-selected; one language per CPG):",
        "A relation of slice-selected-by-sink means selection context, not a fabricated data-flow edge.",
    ]
    for context in contexts:
        if context.get("mode") == "behavior-flow":
            out.append(f"- behavior path · relation={context.get('relation')}")
            for step in context.get("steps", []):
                out.append(f"    {step.get('file')}:{step.get('line')} · "
                           f"{_clip(str(step.get('code') or step.get('method') or ''))}"
                           + (f" · type={step.get('type')}" if step.get("type") else ""))
        else:
            relations = ", ".join(context.get("relations", [])) or "no normalized edges"
            out.append(f"- usages · relations={relations}")
            for node in context.get("nodes", []):
                out.append(f"    {node.get('file')}:{node.get('line')} · "
                           f"{_clip(str(node.get('code') or node.get('name') or ''))}"
                           + (f" · type={node.get('type')}" if node.get("type") else ""))
    return out


async def review_finding(finding: dict, evidence: list[dict], *, deep_context=None,
                         goal: str | None = None, agent=None, model=None) -> FindingReview:
    """Review one finding. Async so it runs on the graph's event loop. Any failure degrades to
    a ``needs_human`` review that keeps the finding flagged rather than dropping it."""
    agent = agent or build_reviewer(model)
    try:
        prompt = build_prompt(finding, evidence, goal)
        if deep_context:
            prompt += "\n\n" + "\n".join(_deep_context_lines(deep_context))
        result = await agent.run(prompt)
        fr: FindingReview = result.output
        if fr.finding_id != finding.get("id"):
            fr = fr.model_copy(update={"finding_id": finding.get("id", "")})
        return fr
    except Exception as exc:
        return FindingReview(
            finding_id=finding.get("id", ""), verdict="needs_human",
            reviewed_confidence=float(finding.get("confidence") or 0.0),
            explanation=f"reviewer unavailable or produced malformed output: {exc!r}")
