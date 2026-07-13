"""LucentLedger: the lucent domain ledger, muster.Ledger plus domain tables such as `symbols`.

Subclasses muster.Ledger. The constructor passes the domain schema and the resume-reset
table set to the base; this class adds only the domain record and count methods. The base
Ledger has no concept of a "symbol".
"""

from __future__ import annotations

from pathlib import Path

import json

from muster.ledger import Ledger, new_id, utcnow

_DOMAIN_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_DOMAIN_SCHEMA = _DOMAIN_SCHEMA_PATH.read_text(encoding="utf-8")  # read once at import
_DOMAIN_RESET_TABLES = ("symbols", "refs", "observations", "findings", "reviews",
                        "reachability", "docstrings")


class LucentLedger(Ledger):
    def __init__(self, db_path: str | Path):
        super().__init__(db_path, extra_schema=_DOMAIN_SCHEMA, reset_tables=_DOMAIN_RESET_TABLES)

    def reset_run_derived(self, run_id: str) -> None:
        """Rebuild Lucent's work queue together with its derived domain state on resume."""
        super().reset_run_derived(run_id)
        self.delete_run_rows(run_id, "work_items", "work_notes")

    def add_symbol(self, *, run_id, module, name, kind, lineno=0, detail=None) -> str:
        sid = new_id("sym")
        self.conn.execute(
            """insert into symbols (id, run_id, module, name, kind, lineno, detail, created_at)
               values (?,?,?,?,?,?,?,?)""",
            (sid, run_id, module, name, kind, lineno, detail, utcnow()),
        )
        self.conn.commit()
        return sid

    def count_symbols(self, run_id: str, kind: str | None = None) -> int:
        if kind is None:
            cur = self.conn.execute("select count(*) c from symbols where run_id=?", (run_id,))
        else:
            cur = self.conn.execute(
                "select count(*) c from symbols where run_id=? and kind=?", (run_id, kind))
        return cur.fetchone()["c"]

    def symbols_by_module(self, run_id: str) -> dict[str, list[dict]]:
        rows = self.conn.execute(
            "select module, name, kind, lineno, detail from symbols where run_id=? "
            "order by module, lineno, name", (run_id,)).fetchall()
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r["module"], []).append(
                {"name": r["name"], "kind": r["kind"], "lineno": r["lineno"], "detail": r["detail"]})
        return out

    def module_paths(self, run_id: str) -> list[str]:
        """Relative paths of every inventoried Python module, i.e. the set an import can
        resolve into. The reference graph is Python-only, so this filters by language rather
        than by the language-neutral artifact kind."""
        rows = self.conn.execute(
            "select logical_path from artifacts where run_id=? and kind='source-file' "
            "and language='python' order by logical_path", (run_id,)).fetchall()
        return [r["logical_path"] for r in rows]

    def count_files(self, run_id: str, language: str | None = None) -> int:
        """Inventoried source files, optionally for one language."""
        if language is None:
            cur = self.conn.execute(
                "select count(*) c from artifacts where run_id=? and kind='source-file'", (run_id,))
        else:
            cur = self.conn.execute(
                "select count(*) c from artifacts where run_id=? and kind='source-file' "
                "and language=?", (run_id, language))
        return cur.fetchone()["c"]

    def language_counts(self, run_id: str) -> dict[str, int]:
        """Inventoried source files grouped by language: the codebase's language mix."""
        cur = self.conn.execute(
            "select language, count(*) c from artifacts where run_id=? and kind='source-file' "
            "group by language order by c desc", (run_id,))
        return {r["language"] or "unknown": r["c"] for r in cur.fetchall()}

    def module_languages(self, run_id: str) -> dict[str, str]:
        """``logical_path -> language`` for every inventoried source file, so the lens can
        reason about a file without re-reading it."""
        rows = self.conn.execute(
            "select logical_path, language from artifacts where run_id=? and kind='source-file'",
            (run_id,)).fetchall()
        return {r["logical_path"]: r["language"] for r in rows}

    def artifact_paths(self, run_id: str) -> dict[str, str]:
        """``logical_path -> on-disk path`` so the report can read a real source snippet."""
        rows = self.conn.execute(
            "select logical_path, path from artifacts where run_id=? and kind='source-file'",
            (run_id,)).fetchall()
        return {r["logical_path"]: r["path"] for r in rows}

    def failed_work(self, run_id: str, operation: str) -> list[dict]:
        """Work items of ``operation`` that ended ``failed``, e.g. modules that would not
        parse. Returns ``{module, error}`` per item, so the lens can surface them as brittle
        findings."""
        rows = self.conn.execute(
            "select target, error from work_items where run_id=? and operation=? and status='failed'",
            (run_id, operation)).fetchall()
        return [{"module": r["target"], "error": r["error"] or "did not parse"} for r in rows]

    # --- observations (judgment-free behavior atoms) -------------------------

    def add_observation(self, *, run_id, module, atom, confidence, method, lineno=0,
                        evidence=None, rule_id=None, obs_id=None) -> str:
        oid = obs_id or new_id("obs")
        self.conn.execute(
            """insert into observations
                   (id, run_id, module, atom, confidence, method, lineno, evidence, rule_id, created_at)
               values (?,?,?,?,?,?,?,?,?,?)""",
            (oid, run_id, module, atom, confidence, method, lineno, evidence, rule_id, utcnow()),
        )
        self.conn.commit()
        return oid

    def count_observations(self, run_id: str, atom: str | None = None) -> int:
        if atom is None:
            cur = self.conn.execute(
                "select count(*) c from observations where run_id=?", (run_id,))
        else:
            cur = self.conn.execute(
                "select count(*) c from observations where run_id=? and atom=?", (run_id, atom))
        return cur.fetchone()["c"]

    def atom_counts(self, run_id: str) -> dict[str, int]:
        """Observations grouped by atom: the codebase's capability profile."""
        cur = self.conn.execute(
            "select atom, count(*) c from observations where run_id=? group by atom "
            "order by c desc", (run_id,))
        return {r["atom"]: r["c"] for r in cur.fetchall()}

    def observations(self, run_id: str) -> list[dict]:
        """Every observation as a plain dict, in file and line order. This is the substrate
        the lenses read and the report cites."""
        rows = self.conn.execute(
            "select id, module, atom, confidence, method, lineno, evidence, rule_id "
            "from observations where run_id=? order by module, lineno", (run_id,)).fetchall()
        return [dict(r) for r in rows]

    # --- docstrings (the code's own words about purpose) ---------------------

    def add_docstring(self, *, run_id, module, text) -> str:
        did = new_id("doc")
        self.conn.execute(
            "insert into docstrings (id, run_id, module, text, created_at) values (?,?,?,?,?)",
            (did, run_id, module, text, utcnow()))
        self.conn.commit()
        return did

    def docstrings(self, run_id: str) -> dict[str, str]:
        rows = self.conn.execute(
            "select module, text from docstrings where run_id=?", (run_id,)).fetchall()
        return {r["module"]: r["text"] for r in rows}

    # --- reachability (dead / unreachable / hard-to-reach code) --------------

    def add_reachability(self, *, run_id, module, kind, lineno=0, name=None, detail=None) -> str:
        rid = new_id("reach")
        self.conn.execute(
            """insert into reachability (id, run_id, module, kind, name, lineno, detail, created_at)
               values (?,?,?,?,?,?,?,?)""",
            (rid, run_id, module, kind, name, lineno, detail, utcnow()),
        )
        self.conn.commit()
        return rid

    def reachability(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "select module, kind, name, lineno, detail from reachability where run_id=? "
            "order by module, lineno", (run_id,)).fetchall()
        return [dict(r) for r in rows]

    def count_reachability(self, run_id: str, kind: str | None = None) -> int:
        if kind is None:
            return self.conn.execute(
                "select count(*) c from reachability where run_id=?", (run_id,)).fetchone()["c"]
        return self.conn.execute(
            "select count(*) c from reachability where run_id=? and kind=?",
            (run_id, kind)).fetchone()["c"]

    # --- findings (the interpreted layer) ------------------------------------

    def add_finding(self, *, run_id, lens, title, claim, confidence, fragility=None,
                    conf_label=None, module=None, composition=None, evidence=None,
                    disproof=None, verify=None, finding_id=None) -> str:
        fid = finding_id or new_id("find")
        self.conn.execute(
            """insert into findings
                   (id, run_id, lens, composition, module, title, claim, fragility,
                    confidence, conf_label, evidence_json, disproof_json, verify_json, created_at)
               values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fid, run_id, lens, composition, module, title, claim, fragility, confidence,
             conf_label, json.dumps(evidence or []), json.dumps(disproof or []),
             json.dumps(verify or []), utcnow()),
        )
        self.conn.commit()
        return fid

    def count_findings(self, run_id: str, lens: str | None = None) -> int:
        if lens is None:
            cur = self.conn.execute("select count(*) c from findings where run_id=?", (run_id,))
        else:
            cur = self.conn.execute(
                "select count(*) c from findings where run_id=? and lens=?", (run_id, lens))
        return cur.fetchone()["c"]

    def findings(self, run_id: str) -> list[dict]:
        """Every finding as a plain dict (json columns decoded), in lens/fragility order."""
        rows = self.conn.execute(
            "select * from findings where run_id=? order by lens, fragility", (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for col in ("evidence_json", "disproof_json", "verify_json"):
                d[col.removesuffix("_json")] = json.loads(d.pop(col) or "[]")
            out.append(d)
        return out

    # --- reviews (optional agentic overlay) ----------------------------------

    def record_review(self, run_id: str, review, *, model: str | None = None) -> str:
        """Persist one FindingReview as a durable review row."""
        rid = new_id("rev")
        self.conn.execute(
            """insert into reviews
                   (id, run_id, finding_id, verdict, reviewed_confidence, explanation,
                    consideration, relevance, disproof_checked_json, model, created_at)
               values (?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, run_id, review.finding_id, review.verdict, review.reviewed_confidence,
             review.explanation, review.consideration, getattr(review, "relevance", ""),
             json.dumps(list(review.disproof_checked or [])), model, utcnow()),
        )
        self.conn.commit()
        return rid

    def count_reviews(self, run_id: str) -> int:
        return self.conn.execute(
            "select count(*) c from reviews where run_id=?", (run_id,)).fetchone()["c"]

    def reviews(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "select finding_id, verdict, reviewed_confidence, explanation, consideration, "
            "relevance, disproof_checked_json, model from reviews where run_id=?", (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["disproof_checked"] = json.loads(d.pop("disproof_checked_json") or "[]")
            out.append(d)
        return out

    # --- reference graph -----------------------------------------------------

    def add_ref(self, *, run_id, src_module, dst_module, target, name, lineno=0,
                kind="external") -> str:
        rid = new_id("ref")
        self.conn.execute(
            """insert into refs
                   (id, run_id, src_module, dst_module, target, name, lineno, kind, created_at)
               values (?,?,?,?,?,?,?,?,?)""",
            (rid, run_id, src_module, dst_module, target, name, lineno, kind, utcnow()),
        )
        self.conn.commit()
        return rid

    def count_refs(self, run_id: str, kind: str | None = None) -> int:
        if kind is None:
            cur = self.conn.execute("select count(*) c from refs where run_id=?", (run_id,))
        else:
            cur = self.conn.execute(
                "select count(*) c from refs where run_id=? and kind=?", (run_id, kind))
        return cur.fetchone()["c"]

    def dependency_graph(self, run_id: str) -> dict:
        """The resolved reference graph, both directions. `dependsOn`/`dependents` cover only
        internal edges (module -> module inside the target); `external` lists the outward
        dotted targets a module pulls in but that live outside the target."""
        rows = self.conn.execute(
            "select src_module, dst_module, target, name, lineno, kind from refs "
            "where run_id=? order by src_module, lineno, target", (run_id,)).fetchall()
        edges: list[dict] = []
        depends_on: dict[str, set[str]] = {}
        dependents: dict[str, set[str]] = {}
        external: dict[str, set[str]] = {}
        for r in rows:
            if r["kind"] == "internal" and r["dst_module"]:
                edges.append({"src": r["src_module"], "dst": r["dst_module"],
                              "name": r["name"], "lineno": r["lineno"]})
                depends_on.setdefault(r["src_module"], set()).add(r["dst_module"])
                dependents.setdefault(r["dst_module"], set()).add(r["src_module"])
            else:
                external.setdefault(r["src_module"], set()).add(r["target"])
        srt = lambda m: {k: sorted(v) for k, v in sorted(m.items())}
        return {"internalEdges": edges, "dependsOn": srt(depends_on),
                "dependents": srt(dependents), "external": srt(external)}
