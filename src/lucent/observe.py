"""The observation engine: turns source into judgment-free atoms, across every language it
can parse.

For each source file lucent extracts the *callees* (the things the code calls) and
classifies them against the vendored parallax callee pack (``signatures/``). Each match
becomes an :class:`Observation` atom: "this file can do X, here is the call site, here is how
sure we are." It passes no judgment: the lenses interpret, and this module only reports.

Two extraction backends sit behind one interface:

* **Python**: pure-stdlib ``ast``. Import aliases resolve to the canonical dotted callee
  (``from subprocess import run as r; r()`` becomes ``subprocess.run``), which the pack's
  substring rules match precisely. It needs no heavy dependencies, so a Python target is
  covered without installing the optional extras.
* **Everything else**: tree-sitter via ``tree-sitter-language-pack`` (the optional ``parse``
  extra). It falls back to a generic regex when a grammar or tree-sitter itself is
  unavailable. Both take the same callee-string-to-pack path. :func:`extraction_mode` reports
  which backend a run used, so the run records its own fidelity.

The languages lucent can observe are exactly those the tree-sitter language pack grammars
cover, plus Python natively.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from lucent.signatures import Signatures


@dataclass
class Observation:
    """One atom observed at a call site. ``method`` records how it was seen
    (``callee-python-ast``, ``callee-tree-sitter``, or ``callee-regex``), which captures the
    extraction fidelity. ``evidence`` is the callee text that fired the rule."""
    atom: str
    confidence: float
    method: str
    path: str
    line: int
    summary: str
    evidence: str
    rule_id: str
    id: str | None = None
    relationships: list[dict] = field(default_factory=list)

    def key(self) -> tuple:
        """Stable identity for dedup: one atom per (file, line, rule, callee)."""
        return (self.atom, self.path, self.line, self.rule_id, self.evidence)


# --- language detection ----------------------------------------------------

#: file extension / name -> canonical language (the pack's language codes).
_LANG_BY_EXT: dict[str, str] = {
    ".py": "python", ".pyw": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".cs": "csharp", ".rb": "ruby", ".php": "php", ".pl": "perl", ".pm": "perl",
    ".lua": "lua", ".r": "r", ".scala": "scala", ".swift": "swift",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ps1": "powershell", ".psm1": "powershell",
    ".sql": "sql", ".groovy": "groovy", ".hs": "haskell", ".ex": "elixir", ".exs": "elixir",
    ".m": "objc", ".mm": "objc", ".vb": "vb", ".hcl": "hcl", ".tf": "hcl",
    ".bat": "batch", ".cmd": "batch", ".applescript": "applescript", ".html": "html", ".htm": "html",
}
_LANG_BY_NAME: dict[str, str] = {
    "dockerfile": "dockerfile", "makefile": "make", "gnumakefile": "make",
}


def language_for(path: str) -> str | None:
    """The canonical language for a path, or None if lucent has no extractor for it."""
    p = Path(path)
    name = p.name.lower()
    if name in _LANG_BY_NAME:
        return _LANG_BY_NAME[name]
    if p.suffix.lower() == ".mk":
        return "make"
    return _LANG_BY_EXT.get(p.suffix.lower())


def source_extensions() -> frozenset[str]:
    return frozenset(_LANG_BY_EXT)


# --- tree-sitter backend (optional; multi-language) ------------------------

_GRAMMAR = {"shell": "bash"}          # canonical language -> tree-sitter grammar name
_TUNED_CALL_NODE = {"javascript": "call_expression", "typescript": "call_expression",
                    "tsx": "call_expression", "python": "call"}
_GENERIC_CALL_KINDS = {
    "call_expression", "call", "method_invocation", "invocation_expression",
    "function_call_expression", "member_call_expression", "scoped_call_expression",
    "function_call", "macro_invocation", "message_expression", "command",
    "command_name", "method_call", "object_creation_expression", "new_expression",
    "command_invocation",
}
_TS_TRIED = False
_TS_OK = False
_PARSERS: dict[str, object] = {}


def ts_available() -> bool:
    global _TS_TRIED, _TS_OK
    if not _TS_TRIED:
        _TS_TRIED = True
        try:
            import tree_sitter_language_pack  # noqa: F401
            _TS_OK = True
        except Exception:
            _TS_OK = False
    return _TS_OK


def extraction_mode() -> str:
    """The best available non-Python backend: ``tree-sitter`` or ``regex-fallback``.
    (Python is always AST-extracted regardless.)"""
    return "tree-sitter" if ts_available() else "regex-fallback"


def _parser(grammar: str):
    if grammar not in _PARSERS:
        from tree_sitter_language_pack import get_parser
        _PARSERS[grammar] = get_parser(grammar)
    return _PARSERS[grammar]


def _node_text(n, data: bytes) -> str:
    return data[n.start_byte:n.end_byte].decode("utf-8", "replace")


def _callee_text(node, data: bytes) -> str:
    """The called expression's text (receiver-qualified where the grammar exposes it),
    e.g. ``Net::HTTP.get``, ``runtime.exec``, ``child_process.exec``."""
    for fld in ("function", "name", "callee", "method", "constructor", "command_name"):
        c = node.child_by_field_name(fld)
        if c is not None:
            return _node_text(c, data).strip().splitlines()[0]
    raw = _node_text(node, data).strip().split("(", 1)[0].split("{", 1)[0]
    return raw.splitlines()[0].strip() if raw else ""


def _extract_calls_ts(src: str, lang: str) -> list[tuple[str, int]] | None:
    """Tree-sitter callee extraction, or None if unavailable for this language."""
    if not ts_available():
        return None
    grammar = _GRAMMAR.get(lang, lang)
    try:
        parser = _parser(grammar)
    except Exception:
        return None            # no grammar for this language -> caller falls back to regex
    want = {_TUNED_CALL_NODE[lang]} if lang in _TUNED_CALL_NODE else _GENERIC_CALL_KINDS
    try:
        data = src.encode("utf-8")
        tree = parser.parse(data)
        out: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in want:
                callee = _callee_text(node, data)
                line = node.start_point[0] + 1
                if callee and (callee, line) not in seen:
                    seen.add((callee, line))
                    out.append((callee, line))
            stack.extend(node.children)
        return out
    except Exception:
        return None


_CALL_RE = re.compile(r"([A-Za-z_$][\w$]*(?:\s*[.:]{1,2}\s*[A-Za-z_$][\w$]*)*)\s*\(")


def _extract_calls_regex(src: str, lang: str) -> list[tuple[str, int]]:
    """Generic fallback: ``identifier(.member)*`` immediately followed by ``(``. Lower
    fidelity, so it is used only where a grammar (or tree-sitter) isn't available."""
    out: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for i, raw in enumerate(src.splitlines(), start=1):
        for m in _CALL_RE.finditer(raw):
            callee = re.sub(r"\s+", "", m.group(1))
            if callee and (callee, i) not in seen:
                seen.add((callee, i))
                out.append((callee, i))
    return out


# --- python backend (pure-stdlib ast, alias-resolved) ----------------------

def _import_bindings(tree: ast.Module) -> dict[str, str]:
    """Local name -> canonical dotted target, from the module's imports. Lets an aliased
    or ``from``-imported call resolve to the canonical callee the pack matches:
    ``import subprocess as sp`` binds ``sp -> subprocess``; ``from os import getenv`` binds
    ``getenv -> os.getenv``."""
    binds: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    binds[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    binds.setdefault(top, top)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                 # relative import: an internal module, not a pack target
                continue
            mod = node.module or ""
            for a in node.names:
                target = f"{mod}.{a.name}" if mod else a.name
                binds[a.asname or a.name] = target
    return binds


def _callee_dotted(func: ast.expr) -> str | None:
    """The dotted source form of a call's function expression (``os.path.join``), or None
    when the head is not a plain name (e.g. ``get_client().post``, which cannot be resolved
    statically)."""
    parts: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    parts.reverse()
    return ".".join(parts)


def _resolve(dotted: str, binds: dict[str, str]) -> str:
    """Rewrite a dotted callee's head through the import bindings, so it reads as the
    canonical target the pack knows."""
    head, _, rest = dotted.partition(".")
    base = binds.get(head)
    if base is None:
        return dotted
    return f"{base}.{rest}" if rest else base


# Distinctive pathlib instance methods, matched even on a local receiver. Unlike generic
# names (``append``, ``get``, ``remove``), these read as file I/O wherever they appear, so a
# bare-method match on them is safe against the local-variable false positives the receiver
# gate exists to prevent (``requests = []; requests.append(...)``). ``unlink`` is already an
# FSYS.DELETE base value in the parallax pack; the rest are covered by the lucent supplement.
_PY_DISTINCTIVE_METHODS = frozenset({
    "write_text", "write_bytes", "read_text", "read_bytes", "unlink", "mkdir"})


def _extract_calls_python(tree: ast.Module) -> list[tuple[str, int]]:
    """Callees the pack can be trusted against, from real import facts.

    * A *qualified* call (``x.method``) is emitted only when ``x`` is an imported module.
      Otherwise ``x`` is a local or ``self``, and a library-name substring match on it is a
      false positive the generic tree-sitter path can't rule out.
    * A *bare* call (``eval(...)``) is always emitted; the pack keys those on the builtin name.
    * A *distinctive pathlib method* (``p.write_text()``, ``Path(x).read_text()``) is emitted
      as its bare method name on any receiver, since the method name alone is strong evidence.
    * ``os.environ[...]`` subscripts are emitted as ``os.environ`` (an env read the callee
      surface would otherwise miss, since it is not a call).
    """
    binds = _import_bindings(tree)
    out: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()

    def add(callee: str, line: int) -> None:
        if callee and (callee, line) not in seen:
            seen.add((callee, line))
            out.append((callee, line))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            line = getattr(node.func, "lineno", node.lineno)
            dotted = _callee_dotted(node.func)
            if dotted and ("." not in dotted or dotted.split(".", 1)[0] in binds):
                add(_resolve(dotted, binds), line)      # trusted: bare name or imported receiver
            elif isinstance(node.func, ast.Attribute) and node.func.attr in _PY_DISTINCTIVE_METHODS:
                add(node.func.attr, line)               # distinctive pathlib method, any receiver
        elif isinstance(node, ast.Subscript):
            base = _callee_dotted(node.value)           # e.g. os.environ['X'] -> "os.environ"
            if base and "." in base and base.split(".", 1)[0] in binds:
                add(_resolve(base, binds), getattr(node, "lineno", 0))
    return out


# --- the observer ----------------------------------------------------------

def _extract_calls(text: str, lang: str, py_tree: ast.Module | None) -> tuple[list[tuple[str, int]], str]:
    """(calls, method): calls are (callee, line); method records the backend used."""
    if lang == "python":
        tree = py_tree
        if tree is None:
            try:
                tree = ast.parse(text)
            except SyntaxError:
                return [], "callee-python-ast"
        return _extract_calls_python(tree), "callee-python-ast"
    ts = _extract_calls_ts(text, lang)
    if ts is not None:
        return ts, "callee-tree-sitter"
    return _extract_calls_regex(text, lang), "callee-regex"


def observe_source(rel: str, text: str, lang: str, *, sigs: Signatures | None = None,
                   py_tree: ast.Module | None = None) -> list[Observation]:
    """Observe one source file: extract callees, classify against the pack, apply gates,
    dedup. ``py_tree`` lets a Python caller pass an already-parsed AST so the file is not
    parsed twice (once for structure, once here)."""
    sigs = sigs or Signatures.load()
    calls, method = _extract_calls(text, lang, py_tree)
    out: dict[tuple, Observation] = {}
    for callee, line in calls:
        hit = sigs.classify_callee(callee, lang)
        if hit is None:
            continue
        confidence = hit.confidence
        gate = sigs.gate_for(hit.atom, lang)
        if gate is not None and not any(t in text for t in gate.any_text):
            if gate.on_missing == "drop":
                continue
            if gate.on_missing == "downweight":
                confidence = round(confidence * gate.downweight_multiplier, 3)
        obs = Observation(atom=hit.atom, confidence=confidence, method=method, path=rel,
                          line=line, summary=hit.summary, evidence=callee, rule_id=hit.rule_id)
        out.setdefault(obs.key(), obs)      # first hit at a key wins (dedup)
    return list(out.values())
