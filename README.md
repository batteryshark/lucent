# lucent

*Code understanding as a ledgered investigation.*

lucent reads a Python target, understands each module (its functions, classes, methods, and
imports), and drains that surface to full coverage: every module is accounted for, and the
run is durable and resumable through a per-run SQLite ledger. The result is a queryable map
of what a codebase contains, produced with the coverage guarantee you would want from any
thorough sweep.

lucent is built on [muster](https://github.com/batteryshark/muster), a ledgered
investigation runtime. muster owns the machinery (run identity, the ledger, the work-queue
drain, resume); lucent brings the domain: a `symbols` table, a handler that understands one
module and queues its imports for linking, and a definition of what "covered" means for a
codebase.

```bash
lucent scan path/to/pkg
```

## Requirements

Python 3.11+. Parsing is pure standard-library `ast`; no heavy dependencies.
