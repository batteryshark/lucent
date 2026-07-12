"""Python structural layer: symbols and the internal reference graph.

observe.py reads behaviour across every language. This module reads structure for Python
specifically: the functions, classes, methods, and imports a module defines, and how imports
resolve into a directed dependency graph over the target's own modules. It is pure stdlib
``ast``, so a Python target gets its full structural map with no heavy dependencies.

This is Python-only by nature (dotted module names, ``from .x import y`` semantics). For a
non-Python target, lucent reports behaviour but omits this structural graph. The omission is a
documented scope limit rather than an accidental gap.
"""

from __future__ import annotations

import ast
from pathlib import Path


def extract_symbols(tree: ast.Module) -> tuple[list[tuple[str, str, int, str | None]], list[dict]]:
    """``(defs, imports)``: top-level functions and classes plus their methods, and the import
    targets. Each import dict carries enough structure for the resolver to link it back to an
    internal module: the ``module`` it names, the ``imported`` leaf, and the relative
    ``level`` (leading-dot count). ``target`` is the flat dotted form kept for the symbol."""
    defs: list[tuple[str, str, int, str | None]] = []
    imports: list[dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append((node.name, "function", node.lineno, None))
        elif isinstance(node, ast.ClassDef):
            defs.append((node.name, "class", node.lineno, None))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.append((sub.name, "method", sub.lineno, node.name))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.append({"name": a.asname or a.name, "lineno": node.lineno,
                                "target": a.name, "module": a.name, "imported": None, "level": 0})
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                target = f"{mod}.{a.name}" if mod else a.name
                imports.append({"name": a.asname or a.name, "lineno": node.lineno,
                                "target": target, "module": mod, "imported": a.name,
                                "level": node.level or 0})
    return defs, imports


# --- reference resolution: dotted import targets to internal module rel paths ---

def module_dotted(rel: str) -> str:
    """A module's importable dotted name ('' for a root-package ``__init__``)."""
    p = Path(rel)
    parts = list(p.with_suffix("").parts) if p.suffix == ".py" else list(p.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_module_index(module_rels: list[str], root_pkg: str) -> dict[str, str]:
    """Map every internal module's dotted name to its rel path, so an import can resolve to
    the module it names. Each module is also registered under the top-package prefix (the
    scanned directory's name) so absolute self-imports (``import pkg.sub``) resolve too."""
    index: dict[str, str] = {}
    for rel in module_rels:
        dotted = module_dotted(rel)
        index.setdefault(dotted, rel)
        if root_pkg:
            index.setdefault(f"{root_pkg}.{dotted}" if dotted else root_pkg, rel)
    return index


def _relative_base(src_rel: str, level: int) -> str:
    """Dotted package a relative import resolves against: at level 1 it is the module's own
    package, and each extra dot ascends one more."""
    dotted = module_dotted(src_rel)
    parts = dotted.split(".") if dotted else []
    if Path(src_rel).name != "__init__.py" and parts:
        parts = parts[:-1]                 # a module resolves relative to its container
    up = level - 1
    if up > 0:
        parts = parts[:-up] if up <= len(parts) else []
    return ".".join(parts)


def resolve_import(index: dict[str, str], src_rel: str, imp: dict) -> tuple[str | None, str]:
    """``(dst_rel, resolved_dotted)``. ``dst_rel`` is the internal module the import names, or
    None when it points outside the target. Tries the submodule form (``from pkg import mod``)
    before the module form (``from mod import name``)."""
    module, imported, level = imp["module"], imp["imported"], imp["level"]
    if level:
        base = _relative_base(src_rel, level)
        prefix = f"{base}.{module}" if (base and module) else (module or base)
    else:
        prefix = module or ""
    candidates: list[str] = []
    if prefix and imported:
        candidates.append(f"{prefix}.{imported}")
    if prefix:
        candidates.append(prefix)
    if not prefix and imported:            # `from . import x` at the package root
        candidates.append(imported)
    for c in candidates:
        if c in index:
            return index[c], c
    return None, (candidates[0] if candidates else imp["target"])
