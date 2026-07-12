"""Assembling findings, atoms, and structure into one assessment — with an overview and a
compositional analysis.

This is lucent's analogue of unmask's ``build_assessment``, but where unmask ends in a
*disposition* (a security next-action), lucent ends in *understanding*. It projects the
ledger's findings and observations into a self-describing dict the report renders, and adds
two synthesis steps over the whole target:

* an **overview** — what the thing you pointed at *is*, overall, and what's in it;
* a **composition** — how it is built: its components, their capabilities, and how they depend
  on one another (the architecture, collapsed from the module reference graph).

This is understanding, not security: findings carry no severity. Only brittle findings carry a
*fragility* gradient; capabilities and decisions are just facts. Every finding's cited
observations are resolved to concrete loci with a few lines of source context.
"""

from __future__ import annotations

from pathlib import Path

from lucent._version import __version__
from lucent.atoms import atom_title, category_of, category_title
from lucent.lens import FRAGILITY_ORDER, _FRAG_RANK

ASSESSMENT_VERSION = "0.1.0"

_CONTEXT_LINES = 2
_MAX_LINE_CHARS = 220

_CONTRACT_NOTE = (
    "This is a code-understanding report: a judgment-free inventory of what the target can do "
    "(observation atoms), read through four lenses (does / decides / brittle / surprising). "
    "Capability is not accusation and absence is not a guarantee — an atom lucent did not "
    "observe may still be reachable through a path its extractors do not cover. This is "
    "understanding, not security: findings carry no severity. Only brittle findings carry a "
    "fragility rating (how much a point complicates understanding or change), always separate "
    "from confidence (how sure the reading is); every finding names what would disprove it.")


def _window_line(raw: str):
    return raw if len(raw) <= _MAX_LINE_CHARS else raw[:_MAX_LINE_CHARS] + "…"


def _snippet(abspath: str | None, line: int | None, match_text: str | None):
    """A few lines of source context around a locus, with the matched callee located for
    highlighting. Best-effort: unreadable file / no line → None."""
    if not abspath or not line or line < 1:
        return None
    try:
        text = Path(abspath).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    if line > len(lines):
        return None
    lo, hi = max(1, line - _CONTEXT_LINES), min(len(lines), line + _CONTEXT_LINES)
    out = []
    for n in range(lo, hi + 1):
        raw = lines[n - 1]
        col = None
        if n == line and match_text:
            idx = raw.find(match_text)
            if idx >= 0:
                col = [idx, idx + len(match_text)]
        out.append({"n": n, "text": _window_line(raw), "match": n == line, "col": col})
    return {"startLine": lo, "matchLine": line, "lines": out}


def _obs_to_dict(o: dict, file_map: dict) -> dict:
    ev = {"summary": o.get("summary"), "matchedText": o.get("evidence")}
    snip = _snippet(file_map.get(o["module"]), o.get("lineno"), o.get("evidence"))
    if snip:
        ev["snippet"] = snip
    return {
        "id": o["id"], "atom": o["atom"], "atomTitle": atom_title(o["atom"]),
        "method": o["method"], "confidence": o["confidence"],
        "location": {"path": o["module"], "line": o.get("lineno")}, "evidence": ev,
    }


def _top_categories(capabilities: dict, n: int) -> list[str]:
    by_cat: dict[str, int] = {}
    for atom, count in capabilities.items():
        by_cat[category_of(atom)] = by_cat.get(category_of(atom), 0) + count
    return [c for c, _ in sorted(by_cat.items(), key=lambda kv: -kv[1])[:n]]


def _max_fragility(findings) -> str | None:
    """Highest fragility among brittle findings (the only lens with a rating)."""
    fr = [f["fragility"] for f in findings if f["lens"] == "brittle" and f.get("fragility")]
    return max(fr, key=lambda s: _FRAG_RANK.get(s, 0)) if fr else None


# --- overview: what the target IS, overall ---------------------------------

def _component_of(path: str) -> str:
    """The top-level component a file belongs to — its first path segment, or ``(root)``."""
    parts = str(path).split("/")
    return parts[0] if len(parts) > 1 else "(root)"


def _entry_points(findings: list[dict], file_map: dict) -> list[str]:
    entries = {f["module"] for f in findings if f.get("composition") == "cli-entry" and f.get("module")}
    entries |= {p for p in file_map if p.rsplit("/", 1)[-1] == "__main__.py"}
    return sorted(entries)


def _first_sentence(text: str, maxlen: int = 240) -> str:
    """The first sentence of a docstring (a component's role), flattened and length-capped."""
    flat = " ".join((text or "").split())
    dot = flat.find(". ")
    s = flat[:dot + 1] if 0 < dot < maxlen else flat
    return s if len(s) <= maxlen else s[:maxlen].rsplit(" ", 1)[0] + "…"


def _first_paragraph(text: str, maxlen: int = 500) -> str:
    """The opening paragraph of a docstring (the stated purpose)."""
    para = " ".join((text or "").split("\n\n", 1)[0].split())
    return para if len(para) <= maxlen else para[:maxlen].rsplit(" ", 1)[0] + "…"


def _root_docstring(docstrings: dict, file_map: dict) -> str | None:
    """The target's own top-level statement of purpose: the root package ``__init__.py``
    docstring, or a single file's module docstring."""
    if "__init__.py" in docstrings:
        return docstrings["__init__.py"]
    if len(file_map) == 1:
        only = next(iter(file_map))
        return docstrings.get(only)
    return None


def _component_role(name: str, modules: list[str], docstrings: dict) -> str | None:
    """A component's role, in its own words: its ``__init__.py`` docstring, else the first of
    its modules that has one."""
    init = f"{name}/__init__.py" if name != "(root)" else "__init__.py"
    if init in docstrings:
        return _first_sentence(docstrings[init])
    for m in modules:
        if m in docstrings:
            return _first_sentence(docstrings[m])
    return None


def _infer_kind(summary: dict, findings: list[dict], file_map: dict) -> str:
    langs = summary["languages"]
    primary = next(iter(langs), "code")
    code_langs = {k: v for k, v in langs.items() if k not in ("sql", "html")}
    names = [p.rsplit("/", 1)[-1] for p in file_map]
    has_cli = any(f.get("composition") == "cli-entry" for f in findings) or "__main__.py" in names
    has_pkg = "__init__.py" in names
    if summary["fileCount"] == 1:
        return f"a single {primary} file"
    if len(code_langs) > 1:
        base = "a multi-language codebase"
    elif has_pkg:
        base = f"a {primary} package"
    else:
        base = f"a {primary} codebase"
    return base + " with a command-line entry point" if has_cli else base


def _overview(summary: dict, composition: dict, findings: list[dict],
              deps: dict, file_map: dict, docstrings: dict) -> dict:
    """The overall summary: what the target is *for* (its own stated purpose), what it is, how
    it's organized, what it can do, and where the change-risk sits — the "what did I point lucent
    at, and what's it for?" read."""
    kind = _infer_kind(summary, findings, file_map)
    purpose = _root_docstring(docstrings, file_map)
    purpose = _first_paragraph(purpose) if purpose else None
    files, mods, syms = summary["fileCount"], summary["moduleCount"], summary["symbolCount"]
    langs = ", ".join(summary["languages"])
    parts: list[str] = []
    scope = f"{files} file(s)" + (f", {mods} Python module(s), {syms} symbol(s)" if mods else "")
    parts.append(f"This is {kind} — {scope} ({langs}).")

    comps = composition["components"]
    if len(comps) > 1:
        named = ", ".join(f"`{c['name']}`" for c in comps[:6])
        more = "" if len(comps) <= 6 else f", and {len(comps) - 6} more"
        parts.append(f"It is organized into {len(comps)} components: {named}{more}.")

    caps = [category_title(a) for a in _top_categories(summary["capabilities"], 5)]
    if caps:
        parts.append("Across the codebase it can: " + ", ".join(c.lower() for c in caps) + ".")
    else:
        parts.append("It reaches for nothing outward that lucent can see (no exec, network, "
                     "filesystem, or dynamic-loading call sites) — self-contained by that measure.")

    entries = _entry_points(findings, file_map)
    if entries:
        parts.append("Entry point(s): " + ", ".join(f"`{e}`" for e in entries[:4]) + ".")

    brittle = sorted((f for f in findings if f["lens"] == "brittle"),
                     key=lambda f: -_FRAG_RANK.get(f.get("fragility"), 0))
    if brittle:
        parts.append("Most fragile points: " + "; ".join(f["title"] for f in brittle[:3]) + ".")

    dependents = deps.get("dependents", {})
    if dependents:
        hub, dents = max(dependents.items(), key=lambda kv: len(kv[1]))
        parts.append(f"`{hub}` is the most-depended-on module ({len(dents)} internal importers) — "
                     "where a change ripples furthest.")
    return {"kind": kind, "purpose": purpose, "text": " ".join(parts), "entryPoints": entries}


# --- composition: how it is built ------------------------------------------

def _composition(file_map: dict, observations: list[dict], deps: dict,
                 docstrings: dict) -> dict:
    """Collapse the file inventory and module reference graph to the *component* level (the
    top-level directories): each component's role (in its own words), size, aggregate
    capabilities, and which components depend on which. This is the architecture the module
    graph implies."""
    from collections import Counter, defaultdict

    atoms_by_module: dict[str, list[str]] = defaultdict(list)
    for o in observations:
        atoms_by_module[o["module"]].append(o["atom"])

    comp_files: dict[str, list[str]] = defaultdict(list)
    for f in sorted(file_map):
        comp_files[_component_of(f)].append(f)

    comps: dict[str, dict] = {}
    for name, fs in comp_files.items():
        caps: Counter = Counter()
        for f in fs:
            caps.update(atoms_by_module.get(f, []))
        comps[name] = {"name": name, "moduleCount": len(fs), "modules": fs,
                       "role": _component_role(name, fs, docstrings),
                       "capabilities": dict(caps.most_common()),
                       "dependsOn": set(), "dependents": set()}

    edges: Counter = Counter()
    for e in deps.get("internalEdges", []):
        sc, dc = _component_of(e["src"]), _component_of(e["dst"])
        if sc != dc and sc in comps and dc in comps:
            edges[(sc, dc)] += 1
            comps[sc]["dependsOn"].add(dc)
            comps[dc]["dependents"].add(sc)

    comp_list = [{**c, "dependsOn": sorted(c["dependsOn"]), "dependents": sorted(c["dependents"])}
                 for c in sorted(comps.values(), key=lambda c: (-c["moduleCount"], c["name"]))]
    edge_list = [{"src": s, "dst": d, "count": n}
                 for (s, d), n in sorted(edges.items(), key=lambda kv: (-kv[1], kv[0]))]
    # Foundations: components nothing internal depends *on* nothing (leaves) vs depended-on hubs.
    foundations = sorted((c["name"] for c in comp_list if c["dependents"] and not c["dependsOn"]))
    return {"components": comp_list, "edges": edge_list, "foundations": foundations}


def build_assessment(*, target_path, findings, observations, deps, summary,
                     file_map, extraction_mode, coverage, reviews=None, goal=None,
                     docstrings=None) -> dict:
    """Project findings + observations + structure into the assessment dict. When ``reviews``
    (the optional agentic overlay) are present, each finding is annotated with its review and a
    run-level review block is attached. ``goal`` is the reader's optional question, surfaced in
    the overview and used to collect goal-relevant findings from the reviews."""
    obs_dicts = {o["id"]: _obs_to_dict(o, file_map) for o in observations}

    cited, seen = [], set()
    for f in findings:
        for ev in f.get("evidence", []):
            oid = ev.get("obs") if isinstance(ev, dict) else None
            if oid and oid in obs_dicts and oid not in seen:
                seen.add(oid)
                cited.append(obs_dicts[oid])

    review_overlay = None
    if reviews:
        from lucent.review.adjudicate import build_review_overlay
        model = next((r.get("model") for r in reviews if r.get("model")), None)
        review_overlay = build_review_overlay(reviews, model=model, goal=goal)
        by_id = {r["finding_id"]: r for r in reviews}
        for f in findings:                       # annotate each finding with its review
            r = by_id.get(f["id"])
            if r:
                f["review"] = r

    by_lens = {lens: sum(1 for f in findings if f["lens"] == lens)
               for lens in ("does", "decides", "brittle", "surprising")}
    docstrings = docstrings or {}
    composition = _composition(file_map, observations, deps, docstrings)
    summary = {**summary, "findingCount": len(findings), "byLens": by_lens,
               "componentCount": len(composition["components"]),
               "highestFragility": _max_fragility(findings),
               "reviewedCount": len(reviews) if reviews else 0}
    overview = _overview(summary, composition, findings, deps, file_map, docstrings)

    return {
        "schemaVersion": ASSESSMENT_VERSION,
        "kind": "codebase-understanding",
        "tool": {"name": "lucent", "version": __version__},
        "target": {"path": str(target_path)},
        "goal": goal,
        "overview": overview,
        "composition": composition,
        "synopsis": {"text": overview["text"], "author": "lucent"},   # one-line lead for the CLI
        "summary": summary,
        "review": review_overlay,
        "findings": findings,
        "observations": cited,
        "dependencies": deps,
        "coverage": {**coverage, "extractionMode": extraction_mode,
                     "notes": [
                         f"Non-Python extraction backend: {extraction_mode}. "
                         "Without the tree-sitter language pack, non-Python files fall back to a "
                         "lower-fidelity regex callee scan.",
                         "The dependency graph and symbol inventory are Python-only; other "
                         "languages are observed for behaviour but not structurally linked.",
                     ]},
        "contract": {"note": _CONTRACT_NOTE},
    }
