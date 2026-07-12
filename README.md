# lucent

![Lucent — a retro robot inspector illuminating the hidden workings of a machine](assets/lucent-logo.png)

*Figure out a codebase, as a ledgered investigation.*

lucent reads a target and produces a coverage-guaranteed **understanding** of it: what every
source file can do, how the Python modules are wired together, and an interpretation of both
through four lenses. Every file is accounted for, and the run is durable and resumable
through a per-run SQLite ledger.

It answers four questions about a codebase, keeping fact and judgment in separate layers:

- **does** — what the code actually does: its capabilities (runs processes, makes network
  calls, writes files, evaluates code…).
- **decides** — where behaviour forks at runtime: dynamic dispatch, command-line entry points.
- **brittle** — where it is fragile: opaque runtime loading, external-service dependence,
  destructive side effects, high-blast-radius modules, import cycles, files that don't parse,
  and logic reached only in deeply-nested cases (hard to test, hard to hold in your head).
- **surprising** — mismatches and things that don't run: capability hidden in a passive-looking
  module, orphan files nothing imports, unreachable statements (after a `return`/`raise`), dead
  branches behind a constant guard (`if False:`), and private definitions nothing references.

## How it works

lucent separates *observation* (a judgment-free fact) from *interpretation* (a lens reading),
the way [parallax](https://github.com/batteryshark/parallax) does. It runs a four-phase
investigation on [muster](https://github.com/batteryshark/muster), a ledgered investigation
runtime:

```
inventory sources → observe each file → compose findings → render report
```

1. **Observe.** For each file, lucent extracts the *callees* and classifies them against the
   vendored parallax callee signature pack — plus a small lucent supplement for Python stdlib
   idioms the reference pack doesn't cover (pathlib I/O, `os.environ`, `hashlib`, `threading`,
   `time.sleep`) — into judgment-free **atoms** (`EXEC.PROC`, `NETW.HTTP`, `FSYS.WRITE`,
   `LOAD.EVAL`, `ENVI.VAR`, and the rest). This is multi-language: every grammar the tree-sitter
   language pack ships is supported. Python is additionally read with the standard-library
   `ast` — import aliases are resolved (`from subprocess import run as r; r()` → `subprocess.run`)
   and a qualified call is only trusted when its receiver is an imported module, so a local
   `requests = []; requests.append(...)` is never mistaken for the HTTP library.
2. **Structure (Python).** Python modules also get a symbol inventory and a **reference
   graph**: every import resolved to the internal module it names, both directions —
   `dependsOn`, `dependents` ("what breaks if I touch this"), and `external`. A **reachability**
   pass over the same AST finds code that doesn't run or runs only under contorted conditions:
   unreachable statements, constant-guarded dead branches, unreferenced private definitions, and
   deeply-nested logic.
3. **Compose.** The four lenses read the atoms and structure into findings. Severity (how much
   this complicates understanding or change) is kept separate from confidence (how sure the
   reading is), and every finding names what would disprove it.
4. **Synthesize + report.** lucent adds two whole-target reads. The **overview** answers what the
   thing you pointed at *is* and *is for*: it surfaces the target's own stated **purpose** (from
   its package and component docstrings), and — with the optional review model — synthesizes a
   **"how it does that"** narrative that traces the mechanism through the components. The
   **compositional analysis** shows the components, each one's role and capabilities, and how they
   depend on one another (the architecture collapsed from the module reference graph). These lead
   a self-contained, theme-aware HTML report (plus Markdown and JSON): overview, composition, then
   findings grouped by lens with cited code evidence.

This is understanding, not security, so findings carry **no severity**. A capability or a
decision point is just a fact about the code. Only *brittle* findings carry a gradient, and it
is **fragility** — how much a point complicates understanding or change — always kept separate
from **confidence** (how sure the reading is).

muster owns the machinery (run identity, the ledger, the coverage-gated work-queue drain,
resume); lucent brings the domain: the observation engine, the reference graph, the lenses,
and the report. It is the same durable spine [unmask](https://github.com/batteryshark/unmask)
uses for malicious-code detection, re-pointed from "is this malicious?" to "what is this, and
where is it fragile?".

## Deepen it (optional)

The mechanical findings tell you *that* the code does something. An optional agentic overlay
tells you *what it really means*: pass `--review` and lucent reads the code behind each
finding with a model and adds a plain-language explanation, a refined confidence, and a
verdict (confirm / refine / refute / needs-human) — the better the system is understood, the
better the decisions about it. It is off by default and degrades gracefully: with no model
configured the deterministic report is produced unchanged.

```bash
lucent scan path/to/target --review --model openai:gpt-4o
# or point at any OpenAI/Anthropic-compatible endpoint via LUCENT_REVIEW_* env
# (LUCENT_REVIEW_PROVIDER=lmstudio|ollama|openai|anthropic, LUCENT_REVIEW_MODEL=…)
```

Add an optional **goal** to point the flashlight. `--goal` is a subtle nudge to the reviewer —
an area, a capability, or a question — that only steers *interpretation and surfacing*, never
the deterministic passes (so the map stays complete). The reviewer weights its reading toward
the goal and flags which findings bear on it; the report leads with a "Toward your goal" digest.

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

lucent isn't published to a package registry yet — install it from a checkout:

```bash
uv sync                                 # core: Python targets fully covered, others via regex fallback
uv sync --extra parse                   # + tree-sitter: full-fidelity AST extraction for every language
uv sync --extra parse --extra review    # + pydantic-ai: the optional agentic-review overlay
# or, with pip:  pip install -e '.[parse,review]'
```

Without the `parse` extra, non-Python files fall back to a lower-fidelity regex callee scan
(the report's coverage section says which mode ran). Python is unaffected either way.

## What it does not claim

Capability is not accusation — an observed atom says what the code *can* do, not that it is
wrong. Absence is not a guarantee — an atom lucent did not observe may still be reachable
through a path its extractors do not cover (the coverage section states the limits). The
dependency graph and symbol inventory are Python-only; other languages are observed for
behaviour but not structurally linked.

## Requirements

Python 3.11+. The core has no heavy dependencies; the optional `parse` extra adds tree-sitter.
