"""Render an assessment to JSON / Markdown / self-contained HTML.

The HTML is fully self-contained (inline CSS + one tiny inline script), theme-aware
(light/dark via ``prefers-color-scheme``), and escapes every finding- or source-derived
string. It is modelled on unmask's report design system but re-skinned for understanding:
a calm synopsis banner instead of a disposition alarm, findings grouped by the four lenses
(does / decides / brittle / surprising) rather than by malice, and a structure section that
surfaces the dependency hubs. Severity and confidence are always shown as two axes.
"""

from __future__ import annotations

import html
import json

_LENSES = ["does", "decides", "brittle", "surprising"]
_LENS_TITLE = {"does": "What it does", "decides": "What it decides",
               "brittle": "Where it is brittle", "surprising": "What is surprising"}
_LENS_BLURB = {
    "does": "The capabilities the code reaches for — what it can actually do.",
    "decides": "Where behaviour forks at runtime: dispatch, entry points, configuration.",
    "brittle": "Points that are opaque, remote-dependent, destructive, or high-blast-radius.",
    "surprising": "Capability that doesn't fit a module's apparent role, and orphans.",
}
_FRAG_ORDER = ["high", "medium", "low"]


def _sorted_group(group: list[dict]) -> list[dict]:
    """Within a lens: brittle findings by fragility (high→low) then confidence; other lenses,
    which carry no rating, by confidence descending."""
    def key(f):
        frag = f.get("fragility")
        rank = _FRAG_ORDER.index(frag) if frag in _FRAG_ORDER else len(_FRAG_ORDER)
        return (rank, -(f.get("confidence") or 0))
    return sorted(group, key=key)


def render_json(assessment: dict) -> str:
    return json.dumps(assessment, indent=2)


def _esc(s) -> str:
    return html.escape("" if s is None else str(s))


def _conf_pct(c) -> str:
    return f"{round(c * 100)}%" if isinstance(c, (int, float)) else "n/a"


# --- markdown --------------------------------------------------------------

def render_markdown(a: dict) -> str:
    summ = a.get("summary") or {}
    obs_by_id = {o["id"]: o for o in (a.get("observations") or [])}
    out: list[str] = ["# Codebase understanding", ""]
    target = (a.get("target") or {}).get("path", "")
    if target:
        out += [f"`{target}`", ""]
    ov = a.get("overview") or {}
    out += ["## Overview", ""]
    if ov.get("purpose"):
        out += [f"**Purpose (in its own words):** {ov['purpose']}", ""]
    if ov.get("howItWorks"):
        out += [f"**How it does that:** {ov['howItWorks']}", ""]
    out += [ov.get("text") or (a.get("synopsis") or {}).get("text", ""), ""]
    if a.get("goal"):
        out += [f"**Goal:** {a['goal']}", ""]
    out.append(f"**Files:** {summ.get('fileCount', 0)}  ·  "
               f"**Components:** {summ.get('componentCount', 0)}  ·  "
               f"**Python modules:** {summ.get('moduleCount', 0)}  ·  "
               f"**Observations:** {summ.get('atomCount', 0)}  ·  "
               f"**Findings:** {summ.get('findingCount', 0)}")
    langs = summ.get("languages") or {}
    if langs:
        out.append("**Languages:** " + ", ".join(f"{k} ({v})" for k, v in langs.items()))
    out.append("")

    for lens in _LENSES:
        group = [f for f in (a.get("findings") or []) if f["lens"] == lens]
        if not group:
            continue
        out += [f"## {_LENS_TITLE[lens]}", ""]
        for f in _sorted_group(group):
            out.append(f"### {f['title']}")
            rating = f"fragility: **{f['fragility']}** · " if f.get("fragility") else ""
            out.append(f"_{rating}confidence: **{f['confidence']}** ({f.get('conf_label')})_")
            out += ["", f["claim"], ""]
            rev = f.get("review")
            if rev:
                out.append(f"> **Reviewer ({rev.get('verdict')}, confidence now "
                           f"{_conf_pct(rev.get('reviewed_confidence'))}):** {rev.get('explanation')}")
                if rev.get("consideration"):
                    out.append(f"> _{rev['consideration']}_")
                out.append("")
            if f.get("disproof"):
                out.append("**What would disprove this:**")
                out += [f"- {d}" for d in f["disproof"]]
                out.append("")
            for ev in f.get("evidence", []):
                if isinstance(ev, dict) and ev.get("obs") in obs_by_id:
                    o = obs_by_id[ev["obs"]]
                    loc = o["location"]
                    out.append(f"- `{loc['path']}:{loc.get('line', '?')}` — "
                               f"{o.get('atom')} `{(o.get('evidence') or {}).get('matchedText', '')}`")
                elif isinstance(ev, dict) and ev.get("path"):
                    note = f" — {ev['note']}" if ev.get("note") else ""
                    out.append(f"- `{ev['path']}`{note}")
            out.append("")

    deps = a.get("dependencies") or {}
    dependents = deps.get("dependents") or {}
    if dependents:
        out += ["## Structure — dependency hubs", ""]
        for mod, dents in sorted(dependents.items(), key=lambda kv: -len(kv[1]))[:8]:
            out.append(f"- `{mod}` ← {len(dents)} dependent(s)")
        out.append("")

    cov = a.get("coverage") or {}
    out += ["## Coverage", ""]
    out += [f"- {n}" for n in cov.get("notes", [])]
    out += ["", "---", f"_{(a.get('contract') or {}).get('note', '')}_", ""]
    return "\n".join(out)


# --- html ------------------------------------------------------------------

_CSS = """
:root{
  --bg:#0e1116; --panel:#161b22; --panel-2:#1b212b; --fg:#e7ecf3; --muted:#9aa6b6;
  --faint:#6b7787; --line:#2a323d; --line-soft:#232a34; --accent:#6ea8fe; --code-bg:#0a0d12;
  --does:#6ea8fe; --decides:#b48ead; --brittle:#ff9f45; --surprising:#63c98a;
  --high:#ff6b6b; --medium:#ffb454; --low:#63c98a; --informational:#7aa2c4;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.28); --radius:12px;
}
@media (prefers-color-scheme: light){
  :root{
    --bg:#f7f8fa; --panel:#fff; --panel-2:#f0f2f5; --fg:#14181d; --muted:#4a5460;
    --faint:#6b7787; --line:#d5dbe2; --line-soft:#e6eaef; --accent:#2b6cb0; --code-bg:#f6f7f9;
    --does:#2b6cb0; --decides:#8a5a9e; --brittle:#c26a1a; --surprising:#2f855a;
    --high:#c0392b; --medium:#b7791f; --low:#2f855a; --informational:#3a6ea5;
    --shadow:0 1px 2px rgba(0,0,0,.06),0 8px 24px rgba(0,0,0,.08);
  }
}
:root[data-theme="dark"]{
  --bg:#0e1116; --panel:#161b22; --panel-2:#1b212b; --fg:#e7ecf3; --muted:#9aa6b6;
  --faint:#6b7787; --line:#2a323d; --line-soft:#232a34; --accent:#6ea8fe; --code-bg:#0a0d12;
  --does:#6ea8fe; --decides:#b48ead; --brittle:#ff9f45; --surprising:#63c98a;
  --high:#ff6b6b; --medium:#ffb454; --low:#63c98a; --informational:#7aa2c4;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.28);
}
:root[data-theme="light"]{
  --bg:#f7f8fa; --panel:#fff; --panel-2:#f0f2f5; --fg:#14181d; --muted:#4a5460;
  --faint:#6b7787; --line:#d5dbe2; --line-soft:#e6eaef; --accent:#2b6cb0; --code-bg:#f6f7f9;
  --does:#2b6cb0; --decides:#8a5a9e; --brittle:#c26a1a; --surprising:#2f855a;
  --high:#c0392b; --medium:#b7791f; --low:#2f855a; --informational:#3a6ea5;
  --shadow:0 1px 2px rgba(0,0,0,.06),0 8px 24px rgba(0,0,0,.08);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:900px;margin:0 auto;padding:40px 22px 72px}
a{color:var(--accent)}
.masthead{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
  flex-wrap:wrap;margin-bottom:20px}
.kicker{font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.target{font-size:13px;color:var(--muted);word-break:break-all;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.synopsis{border:1px solid var(--line);border-left:6px solid var(--accent);border-radius:var(--radius);
  padding:20px 22px;box-shadow:var(--shadow);background:var(--panel)}
.synopsis h1{margin:0 0 10px;font-size:22px;font-weight:800;letter-spacing:.01em}
.synopsis p{margin:0;color:var(--fg);font-size:15.5px;line-height:1.6}
.axes{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:22px 0 8px}
.axis{background:var(--panel);border:1px solid var(--line-soft);border-radius:10px;padding:13px 15px}
.axis .lbl{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin-bottom:4px}
.axis .val{font-size:22px;font-weight:800;line-height:1.1}
.axis .sub{font-size:12px;color:var(--muted);margin-top:3px}
.axes-note{font-size:12.5px;color:var(--faint);margin:2px 2px 0}
h2.sec{font-size:15px;font-weight:700;letter-spacing:.02em;text-transform:uppercase;color:var(--muted);
  margin:40px 0 4px;padding-bottom:8px;border-bottom:1px solid var(--line-soft)}
h2.sec .count{color:var(--faint);font-weight:600;text-transform:none}
.caps{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.cap{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;
  padding:5px 11px;border-radius:999px;background:var(--panel-2);border:1px solid var(--line);color:var(--fg)}
.cap .n{font-weight:800;color:var(--accent)}
.toc{background:var(--panel);border:1px solid var(--line-soft);border-radius:10px;padding:12px 16px;margin:20px 0 0}
.toc-h{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);margin-bottom:8px}
.toc ul{margin:0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:6px 14px}
.toc a{font-size:13px;color:var(--muted);text-decoration:none}.toc a:hover{color:var(--accent)}
.lensgroup{margin-top:30px}
.lenshead{display:flex;align-items:center;gap:10px;margin:0 0 2px}
.lenshead .bar{width:5px;height:20px;border-radius:2px}
.lenshead .name{font-size:16px;font-weight:800}
.lenshead .n{font-size:12.5px;color:var(--faint)}
.lensblurb{font-size:13px;color:var(--muted);margin:0 0 10px 15px}
.bar.does,.name.does{--c:var(--does)} .bar.decides,.name.decides{--c:var(--decides)}
.bar.brittle,.name.brittle{--c:var(--brittle)} .bar.surprising,.name.surprising{--c:var(--surprising)}
.bar.does{background:var(--does)}.bar.decides{background:var(--decides)}
.bar.brittle{background:var(--brittle)}.bar.surprising{background:var(--surprising)}
.name.does{color:var(--does)}.name.decides{color:var(--decides)}
.name.brittle{color:var(--brittle)}.name.surprising{color:var(--surprising)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;margin:10px 0;box-shadow:var(--shadow);border-left:4px solid var(--lc,var(--line))}
.card.does{--lc:var(--does)}.card.decides{--lc:var(--decides)}
.card.brittle{--lc:var(--brittle)}.card.surprising{--lc:var(--surprising)}
.card .top{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap}
.card h3{margin:0;font-size:17px;font-weight:700;line-height:1.35;flex:1 1 240px}
.chips{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:700;padding:3px 9px;
  border-radius:999px;white-space:nowrap;border:1px solid var(--line);background:var(--panel-2);color:var(--muted)}
.chip .k{font-weight:600;opacity:.72}
.chip.frag-high{color:var(--high);border-color:var(--high)}.chip.frag-medium{color:var(--medium);border-color:var(--medium)}
.chip.frag-low{color:var(--low);border-color:var(--low)}
.chip.comp{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px}
.ov-kind{font-size:12.5px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;color:var(--accent);margin:-4px 0 10px}
.ov-purpose,.ov-how{margin:0 0 12px;padding:11px 14px;background:var(--panel-2);border-radius:8px;border:1px solid var(--line-soft)}
.ov-purpose{border-left:3px solid var(--accent)}.ov-how{border-left:3px solid var(--decides)}
.ov-plabel{display:block;font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);margin-bottom:5px}
.ov-purpose p,.ov-how p{margin:0;font-size:15px;line-height:1.55;color:var(--fg)}
.ov-facts{font-size:14px;color:var(--muted);line-height:1.55}
.comp-role{font-size:12.5px;color:var(--muted);line-height:1.45;margin-bottom:8px}
.comps{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-top:14px}
.comp{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 15px;box-shadow:var(--shadow)}
.comp-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:8px}
.comp-name{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;font-weight:700;color:var(--fg)}
.comp-n{font-size:11.5px;color:var(--faint)}
.ccaps{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.ccap{font-size:10.5px;font-weight:600;color:var(--muted);background:var(--panel-2);border:1px solid var(--line-soft);border-radius:999px;padding:2px 7px}
.ccap .n{color:var(--accent);font-weight:800}
.cdeps{font-size:12px;color:var(--muted)}.cdeps code{font-size:11.5px}
.meter{display:inline-flex;align-items:center;gap:6px}
.meter .track{width:40px;height:6px;border-radius:3px;background:var(--line);overflow:hidden}
.meter .fill{height:100%;background:var(--accent);border-radius:3px}
.claim{margin:12px 0 0;font-size:15px;color:var(--fg)}
.block{margin-top:14px}
.block .h{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);margin-bottom:7px}
.block ul{margin:0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:6px}
.block ul.disproof li{position:relative;padding-left:22px;font-size:14px;color:var(--muted)}
.block ul.disproof li::before{content:"✕";position:absolute;left:0;color:var(--faint);font-size:12px;top:2px}
.evidence{margin-top:14px;display:flex;flex-direction:column;gap:8px}
.ev{border:1px solid var(--line-soft);border-radius:8px;overflow:hidden;background:var(--code-bg)}
.evhead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:7px 11px;background:var(--panel-2);
  border-bottom:1px solid var(--line-soft)}
.evhead .loc{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;color:var(--fg);font-weight:600}
.evhead .atom{font-size:10.5px;font-weight:700;color:var(--muted);border:1px solid var(--line);border-radius:5px;padding:0 6px}
.ev pre{margin:0;padding:9px 11px;overflow-x:auto;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:12.5px;line-height:1.55;color:var(--fg)}
.ev pre .ln{color:var(--faint)}.ev pre .hit{color:var(--fg)}
.ev pre mark{background:rgba(255,159,69,.28);color:inherit;border-radius:3px;padding:0 1px}
.ev .note{font-size:13px;color:var(--muted);padding:7px 11px}
.struct{display:flex;flex-direction:column;gap:7px;margin-top:12px}
.hub{display:flex;align-items:center;gap:10px;background:var(--panel);border:1px solid var(--line-soft);
  border-radius:8px;padding:9px 13px}
.hub .mod{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;flex:1 1 auto}
.hub .cnt{font-size:12px;color:var(--muted)}
.hub .track{flex:0 0 120px;height:7px;border-radius:4px;background:var(--line);overflow:hidden}
.hub .fill{height:100%;background:var(--brittle);border-radius:4px}
.review{margin-top:14px;background:var(--panel-2);border:1px solid var(--line-soft);
  border-left:3px solid var(--accent);border-radius:8px;padding:11px 13px}
.rev-h{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.rev-label{font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--faint)}
.rev-conf{font-size:12px;color:var(--muted)}
.rev-badge{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;
  padding:2px 8px;border-radius:999px;border:1px solid transparent}
.rev-badge.confirm{color:var(--surprising);border-color:var(--surprising)}
.rev-badge.refine{color:var(--decides);border-color:var(--decides)}
.rev-badge.refute{color:var(--high);border-color:var(--high)}
.rev-badge.needs{color:var(--informational);border-color:var(--informational)}
.rev-exp{font-size:14px;color:var(--fg);line-height:1.55}
.rev-cons{font-size:13px;color:var(--muted);margin-top:6px;font-style:italic}
.rev-rel{font-size:13px;color:var(--does);margin-top:6px;font-weight:600}
.goal{display:flex;align-items:center;gap:10px;margin-top:14px;background:var(--panel-2);
  border:1px solid var(--line-soft);border-left:4px solid var(--does);border-radius:10px;padding:11px 15px}
.goal-lbl{font-size:10.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--does);flex:0 0 auto}
.goal-text{font-size:14.5px;color:var(--fg)}
.toward{margin-top:12px;border-top:1px solid var(--line-soft);padding-top:10px}
.toward-h{font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--does);margin-bottom:6px}
.toward ul{margin:0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:5px}
.toward li{font-size:13.5px;color:var(--fg);padding-left:16px;position:relative}
.toward li::before{content:"→";position:absolute;left:0;color:var(--does)}
.overlay{margin-top:14px;border:1px solid var(--line);border-left:6px solid var(--decides);
  border-radius:var(--radius);padding:16px 20px;background:var(--panel);box-shadow:var(--shadow)}
.overlay h2{margin:0 0 6px;font-size:16px;font-weight:800}
.overlay .sub{font-size:13.5px;color:var(--muted);line-height:1.55}
.overlay .tally{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.overlay .t{font-size:11.5px;font-weight:700;padding:3px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.empty{background:var(--panel);border:1px dashed var(--line);border-radius:10px;padding:20px;text-align:center;color:var(--muted);margin-top:12px}
.foot{margin-top:44px;padding-top:20px;border-top:1px solid var(--line-soft)}
.covlist{margin:0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:9px}
.covlist li{font-size:13px;color:var(--muted);line-height:1.55;padding-left:18px;position:relative}
.covlist li::before{content:"•";position:absolute;left:2px;color:var(--faint)}
.contract{margin-top:18px;font-size:13px;color:var(--faint);line-height:1.6;border-left:3px solid var(--line);padding:2px 0 2px 14px}
@media (max-width:560px){.wrap{padding:26px 15px 56px}.synopsis h1{font-size:19px}.card{padding:14px 15px}.card h3{flex-basis:100%}}
@media print{.card,.synopsis,.axis,.ev,.hub{box-shadow:none;break-inside:avoid}a{color:inherit;text-decoration:none}}
"""


def _mark_line(text: str, col) -> str:
    esc = _esc(text)
    if not col:
        return esc
    s, e = col
    if 0 <= s <= e <= len(text):
        return _esc(text[:s]) + "<mark>" + _esc(text[s:e]) + "</mark>" + _esc(text[e:])
    return esc


def _evidence_html(ev_list, obs_by_id) -> str:
    rows = []
    for ev in ev_list:
        if isinstance(ev, dict) and ev.get("obs") in obs_by_id:
            o = obs_by_id[ev["obs"]]
            loc = o["location"]
            where = _esc(loc.get("path") or "?")
            if loc.get("line"):
                where += f":{_esc(loc['line'])}"
            atom = f"<span class='atom'>{_esc(o.get('atom'))}</span>"
            snip = (o.get("evidence") or {}).get("snippet")
            body = ""
            if snip:
                lines = []
                for ln in snip["lines"]:
                    n = f"<span class='ln'>{ln['n']:>4}</span> "
                    txt = _mark_line(ln["text"], ln.get("col")) if ln.get("match") else _esc(ln["text"])
                    cls = " class='hit'" if ln.get("match") else ""
                    lines.append(f"<span{cls}>{n}{txt}</span>")
                body = "<pre>" + "\n".join(lines) + "</pre>"
            rows.append(f"<div class='ev'><div class='evhead'><span class='loc'>{where}</span>{atom}</div>{body}</div>")
        elif isinstance(ev, dict) and ev.get("path"):
            note = f" — {_esc(ev['note'])}" if ev.get("note") else ""
            rows.append(f"<div class='ev'><div class='note'><code>{_esc(ev['path'])}</code>{note}</div></div>")
    return "<div class='block'><div class='h'>Evidence</div><div class='evidence'>" + "".join(rows) + "</div></div>" if rows else ""


def _card(f: dict, obs_by_id) -> str:
    lens = f["lens"]
    chips = []
    frag = f.get("fragility")
    if frag:                                     # brittle only — capabilities/decisions have no rating
        chips.append(f"<span class='chip frag-{_esc(frag)}'><span class='k'>fragility</span> {_esc(frag)}</span>")
    conf = f.get("confidence")
    if isinstance(conf, (int, float)):
        w = max(0, min(100, round(conf * 100)))
        chips.append(f"<span class='chip'><span class='meter'><span class='track'>"
                     f"<span class='fill' style='width:{w}%'></span></span></span>"
                     f"<span class='k'>confidence</span> {_conf_pct(conf)}</span>")
    if f.get("composition"):
        chips.append(f"<span class='chip comp'>{_esc(f['composition'])}</span>")
    p = [f"<article class='card {lens}'>",
         "<div class='top'>", f"<h3>{_esc(f['title'])}</h3>",
         "<div class='chips'>" + "".join(chips) + "</div>", "</div>",
         f"<p class='claim'>{_esc(f['claim'])}</p>"]
    rev = f.get("review")
    if rev:
        vcls = {"confirm": "confirm", "refine": "refine", "refute": "refute",
                "needs_human": "needs"}.get(rev.get("verdict"), "needs")
        conf = rev.get("reviewed_confidence")
        cons = (f"<div class='rev-cons'>{_esc(rev['consideration'])}</div>"
                if rev.get("consideration") else "")
        rel = (f"<div class='rev-rel'>↳ toward your goal: {_esc(rev['relevance'])}</div>"
               if (rev.get("relevance") or "").strip() else "")
        p.append(
            "<div class='review'>"
            f"<div class='rev-h'><span class='rev-badge {vcls}'>{_esc(rev.get('verdict'))}</span>"
            f"<span class='rev-label'>reviewer</span>"
            f"<span class='rev-conf'>confidence now {_conf_pct(conf)}</span></div>"
            f"<div class='rev-exp'>{_esc(rev.get('explanation'))}</div>{cons}{rel}</div>")
    if f.get("disproof"):
        p.append("<div class='block'><div class='h'>What would disprove this</div><ul class='disproof'>"
                 + "".join(f"<li>{_esc(d)}</li>" for d in f["disproof"]) + "</ul></div>")
    p.append(_evidence_html(f.get("evidence", []), obs_by_id))
    p.append("</article>")
    return "".join(p)


def render_html(a: dict) -> str:
    summ = a.get("summary") or {}
    target = (a.get("target") or {}).get("path", "")
    obs_by_id = {o["id"]: o for o in (a.get("observations") or [])}
    findings = a.get("findings") or []

    p: list[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Codebase understanding</title>",
        f"<style>{_CSS}</style></head><body><main class='wrap'>",
        "<div class='masthead'><span class='kicker'>Codebase understanding</span>",
    ]
    if target:
        p.append(f"<span class='target'>{_esc(target)}</span>")
    p.append("</div>")

    ov = a.get("overview") or {}
    ov_text = ov.get("text") or (a.get("synopsis") or {}).get("text", "")
    kicker = f"<div class='ov-kind'>{_esc(ov['kind'])}</div>" if ov.get("kind") else ""
    purpose_html = ""
    if ov.get("purpose"):
        purpose_html = ("<div class='ov-purpose'><span class='ov-plabel'>Purpose · in its own words</span>"
                        f"<p>{_esc(ov['purpose'])}</p></div>")
    how = ov.get("howItWorks")
    how_html = ""
    if how:
        how_html = ("<div class='ov-how'><span class='ov-plabel'>How it does that</span>"
                    f"<p>{_esc(how)}</p></div>")
    p.append("<section class='synopsis' id='overview'><h1>Overview</h1>"
             f"{kicker}{purpose_html}{how_html}<p class='ov-facts'>{_esc(ov_text)}</p></section>")

    goal = a.get("goal")
    if goal:
        p.append(f"<section class='goal'><span class='goal-lbl'>Goal</span>"
                 f"<span class='goal-text'>{_esc(goal)}</span></section>")

    review = a.get("review")
    if review:
        counts = review.get("counts") or {}
        tally = "".join(f"<span class='t'>{_esc(k)}: {_esc(v)}</span>" for k, v in counts.items() if v)
        model = (review.get("reviewer") or {}).get("model")
        p.append("<section class='overlay'><h2>Agentic review</h2>"
                 f"<div class='sub'>{_esc(review.get('note'))}"
                 + (f" <em>Model: {_esc(model)}.</em>" if model else "")
                 + f"</div><div class='tally'>{tally}</div>")
        relevant = review.get("relevant") or []
        if relevant:
            fmap = {f["id"]: f for f in findings}
            items = []
            for r in relevant:
                ff = fmap.get(r["finding_id"])
                title = _esc(ff["title"]) if ff else _esc(r["finding_id"])
                items.append(f"<li><strong>{title}</strong> — {_esc(r['relevance'])}</li>")
            p.append("<div class='toward'><div class='toward-h'>Toward your goal</div>"
                     f"<ul>{''.join(items)}</ul></div>")
        p.append("</section>")

    langs = summ.get("languages") or {}
    lang_sub = ", ".join(f"{k}" for k in list(langs)[:3]) or "—"
    frag = summ.get("highestFragility")
    p.append("<div class='axes'>")
    for lbl, val, sub in [
        ("Files", summ.get("fileCount", 0), lang_sub),
        ("Components", summ.get("componentCount", 0), f"{summ.get('moduleCount', 0)} Python modules"),
        ("Observations", summ.get("atomCount", 0), "capability atoms"),
        ("Findings", summ.get("findingCount", 0),
         f"fragility ↑ {frag}" if frag else "no fragile points"),
    ]:
        p.append(f"<div class='axis'><div class='lbl'>{_esc(lbl)}</div>"
                 f"<div class='val'>{_esc(val)}</div><div class='sub'>{_esc(sub)}</div></div>")
    p.append("</div>")
    p.append("<p class='axes-note'>This is understanding, not security — capabilities and "
             "decisions carry no severity. Only brittle findings carry a fragility rating "
             "(how much a point complicates change), always separate from confidence.</p>")

    caps = summ.get("capabilities") or {}
    if caps:
        p.append("<h2 class='sec' id='capabilities'>Capability profile</h2><div class='caps'>")
        from lucent.atoms import atom_title
        for atom, n in sorted(caps.items(), key=lambda kv: -kv[1]):
            p.append(f"<span class='cap'>{_esc(atom_title(atom))} <span class='n'>{_esc(n)}</span></span>")
        p.append("</div>")

    # TOC
    toc = [("overview", "Overview")]
    if (a.get("composition") or {}).get("components"):
        toc.append(("composition", "Composition"))
    for lens in _LENSES:
        n = summ.get("byLens", {}).get(lens, 0)
        if n:
            toc.append((f"lens-{lens}", f"{_LENS_TITLE[lens]} ({n})"))
    if (a.get("dependencies") or {}).get("dependents"):
        toc.append(("structure", "Structure"))
    toc.append(("coverage", "Coverage"))
    p.append("<nav class='toc'><div class='toc-h'>Contents</div><ul>"
             + "".join(f"<li><a href='#{s}'>{_esc(l)}</a></li>" for s, l in toc) + "</ul></nav>")

    # Composition — how the target is built (components + their dependencies)
    comp = a.get("composition") or {}
    comps = comp.get("components") or []
    if comps and (len(comps) > 1 or comp.get("edges")):
        from lucent.atoms import atom_title as _at
        p.append("<h2 class='sec' id='composition'>Composition "
                 f"<span class='count'>· {len(comps)} components</span></h2>")
        if comp.get("foundations"):
            found = ", ".join(f"<code>{_esc(c)}</code>" for c in comp["foundations"])
            p.append(f"<p class='axes-note'>Foundations others build on: {found}. "
                     "Each card lists a component's size, what it can do, and what it depends on.</p>")
        p.append("<div class='comps'>")
        for c in comps:
            capchips = "".join(f"<span class='ccap'>{_esc(_at(atom))} <span class='n'>{n}</span></span>"
                               for atom, n in list(c["capabilities"].items())[:6])
            deps_line = (f"<div class='cdeps'>depends on "
                         + ", ".join(f"<code>{_esc(d)}</code>" for d in c["dependsOn"]) + "</div>"
                         if c["dependsOn"] else "")
            role = f"<div class='comp-role'>{_esc(c['role'])}</div>" if c.get("role") else ""
            p.append("<div class='comp'>"
                     f"<div class='comp-h'><span class='comp-name'>{_esc(c['name'])}</span>"
                     f"<span class='comp-n'>{_esc(c['moduleCount'])} module(s)</span></div>"
                     + role
                     + (f"<div class='ccaps'>{capchips}</div>" if capchips else "")
                     + deps_line + "</div>")
        p.append("</div>")

    # Findings by lens
    any_findings = False
    for lens in _LENSES:
        group = [f for f in findings if f["lens"] == lens]
        if not group:
            continue
        any_findings = True
        group = _sorted_group(group)
        p.append(f"<div class='lensgroup' id='lens-{lens}'>")
        p.append(f"<div class='lenshead'><span class='bar {lens}'></span>"
                 f"<span class='name {lens}'>{_esc(_LENS_TITLE[lens])}</span>"
                 f"<span class='n'>· {len(group)}</span></div>")
        p.append(f"<p class='lensblurb'>{_esc(_LENS_BLURB[lens])}</p>")
        for f in group:
            p.append(_card(f, obs_by_id))
        p.append("</div>")
    if not any_findings:
        p.append("<div class='empty'>No findings — lucent observed no interpretable behaviour "
                 "or structure in this target.</div>")

    # Structure — dependency hubs
    dependents = (a.get("dependencies") or {}).get("dependents") or {}
    if dependents:
        ranked = sorted(dependents.items(), key=lambda kv: -len(kv[1]))[:8]
        top = len(ranked[0][1]) if ranked else 1
        p.append("<h2 class='sec' id='structure'>Structure <span class='count'>· dependency hubs</span></h2>")
        p.append("<div class='struct'>")
        for mod, dents in ranked:
            w = round(len(dents) / top * 100)
            p.append(f"<div class='hub'><span class='mod'>{_esc(mod)}</span>"
                     f"<span class='track'><span class='fill' style='width:{w}%'></span></span>"
                     f"<span class='cnt'>{len(dents)} ←</span></div>")
        p.append("</div>")

    # Coverage + contract
    p.append("<footer class='foot'>")
    cov = a.get("coverage") or {}
    if cov.get("notes"):
        p.append("<h2 class='sec' id='coverage'>Coverage</h2><ul class='covlist'>"
                 + "".join(f"<li>{_esc(n)}</li>" for n in cov["notes"]) + "</ul>")
    p.append(f"<p class='contract'>{_esc((a.get('contract') or {}).get('note', ''))}</p>")
    p.append("</footer></main></body></html>")
    return "".join(p)
