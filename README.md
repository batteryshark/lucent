# Lucent

> *How does this code actually work — what does it do, what does it decide, where is it brittle, and what's surprising about it?*

**Lucent is the benign sibling of [unmask](../unmask).** Where unmask asks "is this
malicious, and can you prove it?" and composes `BP-*` findings, Lucent points the
same machinery at **comprehension**: it reads a target and explains how it behaves,
for a human or an agent trying to understand software they didn't write.

Status: **🅿️ PARKED — not started.** This folder stakes out the project and preserves
its seed. We do **not** build Lucent until [unmask](../unmask)'s ledger-based scanning
and triage are working and coverage is proven good. Lucent then reuses that proven
architecture for non-malicious reading. (Codename for what was "code-understanding".)

## The four lenses

Lucent reads every finding through exactly one lens — judgment-free observation,
grouped into a four-section report:

| Lens | Question |
|---|---|
| **does** | What the code actually does — its capabilities, behaviours, side effects. |
| **decides** | The decisions it makes — branches, policies, thresholds, the config/inputs it keys on. |
| **brittle** | Where it is fragile — unhandled edges, sharp assumptions, error paths that swallow failures. |
| **surprising** | Anything unexpected given what it claims to be — dead code, hidden capability, name/behaviour mismatch. |

## Architecture (mirror unmask)

The plan is to rebuild Lucent the way unmask was built, swapping the malicious lens
for the four understanding lenses:

- **Deterministic scanner** — the vendored parallax engine + tree-sitter parses the
  target and emits judgment-free observation atoms (`EXEC.*`, `NETW.*`, `CRED.*`,
  `LOAD.*`, `FSYS.*`, …). This already exists as the `code-understanding` skill.
- **Its own taxonomy + signature packs**, *vendored into the wheel* exactly like
  unmask vendors the parallax taxonomy — so Lucent is self-contained, no sibling
  checkout at runtime. The understanding lenses (does/decides/brittle/surprising) are
  Lucent's taxonomy, distinct from unmask's `BP-*` malicious compositions.
- **Ledger-based coverage** — a per-run SQLite ledger is the durable coverage/resume
  oracle; the model never decides completion, the coverage gate does. This is the
  piece being proven in unmask first.
- **Report over the ledger** — a renderer groups the generic ledger findings into the
  four-section understanding report (the substrate is generic; the goalpack owns the
  shape). Optional bounded agentic pass for narrative, never for coverage.

## What's in `seed/`

A snapshot of the germ this project grows from (copied from `parallax-goalpacks`,
which keeps its own live copies — Lucent will supersede them once built):

- **`seed/understand/`** — the `understand` goalpack: the four-lens system prompt +
  the renderer that shapes generic ledger findings into the report.
- **`seed/code-understanding/`** — the deterministic scanner skill (vendored parallax
  engine + tree-sitter → observation atoms; regex fallback). The reproducible,
  judgment-free inventory layer Lucent's reading sits on top of. *(The heavy `.venv`
  was intentionally not copied — rebuild via `scripts/setup.sh`.)*

## Family

- **[parallax](https://github.com/batteryshark/parallax)** — the taxonomy: reading code as behaviour.
- **[unmask](../unmask)** — the malicious lens (`BP-*`); the pilot for the ledger + triage architecture.
- **Lucent** — the understanding lens (does/decides/brittle/surprising). ← this project.
- **rekit** / **rekit-factory** — the RE skill/tool kit and the runtime that drives fleets of RE agents.

## When we start

The trigger is: unmask's scanning + triage proven, coverage good. Then — spin Lucent
into its own repo, vendor its taxonomy/signatures, and build the scanner→observe→
compose(4 lenses)→assess→report pipeline over the ledger, reusing everything unmask
established.
