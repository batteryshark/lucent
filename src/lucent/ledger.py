"""LucentLedger: the lucent DOMAIN ledger — muster's spine plus a `symbols` table.

Exactly the unmask pattern, a second time: subclass muster.Ledger, pass the domain
schema + resume-reset set through the constructor, and add only the domain record/count
methods. muster stays ignorant of what a "symbol" is.
"""

from __future__ import annotations

from pathlib import Path

from muster.ledger import Ledger, new_id, utcnow

_DOMAIN_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_DOMAIN_SCHEMA = _DOMAIN_SCHEMA_PATH.read_text(encoding="utf-8")  # read once at import
_DOMAIN_RESET_TABLES = ("symbols",)


class LucentLedger(Ledger):
    def __init__(self, db_path: str | Path):
        super().__init__(db_path, extra_schema=_DOMAIN_SCHEMA, reset_tables=_DOMAIN_RESET_TABLES)

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
