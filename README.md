# lucent

![Lucent: a retro robot inspector illuminating the hidden workings of a machine](assets/lucent-logo-480.png)

*Figure out a codebase, as a ledgered investigation.*

lucent reads a target and produces a coverage-guaranteed **understanding** of it. It records
what every source file can do, observed across every language its parser supports (Go,
JavaScript, TypeScript, Rust, Ruby, shell, and the rest of the tree-sitter grammars). For
Python it also maps how the modules are wired together. Then it interprets both through four
lenses. Every file is accounted for, and the run is durable and resumable through a per-run
SQLite ledger.

Behaviour observation is language-agnostic. The deeper *structural* layer (the reference graph,
reachability, symbol inventory, and docstring-derived purpose) is Python-only for now. A scan
of a Go or JS codebase still gets the full capability map and the does/decides/brittle/surprising
findings that read from it. It just does not get the Python dependency graph.

It answers four questions about a codebase, keeping fact and judgment in separate layers:

- **does**: what the code actually does. Its capabilities: running processes, network calls,
  filesystem writes, evaluating code.
- **decides**: where behaviour forks at runtime, such as dynamic dispatch and command-line
  entry points.
- **brittle**: where it is fragile. Opaque runtime loading, dependence on external services,
  destructive side effects, modules with a wide blast radius, import cycles, files that do not
  parse, and logic buried so deep in nested conditions it is hard to reach and hard to test.
- **surprising**: mismatches and code that does not run. A capability hidden in a passive-looking
  module, orphan files nothing imports, statements after a `return` or `raise`, branches behind
  a constant guard like `if False:`, and private definitions nothing references.

## How it works

lucent keeps *observation* (a judgment-free fact) separate from *interpretation* (a lens
reading), the way [parallax](https://github.com/batteryshark/parallax) does. It runs a
four-phase investigation on [muster](https://github.com/batteryshark/muster), a ledgered
investigation runtime:

```
inventory sources → observe each file → compose findings → render report
```

1. **Observe.** For each file, lucent extracts the callees and classifies them against the
   vendored parallax callee signature pack, plus a small lucent supplement for Python stdlib
   idioms the reference pack misses (pathlib I/O, `os.environ`, `hashlib`, `threading`,
   `time.sleep`). The result is judgment-free **atoms** like `EXEC.PROC`, `NETW.HTTP`,
   `FSYS.WRITE`, `LOAD.EVAL`, and `ENVI.VAR`. This works for every grammar the tree-sitter
   language pack ships. Python is read with the standard-library `ast` instead: import aliases
   resolve (`from subprocess import run as r; r()` becomes `subprocess.run`), and a qualified
   call counts only when its receiver is an imported module, so a local `requests = [];
   requests.append(...)` is never mistaken for the HTTP library.
2. **Structure (Python).** Python modules also get a symbol inventory and a **reference graph**:
   every import resolved to the internal module it names, in both directions (`dependsOn`,
   `dependents`, and `external`). A **reachability** pass over the same AST finds code that does
   not run or runs only under contorted conditions: unreachable statements, constant-guarded
   dead branches, unreferenced private definitions, and deeply-nested logic.
3. **Compose.** The four lenses read the atoms and structure into findings. Fragility (how much
   a point complicates understanding or change) stays separate from confidence (how sure the
   reading is), and every finding states what would disprove it.
4. **Synthesize and report.** lucent adds two whole-target reads. The **overview** says what the
   target is and what it is for: it surfaces the target's own stated **purpose** (from its
   package and component docstrings), and with the optional review model it also writes a
   **"how it does that"** narrative that traces the mechanism through the components. The
   **compositional analysis** shows the components, each one's role and capabilities, and how
   they depend on one another (the architecture collapsed from the module reference graph).
   These lead a self-contained, theme-aware HTML report, plus Markdown and JSON: overview,
   composition, then findings grouped by lens with cited code evidence.

This is understanding, not security, so findings carry **no severity**. A capability or a
decision is a fact about the code, not a risk. Only brittle findings carry a gradient, and that
gradient is **fragility**: how much a point complicates understanding or change. It stays
separate from **confidence** (how sure the reading is).

muster owns the machinery: run identity, the ledger, the coverage-gated work queue, and resume.
lucent supplies the domain: the observation engine, the reference graph, the lenses, and the
report. It runs on the same durable spine that [unmask](https://github.com/batteryshark/unmask)
uses for malicious-code detection, aimed at a different question: not "is this malicious?" but
"what is this, and where is it fragile?".

## Deepen it (optional)

The mechanical findings tell you *that* the code does something. An optional agentic overlay
tells you what it means. Pass `--review` and lucent reads the code behind each finding with a
model and adds a plain-language explanation, a refined confidence, and a verdict (confirm,
refine, refute, or needs-human). It is off by default and degrades cleanly: with no model
configured, the deterministic report is produced unchanged.

```bash
lucent scan path/to/target --review --model openai:gpt-4o
# or point at any OpenAI/Anthropic-compatible endpoint via LUCENT_REVIEW_* env
# (LUCENT_REVIEW_PROVIDER=lmstudio|ollama|openai|anthropic, LUCENT_REVIEW_MODEL=…)
```

Add an optional **goal** to focus the review. `--goal` nudges the reviewer toward an area, a
capability, or a question. It steers interpretation and what the report surfaces, never the
deterministic passes, so the map stays complete. The reviewer weights its reading toward the
goal and flags which findings bear on it, and the report leads with a "Toward your goal" digest.

```bash
lucent scan path/to/target --review --model openai:gpt-4o \
  --goal "how does auth work, and what would I touch to change it?"
```

## Usage

```bash
lucent scan path/to/target
```

`target` can be a single file, a package, or a whole repository. Reports land under
`.lucent/projects/<project>/runs/<run>/reports/understanding.{html,md,json}`.

## Install

lucent is not published to a package registry yet. Install it from a checkout:

```bash
uv sync                                 # core: Python targets fully covered, others via regex fallback
uv sync --extra parse                   # + tree-sitter: full-fidelity AST extraction for every language
uv sync --extra parse --extra review    # + pydantic-ai: the optional agentic-review overlay
# or, with pip:  pip install -e '.[parse,review]'
```

Without the `parse` extra, non-Python files fall back to a lower-fidelity regex callee scan (the
report's coverage section says which mode ran). Python is unaffected either way.

## What it does not claim

Capability is not accusation. An observed atom says what the code *can* do, not that it is
wrong. Absence is not a guarantee: an atom lucent did not observe may still be reachable through
a path its extractors do not cover, and the coverage section states those limits. The reference
graph, symbol inventory, reachability analysis, and docstring-derived purpose are Python-only.
Other languages are still observed for behaviour, and they appear in the capability map, the
composition, and the atom-driven findings, but they are not structurally linked.

## Requirements

Python 3.11+. The core has no heavy dependencies. The optional `parse` extra adds tree-sitter.
