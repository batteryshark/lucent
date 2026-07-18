"""Purpose-and-mechanism synthesis (pydantic-ai).

One whole-target model step that answers the two questions the mechanical overview cannot on
its own: what this is for, and how it does that. It reads the target's own words (package and
component docstrings) and its structure (components, their roles and capabilities, and how they
depend on one another), then writes a short, grounded narrative. It does not invent a purpose
the evidence doesn't support. An honest "the stated purpose is X; the mechanism isn't clear
from structure alone" beats a confident fabrication.

It runs only when a review model is configured, and any failure leaves the deterministic
overview (the docstring-derived purpose) untouched.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PurposeSynthesis(BaseModel):
    purpose: str = Field(description="1-2 sentences: what this codebase is FOR. Its intent, in "
                                     "plain language, grounded in its own docstrings and shape.")
    how_it_works: str = Field(description="2-4 sentences: HOW it achieves that purpose. The main "
                                          "mechanism, as a flow through its components (entry → "
                                          "work → output), grounded in the structure given.")


_INSTRUCTIONS = (
    "You are a senior engineer explaining an unfamiliar codebase to a new teammate. From the "
    "target's own docstrings and its component structure, answer two questions:\n"
    "- purpose: what is this FOR? Its intent in plain language. Prefer the code's own framing "
    "(its package docstring) over guessing.\n"
    "- how_it_works: how does it achieve that? Trace the main mechanism as a flow through the "
    "components: what enters, how the components hand off to each other (use the dependency "
    "structure), and what comes out.\n"
    "Ground everything in what you are given. Do not invent capabilities or components. If the "
    "mechanism genuinely isn't clear from the structure, say so plainly rather than inventing a "
    "flow. Be concise and concrete. Name the actual components."
)


def build_reviewer(model):
    from pydantic_ai import Agent
    return Agent(model, output_type=PurposeSynthesis, instructions=_INSTRUCTIONS, retries=2)


def _prompt(overview: dict, composition: dict, goal: str | None,
            deep_analysis: dict | None = None) -> str:
    lines = [f"Target: {overview.get('kind')}."]
    if overview.get("purpose"):
        lines += ["", f"Its package docstring says: \"{overview['purpose']}\""]
    if overview.get("entryPoints"):
        lines += ["", "Entry points: " + ", ".join(overview["entryPoints"])]
    lines += ["", "Components (name · role · capabilities · depends on):"]
    for c in composition.get("components", []):
        caps = ", ".join(list(c.get("capabilities", {}))[:6]) or "none observed"
        deps = ", ".join(c.get("dependsOn", [])) or "nothing internal"
        role = c.get("role") or "(no docstring)"
        lines.append(f"- {c['name']} ({c['moduleCount']} module(s)) · {role} · can: {caps} · "
                     f"depends on: {deps}")
    if goal:
        lines += ["", f"The reader's particular interest: {goal}. Weight the explanation toward it "
                  "if relevant, but still describe the whole."]
    completed = [run for run in (deep_analysis or {}).get("runs", [])
                 if run.get("status") == "completed"]
    if completed:
        lines += ["", "Focused Joern evidence (bounded index-selected subsets; never infer "
                  "cross-language flow):"]
        for run in completed:
            graph = (run.get("evidence") or {}).get("graph") or {}
            lines.append(f"- {run.get('sourceLanguage')} {run.get('mode')}: "
                         f"{len(graph.get('paths', []))} path(s), "
                         f"{len(graph.get('nodes', []))} normalized node(s)")
            nodes = {str(node.get("id")): node for node in graph.get("nodes", [])
                     if isinstance(node, dict)}
            for path in graph.get("paths", [])[:3]:
                codes = [str(nodes.get(str(identifier), {}).get("code") or "")
                         for identifier in path.get("nodes", [])]
                codes = [code for code in codes if code]
                lines.append(f"  relation={path.get('relation')}: " + " -> ".join(codes[:8]))
    lines += ["", "Write `purpose` and `how_it_works`."]
    return "\n".join(lines)


async def synthesize_purpose(overview: dict, composition: dict, *, goal=None, model=None,
                             deep_analysis=None, agent=None) -> PurposeSynthesis | None:
    """Synthesize the purpose + mechanism narrative, or None on any failure (graceful)."""
    if not composition.get("components"):
        return None
    agent = agent or build_reviewer(model)
    try:
        result = await agent.run(_prompt(overview, composition, goal, deep_analysis))
        return result.output
    except Exception:
        return None
