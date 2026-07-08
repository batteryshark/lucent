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
