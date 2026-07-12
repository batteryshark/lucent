-- lucent DOMAIN ledger table — layered onto muster's core spine.
--
-- muster owns the generic spine (runs, artifacts, work_items, graph_events, reports,
-- questions, answers) and applies it first; this file adds only the code-understanding
-- domain: what we UNDERSTOOD about each module. Registered via LucentLedger(extra_schema=
-- ...). Pragmas + schema-version bookkeeping live in the core spine, not here.

create table if not exists symbols (
    id         text primary key,
    run_id     text not null,
    module     text not null,               -- module rel path (the artifact it came from)
    name       text not null,
    kind       text not null,               -- function|class|method|import
    lineno     integer not null default 0,
    detail     text,                         -- e.g. qualified import target / enclosing class
    created_at text not null
);
create index if not exists idx_symbols_run on symbols(run_id);

-- resolved reference edges: a module's imports linked back to the module they name.
-- `symbols` records that module X imports the name Y; `refs` records the EDGE X -> the
-- module that provides Y, when that module is inside the target (an internal edge), plus a
-- reverse index so "who depends on this module?" is one query. Built by the link-imports
-- handler once the full module inventory is known.
create table if not exists refs (
    id         text primary key,
    run_id     text not null,
    src_module text not null,               -- the importing module (rel path)
    dst_module text,                         -- resolved internal module (rel path), else null
    target     text not null,               -- dotted module the import resolves/points to
    name       text not null,               -- local binding introduced by the import
    lineno     integer not null default 0,
    kind       text not null,               -- internal | external | unresolved
    created_at text not null
);
create index if not exists idx_refs_run on refs(run_id);
create index if not exists idx_refs_src on refs(run_id, src_module);
create index if not exists idx_refs_dst on refs(run_id, dst_module);

-- observations: judgment-free behavior atoms observed at call sites across every language
-- lucent can parse. `symbols`/`refs` describe a Python module's STRUCTURE; `observations`
-- describe what any source file can DO (EXEC.PROC, NETW.HTTP, FSYS.WRITE, LOAD.EVAL, ...),
-- with the callee that fired the rule and how sure the pack is. No severity, no verdict —
-- the lenses read these into findings. Recorded by the observe step; reset on resume.
create table if not exists observations (
    id         text primary key,
    run_id     text not null,
    module     text not null,               -- source file rel path (the artifact it came from)
    atom       text not null,               -- parallax atom id, e.g. EXEC.SHELL
    confidence real not null,               -- pack confidence, gate-adjusted; how sure, not how bad
    method     text not null,               -- how it was seen: callee-python-ast|callee-tree-sitter|callee-regex
    lineno     integer not null default 0,
    evidence   text,                         -- the callee string that matched
    rule_id    text,                         -- the signature-pack rule that fired
    created_at text not null
);
create index if not exists idx_obs_run on observations(run_id);
create index if not exists idx_obs_module on observations(run_id, module);
create index if not exists idx_obs_atom on observations(run_id, atom);

-- findings: the interpreted layer. A lens (`does`/`decides`/`brittle`/`surprising`) reads
-- the atoms + structure of one module into a claim about it. This is understanding, not
-- security: there is no "severity". Only `brittle` findings carry a gradient — `fragility`
-- (how much this complicates understanding/change) — kept separate from confidence (how sure);
-- the other lenses are descriptive and leave it null. Every finding names what would disprove
-- it. Composed after the surface is fully observed; reset on resume. The optional agentic
-- overlay reviews these rows.
create table if not exists findings (
    id            text primary key,
    run_id        text not null,
    lens          text not null,            -- does | decides | brittle | surprising
    composition   text,                      -- named pattern, e.g. high-blast-radius, opaque-loading
    module        text,                      -- the module the finding is about (null = whole-codebase)
    title         text not null,
    claim         text not null,
    fragility     text,                      -- brittle only: low | medium | high; null for other lenses
    confidence    real not null,
    conf_label    text,                      -- low | medium | high (a band over confidence)
    evidence_json text not null default '[]',  -- cited observation/symbol ids + loci
    disproof_json text not null default '[]',  -- what would disprove this reading
    verify_json   text not null default '[]',  -- what to check next
    created_at    text not null
);
create index if not exists idx_findings_run on findings(run_id);
create index if not exists idx_findings_lens on findings(run_id, lens);

-- reviews: the optional agentic overlay. A bounded model step reads the code behind one
-- finding and deepens it — what is actually happening at the cited sites, and how much the
-- mechanical reading holds. Severity is never changed here; the reviewer refines confidence
-- and adds a plain-language explanation. Present only when a run enabled review; reset on
-- resume (re-derived when the run is re-driven with review on).
create table if not exists reviews (
    id                   text primary key,
    run_id               text not null,
    finding_id           text not null,
    verdict              text not null,          -- confirm | refine | refute | needs_human
    reviewed_confidence  real not null,
    explanation          text,
    consideration        text,
    relevance            text,                    -- how this bears on the reader's goal (if any)
    disproof_checked_json text not null default '[]',
    model                text,
    created_at           text not null
);
create index if not exists idx_reviews_run on reviews(run_id);

-- reachability: dead, unreachable, and hard-to-reach code (Python). Judgment-free structural
-- facts about parts that don't run or run only under contorted conditions — statements after a
-- return, branches behind a constant guard, deeply-nested logic, and private defs nothing
-- references. Recorded by the understand-file pass; read by the surprising/brittle lenses.
create table if not exists reachability (
    id         text primary key,
    run_id     text not null,
    module     text not null,
    kind       text not null,               -- unreachable | constant-guard | deep-nesting | dead-code
    name       text,                         -- enclosing function, or the dead symbol
    lineno     integer not null default 0,
    detail     text,
    created_at text not null
);
create index if not exists idx_reach_run on reachability(run_id);

-- docstrings: each Python module's own words about what it is for. The single best signal of
-- *purpose* (as opposed to mechanism) that lives in the source — the package/component
-- docstrings state intent the AST alone can't. Read by the overview (stated purpose) and the
-- composition (component roles), and fed to the optional purpose synthesis.
create table if not exists docstrings (
    id         text primary key,
    run_id     text not null,
    module     text not null,
    text       text not null,
    created_at text not null
);
create index if not exists idx_docstrings_run on docstrings(run_id);
