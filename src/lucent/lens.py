"""The interpretation layer — reading judgment-free atoms and structure into findings.

Where ``observe.py`` records what code *can do* and ``structure.py`` records how it is
*wired*, this module supplies the judgment: it reads that shared substrate through four
lenses, each answering one question about the target, and never collapses them into a score.

    does        — what the code actually does (its capabilities).
    decides     — where behaviour forks at runtime (dispatch, entry points, config).
    brittle     — where it is fragile: opaque, remote-dependent, destructive, high-blast-radius.
    surprising  — mismatches: capability that doesn't fit a module's apparent role, orphans.

This is understanding, not security, so findings carry no "severity". A capability or a
decision point is just a fact about the code — it has no risk grade. Only *brittle* findings
carry a gradient, and it is **fragility**: how much this point complicates understanding or
change. Fragility is always kept separate from **confidence** (how sure the reading is). The
lens fires on ordinary code and names an operational fact plus what would disprove it — a map,
not an alarm. Findings are bounded and deduplicated so the report reads as a briefing.
"""

from __future__ import annotations

from collections import defaultdict

from lucent.atoms import atom_title, category_of, category_title

#: Fragility levels for brittle findings, low → high. Other lenses carry no rating.
FRAGILITY_ORDER = ["low", "medium", "high"]
_FRAG_RANK = {s: i for i, s in enumerate(FRAGILITY_ORDER)}

# Module base names that read as passive/structural — a capability here is a surprise.
_PASSIVE_ROLES = {
    "util", "utils", "helper", "helpers", "config", "conf", "settings", "constants",
    "const", "types", "typing", "schema", "schemas", "models", "model", "dto", "enums",
    "enum", "exceptions", "errors", "interfaces", "protocols", "dataclasses",
}
# External imports that mark a module as a command-line / argument-driven entry point.
_CLI_LIBS = {"argparse", "optparse", "click", "typer", "docopt", "fire"}
# Directories whose modules are not "orphans" worth flagging when nothing imports them.
_NONHUB_DIRS = {"test", "tests", "spec", "specs", "example", "examples", "sample",
                "samples", "docs", "scripts", "bin", "benchmarks", "bench"}


def conf_label(c: float) -> str:
    return "high" if c >= 0.75 else "medium" if c >= 0.45 else "low"


def _finding(lens, title, claim, confidence, *, fragility=None, module=None, composition=None,
             evidence=None, disproof=None, verify=None) -> dict:
    """A finding. ``fragility`` is set only for brittle findings (low/medium/high); the other
    lenses are descriptive and carry no rating. ``confidence`` (how sure the reading is) applies
    to all."""
    return {
        "lens": lens, "title": title, "claim": claim, "fragility": fragility,
        "confidence": round(confidence, 2), "conf_label": conf_label(confidence),
        "module": module, "composition": composition,
        "evidence": evidence or [], "disproof": disproof or [], "verify": verify or [],
    }


def _obs_ev(obs_list, limit=8):
    """Evidence entries citing observations, strongest first."""
    top = sorted(obs_list, key=lambda o: -o["confidence"])[:limit]
    return [{"obs": o["id"]} for o in top]


def _modules(obs_list):
    return sorted({o["module"] for o in obs_list})


# --- does: capability inventory --------------------------------------------

def _does(obs: list[dict]) -> list[dict]:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for o in obs:
        by_cat[category_of(o["atom"])].append(o)
    out = []
    for cat, group in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        atoms = sorted({o["atom"] for o in group})
        mods = _modules(group)
        titles = ", ".join(atom_title(a).lower() for a in atoms)
        out.append(_finding(
            "does", category_title(group[0]["atom"]),
            f"{len(group)} call site(s) across {len(mods)} file(s): {titles}.",
            max(o["confidence"] for o in group),
            composition=f"capability-{cat.lower()}", evidence=_obs_ev(group),
            disproof=["Every cited callee is a same-named local, method, or unrelated library "
                      "rather than the one this atom names — i.e. the capability is misidentified. "
                      "(Reachability is a *separate* question, not a disproof: dead code is latent "
                      "capability a dynamic or external caller can still invoke — see the "
                      "surprising lens.)"],
            verify=["Open a cited call site and confirm the callee resolves to the library the "
                    "atom names."],
        ))
    return out


# --- decides: where behaviour forks at runtime -----------------------------

def _decides(obs: list[dict], deps: dict) -> list[dict]:
    out = []
    dispatch = [o for o in obs if o["atom"] == "LOAD.IMPORT"]
    if dispatch:
        mods = _modules(dispatch)
        out.append(_finding(
            "decides", "Chooses what to load at runtime",
            f"{len(dispatch)} site(s) in {len(mods)} file(s) import a module or library "
            "selected at runtime — the concrete behaviour depends on that input.",
            max(o["confidence"] for o in dispatch),
            composition="runtime-dispatch", evidence=_obs_ev(dispatch),
            disproof=["The loaded name is a fixed constant, not derived from input or config."],
            verify=["Trace what value drives the dynamic import and who can influence it."],
        ))
    envi = [o for o in obs if o["atom"] == "ENVI.VAR"]
    if envi:
        mods = _modules(envi)
        out.append(_finding(
            "decides", "Reads environment configuration",
            f"{len(envi)} site(s) in {len(mods)} file(s) read environment variables; behaviour "
            "is decided by the environment the code runs in, not the source alone.",
            max(o["confidence"] for o in envi),
            composition="environment-driven", evidence=_obs_ev(envi),
            disproof=["The variables are read once into a validated config with defaults, not "
                      "branched on throughout."],
            verify=["List the variables read and check each has a sane default and validation."],
        ))
    external = deps.get("external", {})
    for mod in sorted(external):
        cli = sorted(set(t.split(".")[0] for t in external[mod]) & _CLI_LIBS)
        if cli:
            out.append(_finding(
                "decides", "Command-line entry point",
                f"`{mod}` builds its behaviour from command-line arguments ({', '.join(cli)}); "
                "it is a place the program decides what to do.",
                0.7, module=mod, composition="cli-entry",
                evidence=[{"path": mod, "note": f"imports {', '.join(cli)}"}],
                disproof=["The argument parser is a thin wrapper that always dispatches one way."],
                verify=["Read the argument definitions to see the behaviours it selects between."],
            ))
    return out


# --- brittle: operational fragility ----------------------------------------

def _brittle(obs: list[dict], deps: dict, failed: list[dict], module_langs: dict) -> list[dict]:
    out = []

    for f in failed:
        out.append(_finding(
            "brittle", f"Does not parse: {f['module']}",
            f"`{f['module']}` failed to parse ({f.get('error', 'syntax error')}); its behaviour, "
            "symbols, and dependencies are invisible to this analysis and to anything that imports it.",
            0.95, fragility="high", module=f["module"], composition="unparseable",
            evidence=[{"path": f["module"], "note": f.get("error", "")}],
            disproof=["The file is a template/partial/generated stub that is never imported or run."],
            verify=[f"Run `python -m py_compile {f['module']}` (or the language's parser)."],
        ))

    opaque = [o for o in obs if o["atom"] in ("LOAD.EVAL", "LOAD.DESER")]
    if opaque:
        out.append(_finding(
            "brittle", "Turns data into running code",
            f"{len(opaque)} site(s) evaluate code or deserialize untrusted objects "
            f"({', '.join(sorted({atom_title(o['atom']).lower() for o in opaque}))}); what actually "
            "runs is decided at runtime, so static review and tests cannot see it.",
            max(o["confidence"] for o in opaque), fragility="medium",
            composition="opaque-loading", evidence=_obs_ev(opaque),
            disproof=["The input is a trusted constant or an allowlisted, checksummed payload."],
            verify=["Trace the source of the evaluated/deserialized data to its origin."],
        ))

    netw = [o for o in obs if category_of(o["atom"]) == "NETW"]
    if netw:
        mods = _modules(netw)
        frag = "medium" if len(mods) >= 3 else "low"
        out.append(_finding(
            "brittle", "Depends on external network services",
            f"{len(netw)} network call site(s) across {len(mods)} file(s); this behaviour depends "
            "on remote services being reachable and returning what the code expects.",
            max(o["confidence"] for o in netw), fragility=frag,
            composition="external-control-dependency", evidence=_obs_ev(netw),
            disproof=["The destinations are local/loopback, or every call has a tested offline fallback."],
            verify=["Check timeout, retry, and failure handling at the cited call sites."],
        ))

    listeners = [o for o in obs if o["atom"] == "NETW.LISTEN"]
    if listeners:
        out.append(_finding(
            "brittle", "Exposes a network listener",
            f"{len(listeners)} site(s) bind a network listener; an inbound server surface widens "
            "what can reach the process and is a common source of operational and security risk.",
            max(o["confidence"] for o in listeners), fragility="medium",
            composition="inbound-surface", evidence=_obs_ev(listeners),
            disproof=["The listener binds only to loopback for local IPC, not an external interface."],
            verify=["Check the bind address, authentication, and exposure of each listener."],
        ))

    destructive = [o for o in obs if o["atom"] == "FSYS.DELETE"]
    if destructive:
        out.append(_finding(
            "brittle", "Removes files or directory trees",
            f"{len(destructive)} deletion site(s); a wrong or attacker-influenced path here is "
            "data loss, and the operation is hard to undo.",
            max(o["confidence"] for o in destructive), fragility="medium",
            composition="destructive-side-effect", evidence=_obs_ev(destructive),
            disproof=["Every deleted path is confined to a temp dir the code created itself."],
            verify=["Confirm each deleted path is validated and scoped before removal."],
        ))

    # High blast radius: internal modules many others depend on.
    dependents = deps.get("dependents", {})
    if dependents:
        ranked = sorted(dependents.items(), key=lambda kv: -len(kv[1]))
        threshold = max(3, len(module_langs) // 10)
        for mod, dents in ranked[:5]:
            if len(dents) < threshold:
                break
            frag = "medium" if len(dents) >= threshold * 2 else "low"
            out.append(_finding(
                "brittle", f"High blast radius: {mod}",
                f"`{mod}` is imported by {len(dents)} internal module(s); a change to its interface "
                "ripples across the codebase, so it is expensive and risky to touch.",
                0.8, fragility=frag, module=mod, composition="high-blast-radius",
                evidence=[{"path": d} for d in sorted(dents)[:10]],
                disproof=["The public surface is small and stable, or dependents only use a "
                          "narrow, well-tested part of it."],
                verify=["Check whether the widely-used surface has tests pinning its behaviour."],
            ))

    for cycle in _import_cycles(deps.get("dependsOn", {})):
        out.append(_finding(
            "brittle", "Import cycle",
            f"These modules import each other in a cycle: {' → '.join(cycle)} → {cycle[0]}. "
            "Cyclic imports are fragile to reorder, hard to test in isolation, and a common "
            "source of import-time errors.",
            0.85, fragility="medium", composition="import-cycle",
            evidence=[{"path": m} for m in cycle],
            disproof=["The cycle is broken at runtime by deferred (function-local) imports."],
            verify=["Confirm whether the imports are module-level or deferred inside functions."],
        ))
    return out


# --- surprising: mismatches ------------------------------------------------

_ACTIVE = {"EXEC", "NETW"}
_ACTIVE_ATOMS = {"LOAD.EVAL", "LOAD.DESER", "FSYS.DELETE"}


def _surprising(obs: list[dict], deps: dict, module_langs: dict) -> list[dict]:
    out = []
    by_mod: dict[str, list[dict]] = defaultdict(list)
    for o in obs:
        by_mod[o["module"]].append(o)

    for mod in sorted(by_mod):
        base = mod.rsplit("/", 1)[-1].removesuffix(".py").lower()
        if base not in _PASSIVE_ROLES:
            continue
        active = [o for o in by_mod[mod]
                  if category_of(o["atom"]) in _ACTIVE or o["atom"] in _ACTIVE_ATOMS]
        if active:
            caps = ", ".join(sorted({atom_title(o["atom"]).lower() for o in active}))
            out.append(_finding(
                "surprising", f"Active capability in a passive-looking module: {mod}",
                f"`{mod}` reads like a {base} module but {caps}. Capability hidden where a reader "
                "would not look for it is easy to miss when reasoning about the code.",
                max(o["confidence"] for o in active), module=mod,
                composition="role-capability-mismatch", evidence=_obs_ev(active),
                disproof=["The module's real role is broader than its name suggests; rename or "
                          "relocate would remove the surprise."],
                verify=["Confirm the capability belongs here rather than in a service/adapter module."],
            ))

    # Orphans: Python modules nothing internal imports (dead code, or an unmarked entry point).
    dependents = deps.get("dependents", {})
    depends_on = deps.get("dependsOn", {})
    if dependents or depends_on:
        py_mods = [m for m, lang in module_langs.items() if lang == "python"]
        orphans = []
        for m in sorted(py_mods):
            name = m.rsplit("/", 1)[-1]
            parts = set(m.split("/"))
            if name == "__init__.py" or name == "__main__.py":
                continue
            if parts & _NONHUB_DIRS:
                continue
            if m not in dependents:
                orphans.append(m)
        for m in orphans[:10]:
            out.append(_finding(
                "surprising", f"Imported by nothing: {m}",
                f"No module inside the target imports `{m}`. It is either an entry point, a "
                "plugin loaded dynamically, or dead code — worth knowing which.",
                0.55, module=m, composition="orphan-module",
                evidence=[{"path": m}],
                disproof=["It is an entry point, a plugin loaded by name, or imported only by "
                          "tests or an external consumer — reached, just not through a static "
                          "internal import."],
                verify=["Grep for the module name and check the packaging entry points."],
            ))
    return out


# --- import-cycle detection (Tarjan SCC over internal edges) ---------------

def _import_cycles(depends_on: dict[str, list[str]]) -> list[list[str]]:
    """Strongly-connected components of size > 1 (or self-loops) in the internal dependency
    graph — the import cycles. Deterministic order for a stable report."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = [0]
    sccs: list[list[str]] = []
    nodes = sorted(set(depends_on) | {d for v in depends_on.values() for d in v})

    import sys
    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))

    def strong(v: str):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in depends_on.get(v, []):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or (comp[0] in depends_on.get(comp[0], [])):
                sccs.append(sorted(comp))

    for n in nodes:
        if n not in index:
            strong(n)
    return sccs


def _reachability(reach: list[dict]) -> list[dict]:
    """Dead / unreachable / hard-to-reach code, split across the surprising lens (things that
    don't run, which is surprising) and the brittle lens (things reached only under contorted
    conditions, which are hard to test and reason about)."""
    out = []
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in reach:
        by_kind[r["kind"]].append(r)

    unreachable = by_kind.get("unreachable", [])
    if unreachable:
        mods = sorted({r["module"] for r in unreachable})
        out.append(_finding(
            "surprising", "Unreachable code",
            f"{len(unreachable)} statement(s) across {len(mods)} file(s) follow a return, raise, "
            "break, or exit in the same block, so they can never run — dead lines that mislead a "
            "reader about what the code does.",
            0.9, composition="unreachable-code",
            evidence=[{"path": r["module"], "line": r["lineno"], "note": r["detail"]}
                      for r in unreachable[:12]],
            disproof=["The 'terminal' statement is inside a branch that doesn't always return "
                      "(re-check the control flow)."],
            verify=["Open each cited line and confirm nothing can reach it."],
        ))

    guards = by_kind.get("constant-guard", [])
    if guards:
        out.append(_finding(
            "surprising", "Dead branch behind a constant guard",
            f"{len(guards)} branch(es) are gated on a constant-false test (`if False:`, `while 0:`); "
            "the body never executes — usually a disabled feature, a debug toggle, or left-behind code.",
            0.85, composition="constant-guarded",
            evidence=[{"path": r["module"], "line": r["lineno"], "note": r["detail"]}
                      for r in guards[:12]],
            disproof=["The guard constant is rewritten at runtime (rare, and a code smell in itself)."],
            verify=["Decide whether to delete the branch or restore the condition it once had."],
        ))

    dead = by_kind.get("dead-code", [])
    if dead:
        names = ", ".join(f"`{r['name']}`" for r in dead[:8])
        out.append(_finding(
            "surprising", "Private definitions nothing references",
            f"{len(dead)} module-private definition(s) ({names}) are defined but referenced nowhere "
            "in their own module — likely dead code, or a public API accessed only by name elsewhere.",
            0.6, composition="dead-definition",
            evidence=[{"path": r["module"], "line": r["lineno"], "note": f"{r['detail']} {r['name']}"}
                      for r in dead[:12]],
            disproof=["The name is invoked dynamically (getattr / globals() / importlib), "
                      "re-exported from the package, registered as a plugin or entry point, or "
                      "reached only by tests or an out-of-tree caller — any of which makes it "
                      "latent functionality, not dead code."],
            verify=["Grep the whole codebase (and its entry-point config) for the name before "
                    "removing it."],
        ))

    deep = by_kind.get("deep-nesting", [])
    if deep:
        deep.sort(key=lambda r: -int(r["detail"]))
        worst = int(deep[0]["detail"])
        out.append(_finding(
            "brittle", "Logic reached only in specific, deeply-nested cases",
            f"{len(deep)} function(s) nest conditions {worst} levels deep at the worst; code that "
            "deep runs only under that many stacked conditions, so it is hard to reach in a test "
            "and hard to hold in your head.",
            0.8, fragility="medium" if worst >= 6 else "low", composition="deep-nesting",
            evidence=[{"path": r["module"], "line": r["lineno"],
                       "note": f"{r['name']} — depth {r['detail']}"} for r in deep[:12]],
            disproof=["The nesting is a flat dispatch (e.g. a match/elif chain) that reads simply "
                      "despite the depth."],
            verify=["Check whether the deepest branch has a test that actually reaches it."],
        ))
    return out


def compose(obs: list[dict], deps: dict, failed: list[dict],
            module_langs: dict, reach: list[dict] | None = None) -> list[dict]:
    """Read the substrate through all four lenses into a bounded, deduplicated finding list."""
    findings: list[dict] = []
    findings += _does(obs)
    findings += _decides(obs, deps)
    findings += _brittle(obs, deps, failed, module_langs)
    findings += _surprising(obs, deps, module_langs)
    findings += _reachability(reach or [])
    return findings
