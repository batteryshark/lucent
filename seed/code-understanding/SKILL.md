---
name: code-understanding
capability: code-understanding
accepts: [tree, source/python, source/javascript, source/typescript, source/go, source/ruby, source/rust]
emits: [analysis/observations]
tier: read-only
run: scripts/run.sh
keywords: [parallax, deterministic, tree-sitter, ast, atoms, observations, taxonomy, static-analysis, source, exec, network, credentials, capability]
description: >-
  Deterministic code understanding: run the vendored parallax engine over a source
  tree and emit parallax-taxonomy observation atoms (EXEC.SHELL, EXEC.PROC, NETW.*,
  CRED.*, LOAD.*, FSYS.*, ARTF.URL, ...). tree-sitter parses the source into an AST
  and rules classify callees against the taxonomy signature packs; degrades to a
  regex fallback when tree-sitter isn't installed. The alternative to pure-LLM
  reading — goalpacks that want a reproducible, judgment-free inventory of what code
  *can do* request this instead. Output is `observations.json`, which re-enters the
  ledger for the brain to reason over.
---

# code-understanding — source tree → parallax observation atoms

The deterministic half of parallax "reading code as affordances". This skill runs
the vendored parallax engine (`parallax-goalpacks/engine/`, a shared repo-root
component) over a source tree and emits **judgment-free observation atoms** from the
parallax taxonomy — `EXEC.SHELL`, `EXEC.PROC`, `NETW.HTTP`, `CRED.READ`,
`LOAD.DYNAMIC`, `FSYS.WRITE`, `ARTF.URL`, and so on. No severity, no verdict: just a
reproducible inventory of what the code *can do*, which the goalpack's brain then
interprets.

## The engine path

```
engine.observe_report(target)
  -> inventory.build + source_containers.expand
  -> rules.run          (tree-sitter AST extraction; regex fallback without it)
  -> model.Observation atoms
  -> dataflow / callgraph
  -> report.build       -> observations.json
```

`tree-sitter` is a *library* parser (it never executes the target), so parsing
untrusted source is read-only. That is why this skill is tier `read-only`: the
runner auto-runs it without gating through the human channel.

## Install (own venv, heavy deps stay here)

The skill carries its **own** uv venv so tree-sitter never leaks into rekit:

```sh
scripts/setup.sh
```

`setup.sh` runs `uv venv` in the skill and installs
`tree-sitter==0.25.2`, `tree-sitter-language-pack==1.12.0`, `jsonschema>=4.18`
(the deps pinned by the upstream engine). The venv (`.venv/`) is gitignored.

The engine itself is the shared `parallax-goalpacks/engine/` package: `run.sh` puts
the repo root on `PYTHONPATH` so `import engine` resolves to it (no second copy).

## How rekit drives it

`scripts/run.sh <input> <out_dir>` activates the skill's venv, puts the repo root on
`PYTHONPATH`, and runs the wrapper:

```sh
scripts/observe.py <input> <out_dir>
```

which calls `engine.observe_report(<input>)` and writes `<out_dir>/observations.json`.

## Taxonomy resolution

The engine classifies extracted callees against parallax-taxonomy signature packs.
Resolution order (see `engine/paths.py`):

1. `PRLX_TAXONOMY_ROOT` / `PRLX_SOURCE_CALLEE_PACK` env (pinning hook), else
2. a sibling `parallax-taxonomy/` checkout, else
3. the **bundled** copy at `engine/taxonomy/` — a verbatim vendor of
   `parallax-taxonomy/signatures/`, so the skill is self-contained with no env set.

## Output

`<out_dir>/observations.json`, classified `analysis/observations`. Shape:

```json
{
  "target": "<input>",
  "astMode": "tree-sitter",      // or "regex-fallback"
  "counts": { "observations": 6, "byAtom": { "EXEC.SHELL": 3, ... } },
  "observations": [ { "atom": "EXEC.SHELL", "location": {...}, "evidence": {...} }, ... ],
  "report": { ... full engine scan-report ... }
}
```

The `observations` array carries the atoms; they re-enter the ledger so the
deterministic inventory drives the next loop round.
