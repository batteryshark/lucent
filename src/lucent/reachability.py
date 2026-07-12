"""Reachability analysis: dead, unreachable, and hard-to-reach code (Python).

Some of the most useful things to know about a codebase are the parts that do not run, or run
only under contorted conditions: statements after a ``return`` that can never execute, branches
behind a constant guard, private helpers nothing calls, and logic buried so deep in nested
conditions it is only reached in very specific cases. These are judgment-free structural facts,
exactly lucent's kind of observation. They feed the ``surprising`` lens (dead and unreachable
code) and the ``brittle`` lens (hard-to-reach code).

Pure-stdlib ``ast``, intra-module and conservative by design: it reports what it can prove from
one module's syntax, and prefers silence to a false "this is dead", since a false positive is
worse than saying nothing. Python-only, like the rest of the structural layer.
"""

from __future__ import annotations

import ast
from collections import Counter

#: Nesting depth (of if/for/while/with/try) at or above which a statement is "hard to reach",
#: meaning it is only entered under this many stacked conditions. 5 keeps it to genuinely deep
#: logic.
_DEEP_THRESHOLD = 5
_NESTERS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _callee_name(func: ast.expr) -> str:
    parts: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        parts.reverse()
        return ".".join(parts)
    return ""


def _is_terminal(stmt: ast.stmt) -> bool:
    """A statement after which control cannot fall through to the next statement."""
    if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        return _callee_name(stmt.value.func) in ("sys.exit", "os._exit", "exit", "quit", "os.abort")
    return False


def _falsy_guard(test: ast.expr) -> str | None:
    """The literal a constant-false guard tests on (``if False``/``if 0``/``while None``), or None."""
    if isinstance(test, ast.Constant) and not bool(test.value):
        return repr(test.value)
    return None


def _child_blocks(stmt: ast.stmt):
    for field in ("body", "orelse", "finalbody"):
        block = getattr(stmt, field, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            yield block
    for handler in getattr(stmt, "handlers", []) or []:
        yield handler.body


def _max_nesting(func: ast.AST) -> tuple[int, int]:
    """(max depth, line of the deepest nester) of stacked compound statements inside ``func``,
    not counting nested function/class scopes (they get measured on their own)."""
    best = [0, getattr(func, "lineno", 0)]

    def rec(stmts, depth):
        for s in stmts:
            if isinstance(s, _DEFS):
                continue
            if isinstance(s, _NESTERS):
                nd = depth + 1
                if nd > best[0]:
                    best[0], best[1] = nd, s.lineno
                for block in _child_blocks(s):
                    rec(block, nd)
            else:
                for block in _child_blocks(s):
                    rec(block, depth)

    rec(func.body, 0)
    return best[0], best[1]


def _used_identifiers(tree: ast.Module) -> Counter:
    """How often each identifier is referenced (as a name or an attribute), so a definition
    referenced nowhere can be spotted. A module-private def's own header is not counted as a
    reference."""
    c: Counter = Counter()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            c[n.id] += 1
        elif isinstance(n, ast.Attribute):
            c[n.attr] += 1
    return c


def _dunder_all(tree: ast.Module) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                return {e.value for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def analyze(tree: ast.Module) -> list[dict]:
    """Reachability facts for one module, as flat rows ``{kind, name, lineno, detail}``:

      * ``unreachable``:    a statement follows a return/raise/break/exit in the same block.
      * ``constant-guard``: a branch is gated on a constant-false test (``if False:``).
      * ``deep-nesting``:   a function nests compound statements at or above the deep threshold.
      * ``dead-code``:      a module-private def is referenced nowhere in its module.
    """
    rows: list[dict] = []

    def scan(stmts, func):
        for i, s in enumerate(stmts):
            if _is_terminal(s) and i + 1 < len(stmts):
                rows.append({"kind": "unreachable", "name": func, "lineno": stmts[i + 1].lineno,
                             "detail": f"after {type(s).__name__.lower()}"})
                break
        for s in stmts:
            g = _falsy_guard(s.test) if isinstance(s, (ast.If, ast.While)) else None
            if g is not None:
                rows.append({"kind": "constant-guard", "name": func, "lineno": s.lineno,
                             "detail": f"{type(s).__name__.lower()} {g}"})
            inner = s.name if isinstance(s, _FUNCS) else func
            for block in _child_blocks(s):
                scan(block, inner)

    scan(tree.body, "<module>")

    for node in ast.walk(tree):
        if isinstance(node, _FUNCS):
            depth, line = _max_nesting(node)
            if depth >= _DEEP_THRESHOLD:
                rows.append({"kind": "deep-nesting", "name": node.name, "lineno": line,
                             "detail": str(depth)})

    private = [(n.name, type(n).__name__.lower().replace("def", ""), n.lineno) for n in tree.body
               if isinstance(n, _DEFS) and n.name.startswith("_") and not n.name.startswith("__")]
    if private:
        used = _used_identifiers(tree)
        exported = _dunder_all(tree)
        for name, kind, line in private:
            if name not in exported and used.get(name, 0) == 0:
                rows.append({"kind": "dead-code", "name": name, "lineno": line,
                             "detail": kind or "definition"})
    return rows
