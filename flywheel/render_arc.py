"""Render the full N-iteration flywheel arc as a single HTML page.

Reads:
  - flywheel/outputs/loop_arc.json                             (per-iteration metrics)
  - flywheel/outputs/runs/<run_id>/<pv-...>/domain_rules.md    (prompt body for each version)
  - flywheel/outputs/runs/<run_id>/<pv-...>/report.json        (per-event TP/FP/FN detail)
  - optional terminal log from the loop run                    (rewriter summaries + diffs)

Writes:
  - flywheel/outputs/arc_report.html
  - flywheel/outputs/optimizer_summaries.json   (so re-renders don't need the log)

Usage:
  python -m flywheel.render_arc                       # use existing summaries.json
  python -m flywheel.render_arc --log path/to/log.txt # parse a fresh log first
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from datetime import datetime
from pathlib import Path

from flywheel.config import OUTPUTS_DIR, DEFAULT_GAME, ANALYZE_MODEL


SUMMARIES_PATH = OUTPUTS_DIR / "optimizer_summaries.json"
ARC_PATH = OUTPUTS_DIR / "loop_arc.json"
DEFAULT_RUN_ID = "verify:video"


# ---------------------------------------------------------------------------
# Log parsing — extract "Optimization summary" blocks keyed by candidate id
# ---------------------------------------------------------------------------

_SUMMARY_RE = re.compile(
    r"Optimization summary\s+\(confidence=([\d.]+),\s+activated=\w+\)\s*\n"
    r"={5,}\n"
    r"(?P<reason>.*?)\n"
    r"={5,}\n"
    r"\n"
    r"Diff \(active (?P<active>pv-[a-f0-9-]+).*?\s+candidate (?P<candidate>pv-[a-f0-9-]+)\)\s*:\n"
    r"(?P<diff>.*?)\n\n",
    re.DOTALL,
)


def parse_log(path: Path) -> dict[str, dict]:
    text = path.read_text(errors="ignore")
    out: dict[str, dict] = {}
    for m in _SUMMARY_RE.finditer(text):
        cand = m.group("candidate").strip()
        out[cand] = {
            "confidence": float(m.group(1)),
            "reason": m.group("reason").strip(),
            "active_id": m.group("active").strip(),
            "diff": m.group("diff"),
        }
    return out


# ---------------------------------------------------------------------------
# Disk loading
# ---------------------------------------------------------------------------

def _load_arc() -> list[dict]:
    return json.loads(ARC_PATH.read_text())


def _load_prompt(run_id: str, pv: str) -> str:
    p = OUTPUTS_DIR / "runs" / run_id / pv / "domain_rules.md"
    return p.read_text() if p.exists() else "(prompt file missing)"


def _load_report(run_id: str, pv: str) -> dict:
    p = OUTPUTS_DIR / "runs" / run_id / pv / "report.json"
    return json.loads(p.read_text()) if p.exists() else {}


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def _delta_pp(prev, cur):
    if prev is None or cur is None:
        return ""
    d = (cur - prev) * 100
    if abs(d) < 0.5:
        return f'<span class="d zero">→ +0pp</span>'
    cls = "up" if d > 0 else "down"
    return f'<span class="d {cls}">{"▲" if d > 0 else "▼"} {d:+.0f}pp</span>'


def _arc_table(arc: list[dict]) -> str:
    head = "<tr><th>iter</th><th>F1</th><th>Recall</th><th>Precision</th><th>Matched</th><th>Halls</th><th>prompt</th></tr>"
    rows = []
    prev = {"f1": None, "recall": None, "precision": None}
    for i, it in enumerate(arc):
        is_best = it["f1"] == max(x["f1"] for x in arc)
        cls = " class='best'" if is_best else ""
        f1d = _delta_pp(prev["f1"], it["f1"])
        rd = _delta_pp(prev["recall"], it["recall"])
        pd = _delta_pp(prev["precision"], it["precision"])
        rows.append(
            f"<tr{cls}>"
            f"<td><b>v{it['iteration']}</b></td>"
            f"<td>{_pct(it['f1'])} {f1d}</td>"
            f"<td>{_pct(it['recall'])} {rd}</td>"
            f"<td>{_pct(it['precision'])} {pd}</td>"
            f"<td>{it['n_matched']}/{it['n_gt']}</td>"
            f"<td>{it['n_hallucinations']}</td>"
            f"<td><code>{it['prompt_version_id'][:12]}…</code></td>"
            f"</tr>"
        )
        prev = it
    return f"<table class='arc'><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>"


def _sparkline(arc: list[dict]) -> str:
    # 3 lines: F1 (green), Recall (blue), Precision (orange)
    w, h, pad = 720, 200, 28
    n = len(arc)
    if n < 2:
        return ""
    xs = [pad + i * (w - 2 * pad) / (n - 1) for i in range(n)]

    def line(key, color):
        ys = [pad + (1 - it[key]) * (h - 2 * pad) for it in arc]
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        pts = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"/>'
            for x, y in zip(xs, ys)
        )
        return f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{d}"/>{pts}'

    grid = ""
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = pad + (1 - v) * (h - 2 * pad)
        grid += f'<line x1="{pad}" y1="{y:.1f}" x2="{w - pad}" y2="{y:.1f}" stroke="#222" stroke-dasharray="2,3"/>'
        grid += f'<text x="6" y="{y + 4:.1f}" fill="#666" font-size="11">{int(v*100)}%</text>'
    labels = ""
    for i, x in enumerate(xs):
        labels += f'<text x="{x:.1f}" y="{h - 8}" fill="#888" font-size="11" text-anchor="middle">v{i+1}</text>'

    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">'
        f"{grid}"
        f'{line("recall", "#5bc0de")}'
        f'{line("precision", "#f0ad4e")}'
        f'{line("f1", "#5cb85c")}'
        f"{labels}"
        "</svg>"
    )


def _event_card(d: dict) -> str:
    status = d.get("status", "matched")
    ts_value = d.get("pred_t") if d.get("pred_t") is not None else d.get("gt_t")
    ts = "—" if ts_value is None else f"{ts_value:.0f}s"
    if status == "matched":
        tt = "✓" if d.get("technique_correct") else "✗"
        tt_cls = "ok" if d.get("technique_correct") else "bad"
        ss = "✓" if d.get("submitter_correct") else "✗"
        ss_cls = "ok" if d.get("submitter_correct") else "bad"
        body = (
            f"<b>{_esc(str(d.get('pred_technique')))}</b> "
            f"<span class='vs'>vs gt</span> <i>{_esc(str(d.get('gt_technique')))}</i> "
            f"<span class='dt'>Δt={d.get('delta_t', 0):+.0f}s</span> "
            f"<span class='tick {tt_cls}'>{tt}</span> tech "
            f"<span class='tick {ss_cls}'>{ss}</span> sub"
        )
    elif status == "hallucination":
        body = f"<b>{_esc(str(d.get('pred_technique')))}</b> ghost — claimed by {_esc(str(d.get('pred_submitter_raw') or '—'))}"
    else:
        body = f"<b>{_esc(str(d.get('gt_technique')))}</b> missed (gt: {_esc(str(d.get('gt_submitter') or '—'))})"
    return f'<div class="ev {status}"><span class="ts">{ts}</span><span class="tag {status}">{status.replace("_", " ")}</span><span class="body">{body}</span></div>'


def _events_grid(report: dict) -> str:
    details = report.get("details", []) or []
    if not details:
        return "<div class='ev empty'>no events</div>"
    details = sorted(
        details,
        key=lambda d: (d.get("pred_t") if d.get("pred_t") is not None else d.get("gt_t")) or 0.0,
    )
    return "".join(_event_card(d) for d in details)


def _diff_html(prev: str, cur: str) -> str:
    diff = difflib.unified_diff(
        prev.splitlines(), cur.splitlines(),
        fromfile="prev", tofile="cur", lineterm="", n=2,
    )
    rows = []
    for line in diff:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            rows.append(f'<div class="dl add">{_esc(line)}</div>')
        elif line.startswith("-"):
            rows.append(f'<div class="dl rem">{_esc(line)}</div>')
        else:
            rows.append(f'<div class="dl ctx">{_esc(line)}</div>')
    if not rows:
        return "<div class='dl ctx'>(no textual diff)</div>"
    return "".join(rows)


def _iter_card(idx: int, total: int, it: dict, prev_pv: str | None,
               prev_prompt: str, prompt: str, report: dict,
               summary: dict | None) -> str:
    pv = it["prompt_version_id"]
    label = f"v{it['iteration']}"
    badge = ""
    if it["f1"] >= 0.999:
        badge = '<span class="badge gold">PERFECT</span>'
    elif idx > 0 and it["f1"] < total_arc[idx - 1]["f1"]:
        badge = '<span class="badge warn">REGRESSION</span>'

    # Optimizer note for the rewrite that PRODUCED this version (i.e. produced when prev_pv was active)
    optimizer_note = ""
    if summary:
        optimizer_note = (
            f"<details class='opt'><summary>optimizer's note (confidence "
            f"{summary['confidence']:.2f})</summary>"
            f"<div class='reason'>{_esc(summary['reason'])}</div>"
            f"</details>"
        )

    diff_section = ""
    if prev_pv:
        diff_section = (
            f"<details class='diff' open><summary>diff vs v{idx}"
            f" <code>{prev_pv[:12]}… → {pv[:12]}…</code></summary>"
            f"<div class='diff-body'>{_diff_html(prev_prompt, prompt)}</div>"
            f"</details>"
        )

    return (
        f"<section class='iter'>"
        f"<header>"
        f"<h2>{label} {badge}</h2>"
        f"<div class='kv'>"
        f"<span><b>F1</b> {_pct(it['f1'])}</span>"
        f"<span><b>R</b> {_pct(it['recall'])}</span>"
        f"<span><b>P</b> {_pct(it['precision'])}</span>"
        f"<span><b>matched</b> {it['n_matched']}/{it['n_gt']}</span>"
        f"<span><b>halls</b> {it['n_hallucinations']}</span>"
        f"<span class='pv'><code>{pv[:18]}…</code></span>"
        f"</div>"
        f"</header>"
        f"{optimizer_note}"
        f"{diff_section}"
        f"<details class='prompt'><summary>full prompt ({len(prompt)} chars)</summary>"
        f"<pre class='prompt-body'>{_esc(prompt)}</pre></details>"
        f"<div class='events'>{_events_grid(report)}</div>"
        f"</section>"
    )


# Module-level reference used inside _iter_card for arc context
total_arc: list[dict] = []


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  font-family: ui-monospace, Menlo, "SF Mono", monospace;
  background: #0b0c10;
  color: #e6e6e6;
  margin: 0;
  padding: 32px;
  max-width: 1180px;
  margin: 0 auto;
}
h1 { font-size: 26px; margin: 0 0 4px 0; font-weight: 600; letter-spacing: -0.01em; }
h2 { font-size: 18px; margin: 0; font-weight: 600; color: #e6e6e6; }
h3 { font-size: 14px; margin: 24px 0 8px 0; color: #9ad; font-weight: 500; text-transform: uppercase; letter-spacing: 0.08em; }
.sub { color: #8a8d96; margin-bottom: 24px; font-size: 13px; }
.sub code { background: #16181f; padding: 2px 6px; border-radius: 3px; font-size: 12px; }

.hero {
  background: #11131a;
  border: 1px solid #2a2d36;
  border-radius: 8px;
  padding: 20px 24px;
  margin: 16px 0 28px 0;
}
.hero-grid { display: grid; grid-template-columns: 220px 1fr; gap: 28px; align-items: center; }
.big-stat { font-size: 56px; font-weight: 700; line-height: 1; color: #5cb85c; }
.big-stat small { display:block; font-size: 13px; color: #8a8d96; font-weight: 400; margin-top: 6px; letter-spacing: 0.04em; text-transform: uppercase; }
.spark { width: 100%; height: auto; }
ul.legend { list-style: none; padding: 0; margin: 18px 0 0 0; display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: #c8cad1; }
ul.legend li { display: flex; align-items: center; gap: 8px; }
ul.legend .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }

table.arc { border-collapse: collapse; width: 100%; font-size: 13px; margin: 12px 0 32px 0; }
table.arc th, table.arc td { border: 1px solid #2a2d36; padding: 8px 12px; text-align: left; }
table.arc th { background: #16181f; font-weight: 600; color: #9ad; }
table.arc tr.best td { background: #15291a; }
table.arc code { background: #0b0c10; padding: 1px 4px; border-radius: 3px; font-size: 11px; color: #9ad; }
.d { font-size: 11px; margin-left: 6px; }
.d.up { color: #5cb85c; }
.d.down { color: #d9534f; }
.d.zero { color: #666; }

section.iter {
  background: #11131a;
  border: 1px solid #2a2d36;
  border-radius: 8px;
  padding: 20px 24px;
  margin: 16px 0;
}
section.iter > header { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; }
section.iter .kv { display: flex; gap: 18px; font-size: 12px; color: #c8cad1; flex-wrap: wrap; }
section.iter .kv b { color: #9ad; font-weight: 500; margin-right: 4px; }
section.iter .pv code { background: #0b0c10; padding: 2px 6px; border-radius: 3px; color: #888; font-size: 11px; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: 0.04em; margin-left: 10px; vertical-align: middle; }
.badge.gold { background: #2d2308; color: #f0c040; border: 1px solid #604a08; }
.badge.warn { background: #2d1408; color: #e69060; border: 1px solid #6a3010; }

details { margin: 12px 0; border: 1px solid #2a2d36; border-radius: 6px; background: #0e1018; }
details > summary { cursor: pointer; padding: 8px 14px; font-size: 12px; color: #9ad; user-select: none; }
details > summary:hover { background: #16181f; }
details[open] > summary { border-bottom: 1px solid #2a2d36; }
.opt .reason { padding: 12px 14px; color: #c8cad1; font-size: 13px; line-height: 1.5; font-family: -apple-system, system-ui, sans-serif; }
.prompt-body { margin: 0; padding: 14px; font-size: 12px; line-height: 1.5; color: #c8cad1; white-space: pre-wrap; max-height: 480px; overflow: auto; }
.diff-body { padding: 8px 14px; font-size: 12px; line-height: 1.45; }
.dl { white-space: pre-wrap; padding: 1px 6px; border-radius: 2px; font-family: ui-monospace, Menlo, monospace; }
.dl.add { background: #0e2a16; color: #9be7af; border-left: 3px solid #2c8045; padding-left: 8px; margin: 1px 0; }
.dl.rem { background: #2a0e0e; color: #f29a9a; border-left: 3px solid #80302c; padding-left: 8px; margin: 1px 0; text-decoration: line-through; opacity: 0.85; }
.dl.ctx { color: #6a6d78; padding-left: 8px; }

.events { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px; margin-top: 10px; }
.ev { border: 1px solid #2a2d36; border-left-width: 4px; padding: 10px 12px; border-radius: 4px; background: #0e1018; font-size: 12px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ev.matched { border-left-color: #5cb85c; }
.ev.hallucination { border-left-color: #d9534f; }
.ev.missed_gt { border-left-color: #f0ad4e; background: #1c1814; }
.ev .ts { color: #9ad; font-weight: 700; min-width: 38px; }
.ev .tag { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 3px; letter-spacing: 0.04em; text-transform: uppercase; }
.ev .tag.matched { background: #1f3d20; color: #9c9; }
.ev .tag.hallucination { background: #3a1f1f; color: #f99; }
.ev .tag.missed_gt { background: #3a2f1f; color: #fc9; }
.ev .body { flex: 1; min-width: 0; }
.ev .body i { color: #9ad; font-style: normal; }
.ev .vs { color: #666; font-size: 11px; }
.ev .dt { color: #888; font-size: 11px; }
.tick.ok { color: #5cb85c; font-weight: 700; }
.tick.bad { color: #d9534f; font-weight: 700; }

footer { margin: 36px 0 16px 0; padding-top: 20px; border-top: 1px solid #2a2d36; color: #6a6d78; font-size: 12px; line-height: 1.6; }
footer code { color: #9ad; }
"""


def render(run_id: str = DEFAULT_RUN_ID) -> Path:
    arc = _load_arc()
    global total_arc
    total_arc = arc

    summaries: dict[str, dict] = {}
    if SUMMARIES_PATH.exists():
        summaries = json.loads(SUMMARIES_PATH.read_text())

    def _summary_for(pv: str) -> dict | None:
        # Log printed truncated prefixes, arc.json has full UUIDs — match by prefix.
        if pv in summaries:
            return summaries[pv]
        for k, v in summaries.items():
            if pv.startswith(k.rstrip("-")) or k.startswith(pv[: len(k)]):
                return v
        return None

    # Hero numbers
    best = max(arc, key=lambda x: x["f1"])
    first = arc[0]

    # Per-iter cards
    cards = []
    prev_prompt = ""
    prev_pv: str | None = None
    for i, it in enumerate(arc):
        pv = it["prompt_version_id"]
        prompt = _load_prompt(run_id, pv)
        report = _load_report(run_id, pv)
        summary = _summary_for(pv)  # the rewrite that PRODUCED pv lives keyed by pv
        cards.append(
            _iter_card(i, len(arc), it, prev_pv, prev_prompt, prompt, report, summary)
        )
        prev_prompt = prompt
        prev_pv = pv

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Flywheel arc — {run_id} · {ANALYZE_MODEL}</title>
<style>{CSS}</style>
</head>
<body>

<h1>Flywheel arc · <span style="color:#9ad">{run_id}</span></h1>
<div class="sub">
  Self-improving prompt loop · model <code>{ANALYZE_MODEL}</code> · video <code>{DEFAULT_GAME}</code> · rendered {timestamp}
</div>

<section class="hero">
  <div class="hero-grid">
    <div>
      <div class="big-stat">{_pct(best['f1'])}<small>peak F1 · v{best['iteration']}</small></div>
      <div style="margin-top:14px; color:#8a8d96; font-size:12px; line-height:1.7;">
        start v1 → <b style="color:#e6e6e6">{_pct(first['f1'])}</b><br>
        peak v{best['iteration']} → <b style="color:#5cb85c">{_pct(best['f1'])}</b><br>
        Δ <b style="color:#5cb85c">+{(best['f1']-first['f1'])*100:.0f}pp</b> over {len(arc)} iterations
      </div>
      <ul class="legend">
        <li><span class="sw" style="background:#5cb85c"></span>F1</li>
        <li><span class="sw" style="background:#5bc0de"></span>Recall</li>
        <li><span class="sw" style="background:#f0ad4e"></span>Precision</li>
      </ul>
    </div>
    <div>{_sparkline(arc)}</div>
  </div>
</section>

<h3>The arc</h3>
{_arc_table(arc)}

<h3>Per iteration · prompt · diff · events</h3>
{''.join(cards)}

<footer>
<b>Where the data lives</b><br>
This page is rendered from <code>flywheel/outputs/loop_arc.json</code> + per-version <code>domain_rules.md</code> /
<code>report.json</code> in <code>flywheel/outputs/runs/{run_id}/</code>. Optimizer notes parsed from the loop terminal log
into <code>flywheel/outputs/optimizer_summaries.json</code>. Every prompt version and outcome is also versioned in MuBit Console.
<br><br>
Re-render anytime with <code>python -m flywheel.render_arc</code> (or <code>--log path/to/log.txt</code> to refresh optimizer notes).
</footer>
</body>
</html>
"""
    out = OUTPUTS_DIR / "arc_report.html"
    out.write_text(html)
    print(f"Wrote {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the flywheel arc as a single HTML page.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID)
    ap.add_argument("--log", type=Path, default=None,
                    help="Path to a loop terminal log to extract optimizer summaries from.")
    args = ap.parse_args()

    if args.log:
        if not args.log.exists():
            raise SystemExit(f"log not found: {args.log}")
        summaries = parse_log(args.log)
        SUMMARIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARIES_PATH.write_text(json.dumps(summaries, indent=2))
        print(f"Wrote {SUMMARIES_PATH}  ({len(summaries)} entries)")

    render(args.run_id)


if __name__ == "__main__":
    main()
