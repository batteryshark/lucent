"""Signature-pack reader and callee matcher.

Consumes the vendored ``parallax-signature-pack/v1`` callee pack (``source-callees.json``),
the judgment-free mapping from an observed callee string to a parallax ontology atom. lucent
reads it as *data*: the pack holds the meaning, this module holds the mechanics. The pack is a
verbatim copy of parallax's ``signatures/packs/source-callees.json`` (the source of record);
refresh it from there.

The matcher reproduces the pack's ``match_symbol`` modes exactly, so classification stays
consistent with the parallax reference. See the mode table in :func:`match_symbol`.
Observation *gates* (a file-scope text requirement that must hold for an atom to stand, e.g.
JS ``exec`` needs ``child_process`` in the file) are exposed for the observer to apply,
since only it has the file text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# The vendored parallax callee pack (the source of record), plus lucent's own Python-idiom
# supplement (stdlib idioms the reference pack does not cover). Both are read the same way.
_PACK_PATHS = (Path(__file__).with_name("source-callees.json"),
               Path(__file__).with_name("python-idioms.json"))
_SCHEMA_VERSION = "parallax-signature-pack/v1"


@dataclass(frozen=True)
class MatchRule:
    """One callee signature: match an extracted callee string to an atom."""
    id: str
    atom: str
    languages: tuple[str, ...]
    mode: str
    values: tuple[str, ...]
    case_sensitive: bool
    confidence: float
    summary: str
    priority: int
    order: int

    def applies_to(self, lang: str) -> bool:
        return lang in self.languages or "*" in self.languages


@dataclass(frozen=True)
class Gate:
    """An observation gate: for a given atom + language, the file must satisfy a text
    requirement, else the observation is dropped or downweighted. lucent honours the
    common ``any_text`` / ``drop`` / ``downweight`` forms the callee pack uses."""
    id: str
    atom: str
    languages: tuple[str, ...]
    any_text: tuple[str, ...]
    on_missing: str            # "drop" | "downweight" | "tag"
    downweight_multiplier: float

    def applies_to(self, atom: str, lang: str) -> bool:
        return atom == self.atom and (lang in self.languages or "*" in self.languages)


@dataclass(frozen=True)
class Hit:
    """A classification result: the atom a callee matched, with its confidence."""
    atom: str
    confidence: float
    summary: str
    rule_id: str


class SignaturePackError(ValueError):
    """Raised when the vendored signature pack is missing or malformed."""


# --- matching (mirrors parallax `signatures._matches`) ------------

def normalize(symbol: str, *, case_sensitive: bool = False) -> str:
    """Fold member separators (``::``, ``->``) to ``.``, and lowercase unless the rule is
    case-sensitive. This is the canonical form that both callee strings and pack values
    compare in."""
    out = symbol.replace("::", ".").replace("->", ".")
    return out if case_sensitive else out.lower()


def match_symbol(candidate: str, rule: MatchRule) -> bool:
    """True if ``candidate`` matches ``rule`` under its mode:

    * ``base``: the last dotted segment equals a value;
    * ``exact``: the whole normalized symbol equals a value;
    * ``suffix``: it ends with a value;
    * ``exact_or_suffix``: it equals a value or ends with ``.`` + value;
    * ``substring``: a value occurs anywhere;
    * ``regex``: any value pattern searches.
    """
    n = normalize(candidate, case_sensitive=rule.case_sensitive)
    values = rule.values if rule.case_sensitive else tuple(v.lower() for v in rule.values)
    mode = rule.mode
    if mode == "base":
        return n.split(".")[-1] in values
    if mode == "exact":
        return n in values
    if mode == "suffix":
        return any(n.endswith(v) for v in values)
    if mode == "exact_or_suffix":
        return any(n == v or n.endswith("." + v) for v in values)
    if mode == "substring":
        return any(v in n for v in values)
    if mode == "regex":
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        return any(re.search(v, n, flags) for v in rule.values)
    raise ValueError(f"unsupported match mode {mode!r} in {rule.id}")


# --- pack loading ----------------------------------------------------------

class Signatures:
    """Facade over the vendored callee pack: classify a callee, look up gates."""

    def __init__(self, rules: tuple[MatchRule, ...], gates: tuple[Gate, ...],
                 pack_id: str, version: str):
        self.rules = rules
        self.gates = gates
        self.pack_id = pack_id
        self.version = version

    @classmethod
    def load(cls) -> "Signatures":
        return _load_cached()

    def classify_callee(self, callee: str, lang: str) -> Hit | None:
        """First matching rule for ``callee`` in ``lang``, by (priority desc, pack order).
        Returns None when nothing matches, so an unclassified callee produces no atom."""
        applicable = [r for r in self.rules if r.applies_to(lang)]
        for rule in sorted(applicable, key=lambda r: (-r.priority, r.order)):
            if match_symbol(callee, rule):
                return Hit(rule.atom, rule.confidence, rule.summary, rule.id)
        return None

    def gate_for(self, atom: str, lang: str) -> Gate | None:
        for g in self.gates:
            if g.applies_to(atom, lang):
                return g
        return None

    def known_atoms(self) -> frozenset[str]:
        return frozenset(r.atom for r in self.rules)


def _load_pack(path: Path) -> tuple[tuple[MatchRule, ...], tuple[Gate, ...], str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise SignaturePackError(f"cannot read signature pack {path}: {e}") from e
    except json.JSONDecodeError as e:
        raise SignaturePackError(f"malformed signature pack {path}: {e}") from e
    if data.get("schema_version") != _SCHEMA_VERSION:
        raise SignaturePackError(
            f"{path}: unsupported schema_version {data.get('schema_version')!r}")

    rules: list[MatchRule] = []
    for i, row in enumerate(data.get("signatures", [])):
        if row.get("surface") != "callee" or "match" not in row:
            continue  # lucent reads only the callee surface
        m = row["match"]
        rules.append(MatchRule(
            id=str(row["id"]), atom=str(row["atom"]), languages=tuple(row["languages"]),
            mode=str(m["mode"]), values=tuple(str(v) for v in m["values"]),
            case_sensitive=bool(m.get("case_sensitive", False)),
            confidence=float(row["confidence"]), summary=str(row["summary"]),
            priority=int(row.get("priority", 0)), order=i,
        ))

    gates: list[Gate] = []
    for row in data.get("observation_gates", []):
        ctx = row.get("requires_context") or {}
        any_text = tuple(ctx.get("any_text") or ())
        if not any_text:
            continue  # lucent honours the any_text gate form the callee pack uses
        gates.append(Gate(
            id=str(row["id"]), atom=str(row["atom"]), languages=tuple(row["languages"]),
            any_text=any_text, on_missing=str(ctx.get("on_missing", "downweight")),
            downweight_multiplier=float(ctx.get("downweight_multiplier", 0.5)),
        ))
    if not rules:
        raise SignaturePackError(f"{path}: no callee signatures")
    return tuple(rules), tuple(gates), str(data["id"]), str(data["version"])


@lru_cache(maxsize=1)
def _load_cached() -> Signatures:
    """Load and cache the vendored packs (read-only; re-parsing them for every observed file
    would be wasteful). The parallax callee pack and lucent's Python-idiom supplement are
    merged into one rule set; each rule keeps its own priority, so classification order is
    deterministic across both. Safe to share across the run."""
    all_rules: list[MatchRule] = []
    all_gates: list[Gate] = []
    ids: list[str] = []
    offset = 0
    for path in _PACK_PATHS:
        if not path.is_file():
            continue
        rules, gates, pack_id, _version = _load_pack(path)
        # Re-base each pack's order so merged ties break by pack order then in-pack order.
        all_rules.extend(
            MatchRule(**{**r.__dict__, "order": r.order + offset}) for r in rules)
        all_gates.extend(gates)
        ids.append(pack_id)
        offset += len(rules) + 1000
    if not all_rules:
        raise SignaturePackError(f"no callee signatures under {_PACK_PATHS[0].parent}")
    return Signatures(tuple(all_rules), tuple(all_gates), "+".join(ids), _SCHEMA_VERSION)


__all__ = ["Signatures", "MatchRule", "Gate", "Hit", "SignaturePackError",
           "match_symbol", "normalize"]
