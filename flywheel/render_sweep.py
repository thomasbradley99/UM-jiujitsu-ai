"""Render an overnight-sweep comparison report from many loop_arc.json files.

Reads:
  flywheel/outputs/sweep/loop_arc_<label>_r<i>.json    (one per replay arc)

Writes:
  flywheel/outputs/sweep/comparison_report.html

Each arc is the per-iteration output of one full N-iteration loop, so the
sweep directory holds N_REPLAYS arcs per seed × len(SEEDS) seeds. This script
groups arcs by their `<label>` token (parsed from the filename), computes
mean ± stddev of F1 / recall / precision per iteration position, and renders
two overlaid trend lines (one per seed) with shaded stddev bands so you can
see — at a glance — whether the optimizer is actually learning beyond noise.

Usage (from repo root, after `scp -r vm:.../sweep ./flywheel/outputs/`):
  python -m flywheel.render_sweep
  python -m flywheel.render_sweep --sweep-dir flywheel/outputs/sweep
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path

from flywheel.config import OUTPUTS_DIR, ANALYZE_MODEL, DEFAULT_GAME


DEFAULT_SWEEP_DIR = OUTPUTS_DIR / "sweep"
ARC_FILENAME_RE = re.compile(r"^loop_arc_(?P<label>.+)_r(?P<replay>\d+)\.json$")

# Distinct hues per seed label. Order matches the order labels are first seen
# (so naive=green, handtuned=blue is the typical default).
SEED_PALETTE = [
    {"line": "#5cb85c", "band": "rgba(92,184,92,0.18)", "name": "green"},
    {"line": "#5bc0de", "band": "rgba(91,192,222,0.18)", "name": "blue"},
    {"line": "#f0ad4e", "band": "rgba(240,173,78,0.18)", "name": "orange"},
    {"line": "#d9534f", "band": "rgba(217,83,79,0.18)", "name": "red"},
    {"line": "#ad8de8", "band": "rgba(173,141,232,0.18)", "name": "purple"},
]

METRIC_KEYS = ("f1", "recall", "precision")


# ---------------------------------------------------------------------------
# Loading + grouping
# ---------------------------------------------------------------------------

def _discover_arcs(sweep_dir: Path) -> dict[str, list[tuple[int, list[dict]]]]:
    """Return {label: [(replay_idx, arc), ...]} sorted by replay_idx."""
    if not sweep_dir.is_dir():
        raise SystemExit(f"sweep dir not found: {sweep_dir}")

    by_label: dict[str, list[tuple[int, list[dict]]]] = {}
    for path in sorted(sweep_dir.glob("loop_arc_*.json")):
        m = ARC_FILENAME_RE.match(path.name)
        if not m:
            continue
        label = m.group("label")
        replay = int(m.group("replay"))
        try:
            arc = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"  skipping {path.name}: invalid JSON ({exc})")
            continue
        if not isinstance(arc, list) or not arc:
            print(f"  skipping {path.name}: empty / not a list")
            continue
        by_label.setdefault(label, []).append((replay, arc))

    for label in by_label:
        by_label[label].sort(key=lambda x: x[0])

    if not by_label:
        raise SystemExit(
            f"no loop_arc_*.json files matched pattern in {sweep_dir}"
        )
    return by_label


def _stats_per_iteration(arcs: list[list[dict]]) -> list[dict]:
    """For each iteration position, compute mean/stddev/min/max across replays."""
    if not arcs:
        return []
    n = min(len(a) for a in arcs)  # in case a replay died early, truncate
    out: list[dict] = []
    for i in range(n):
        row: dict = {"iteration": i + 1, "n_replays": len(arcs)}
        for key in METRIC_KEYS:
            vals = [float(a[i][key]) for a in arcs if a[i].get(key) is not None]
            if not vals:
                row[key] = {"mean": None, "std": None, "min": None, "max": None,
                            "values": []}
                continue
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)  # population
            row[key] = {
                "mean": mean,
                "std": math.sqrt(var),
                "min": min(vals),
                "max": max(vals),
                "values": vals,
            }
        out.append(row)
    return out


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
    return "—" if x is None else f"{x * 100:.1f}%"


def _pct0(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def _pp(x):
    return "—" if x is None else f"{x * 100:+.1f}pp"


def _band_svg(stats: list[dict], series: list[dict], metric: str = "f1") -> str:
    """Overlaid mean lines with stddev bands, one series per seed label."""
    w, h, pad = 760, 240, 36
    # max iter count across series so we can size the x-axis consistently
    n = max(len(s["stats"]) for s in series) if series else 0
    if n < 2:
        return "<div class='sub'>need ≥2 iterations to draw a sparkline</div>"

    def x_of(i, series_n):
        return pad + i * (w - 2 * pad) / (series_n - 1)

    def y_of(v):
        return pad + (1 - v) * (h - 2 * pad)

    # Grid + axis labels
    grid = ""
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = y_of(v)
        grid += (
            f'<line x1="{pad}" y1="{y:.1f}" x2="{w - pad}" y2="{y:.1f}" '
            f'stroke="#222" stroke-dasharray="2,3"/>'
            f'<text x="6" y="{y + 4:.1f}" fill="#666" font-size="11">'
            f'{int(v*100)}%</text>'
        )
    x_labels = ""
    for i in range(n):
        x = x_of(i, n)
        x_labels += (
            f'<text x="{x:.1f}" y="{h - 8}" fill="#888" font-size="11" '
            f'text-anchor="middle">v{i+1}</text>'
        )

    # One band + line per series
    paths = ""
    for series_idx, s in enumerate(series):
        col = SEED_PALETTE[series_idx % len(SEED_PALETTE)]
        rows = s["stats"]
        if len(rows) < 2:
            continue

        # Stddev band (mean ± std, clipped to [0, 1])
        upper, lower = [], []
        for i, r in enumerate(rows):
            m = r[metric]["mean"]
            sd = r[metric]["std"] or 0.0
            if m is None:
                continue
            x = x_of(i, n)
            upper.append((x, y_of(min(1.0, m + sd))))
            lower.append((x, y_of(max(0.0, m - sd))))
        if upper:
            band_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in upper) + " " + " ".join(
                f"{x:.1f},{y:.1f}" for x, y in reversed(lower)
            )
            paths += f'<polygon points="{band_pts}" fill="{col["band"]}" stroke="none"/>'

        # Mean line + dots
        mean_pts = []
        for i, r in enumerate(rows):
            m = r[metric]["mean"]
            if m is None:
                continue
            mean_pts.append((x_of(i, n), y_of(m)))
        if mean_pts:
            d = " ".join(f"{x:.1f},{y:.1f}" for x, y in mean_pts)
            paths += (
                f'<polyline fill="none" stroke="{col["line"]}" '
                f'stroke-width="2.5" points="{d}"/>'
            )
            for x, y in mean_pts:
                paths += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{col["line"]}"/>'

    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f"{grid}{paths}{x_labels}"
        "</svg>"
    )


def _verdict_block(label: str, stats: list[dict], color: str) -> str:
    """One-liner: did this seed actually improve over the arc?"""
    if len(stats) < 2:
        return ""
    first = stats[0]["f1"]
    last = stats[-1]["f1"]
    best = max(stats, key=lambda r: r["f1"]["mean"] or -1)

    if first["mean"] is None or last["mean"] is None:
        return ""

    delta = last["mean"] - first["mean"]
    pooled_std = math.sqrt(((first["std"] or 0) ** 2 + (last["std"] or 0) ** 2) / 2)
    # Crude effect-size: how many "noise units" of improvement
    z = delta / pooled_std if pooled_std > 1e-9 else float("inf") if delta > 0 else 0.0

    if z >= 1.5:
        verdict, vc = "learning above noise", "#5cb85c"
    elif z >= 0.5:
        verdict, vc = "trending up (within noise)", "#f0ad4e"
    elif z <= -0.5:
        verdict, vc = "regressing", "#d9534f"
    else:
        verdict, vc = "noise — no signal", "#888"

    return (
        f'<div class="verdict">'
        f'<span class="vlabel" style="color:{color}">{_esc(label)}</span>'
        f'<span class="varrow">v1 <b>{_pct(first["mean"])}</b> '
        f'(±{_pct0(first["std"])}) → '
        f'v{stats[-1]["iteration"]} <b>{_pct(last["mean"])}</b> '
        f'(±{_pct0(last["std"])})</span>'
        f'<span class="vdelta" style="color:{vc}">Δ {_pp(delta)} · '
        f'{z:+.1f}σ · {verdict}</span>'
        f'<span class="vbest">peak v{best["iteration"]}: '
        f'<b>{_pct(best["f1"]["mean"])}</b> ± {_pct0(best["f1"]["std"])}</span>'
        f"</div>"
    )


def _stats_table(label: str, stats: list[dict], color: str) -> str:
    head = (
        "<tr>"
        "<th>iter</th>"
        "<th>F1 mean ± std</th><th>min/max</th>"
        "<th>Recall mean ± std</th>"
        "<th>Precision mean ± std</th>"
        "<th>n</th>"
        "</tr>"
    )
    rows = []
    best_mean = max((r["f1"]["mean"] for r in stats if r["f1"]["mean"] is not None),
                    default=None)
    for r in stats:
        f1 = r["f1"]; rc = r["recall"]; pr = r["precision"]
        is_best = best_mean is not None and f1["mean"] == best_mean
        cls = " class='best'" if is_best else ""
        rows.append(
            f"<tr{cls}>"
            f"<td><b>v{r['iteration']}</b></td>"
            f"<td>{_pct(f1['mean'])} ± {_pct0(f1['std'])}</td>"
            f"<td><span class='mm'>{_pct0(f1['min'])}/{_pct0(f1['max'])}</span></td>"
            f"<td>{_pct(rc['mean'])} ± {_pct0(rc['std'])}</td>"
            f"<td>{_pct(pr['mean'])} ± {_pct0(pr['std'])}</td>"
            f"<td>{r['n_replays']}</td>"
            f"</tr>"
        )
    return (
        f'<h4 style="color:{color}">{_esc(label)} · per-iteration aggregates</h4>'
        f'<table class="arc"><thead>{head}</thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _replays_table(label: str, replays: list[tuple[int, list[dict]]],
                   color: str) -> str:
    if not replays:
        return ""
    n = min(len(arc) for _, arc in replays)
    head = (
        "<tr><th>replay</th>"
        + "".join(f"<th>v{i+1}</th>" for i in range(n))
        + "<th>peak</th></tr>"
    )
    rows = []
    for replay_idx, arc in replays:
        cells = []
        peak = max(it["f1"] for it in arc[:n]) if arc else 0
        for i in range(n):
            f1 = arc[i]["f1"]
            cell = _pct0(f1)
            if f1 == peak:
                cells.append(f"<td class='peak'>{cell}</td>")
            else:
                cells.append(f"<td>{cell}</td>")
        rows.append(
            f"<tr><td><b>r{replay_idx}</b></td>"
            f"{''.join(cells)}"
            f"<td><b>{_pct0(peak)}</b></td></tr>"
        )
    return (
        f'<h4 style="color:{color}">{_esc(label)} · per-replay F1 trajectories</h4>'
        f'<table class="arc replays"><thead>{head}</thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


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
  padding: 32px;
  max-width: 1180px;
  margin: 0 auto;
}
h1 { font-size: 26px; margin: 0 0 4px 0; font-weight: 600; letter-spacing: -0.01em; }
h3 { font-size: 14px; margin: 28px 0 8px 0; color: #9ad; font-weight: 500;
     text-transform: uppercase; letter-spacing: 0.08em; }
h4 { font-size: 13px; margin: 20px 0 6px 0; font-weight: 600; }
.sub { color: #8a8d96; margin-bottom: 24px; font-size: 13px; }
.sub code { background: #16181f; padding: 2px 6px; border-radius: 3px; font-size: 12px; }

.hero {
  background: #11131a;
  border: 1px solid #2a2d36;
  border-radius: 8px;
  padding: 20px 24px;
  margin: 16px 0 28px 0;
}

ul.legend { list-style: none; padding: 0; margin: 14px 0 0 0;
            display: flex; gap: 18px; font-size: 12px; color: #c8cad1;
            flex-wrap: wrap; }
ul.legend li { display: flex; align-items: center; gap: 8px; }
ul.legend .sw { display: inline-block; width: 14px; height: 14px;
                border-radius: 3px; }

.metric-tabs { display: flex; gap: 6px; margin: 8px 0 10px 0; }
.metric-tabs .tab {
  background: #16181f; border: 1px solid #2a2d36; color: #c8cad1;
  padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 600;
  letter-spacing: 0.04em; text-transform: uppercase;
}
.metric-tabs .tab.f1 { color: #5cb85c; border-color: #2c4a30; }
.metric-tabs .tab.recall { color: #5bc0de; border-color: #1f4c5d; }
.metric-tabs .tab.precision { color: #f0ad4e; border-color: #5a4220; }

.spark { width: 100%; height: auto; }

.verdict {
  background: #0e1018;
  border: 1px solid #2a2d36;
  border-left-width: 4px;
  border-radius: 6px;
  padding: 12px 16px;
  margin: 8px 0;
  display: grid;
  grid-template-columns: 140px 1fr auto auto;
  gap: 14px;
  align-items: center;
  font-size: 13px;
}
.verdict .vlabel { font-weight: 700; letter-spacing: 0.04em;
                   text-transform: uppercase; }
.verdict .varrow { color: #c8cad1; }
.verdict .varrow b { color: #e6e6e6; }
.verdict .vdelta { font-weight: 700; font-size: 12px; }
.verdict .vbest { color: #888; font-size: 12px; }
.verdict .vbest b { color: #c8cad1; }

table.arc { border-collapse: collapse; width: 100%; font-size: 13px;
            margin: 8px 0 16px 0; }
table.arc th, table.arc td { border: 1px solid #2a2d36; padding: 7px 10px;
                              text-align: left; }
table.arc th { background: #16181f; font-weight: 600; color: #9ad; }
table.arc tr.best td { background: #15291a; }
table.arc .mm { color: #888; font-size: 11px; }
table.arc.replays td { text-align: center; font-variant-numeric: tabular-nums; }
table.arc.replays td.peak { background: #15291a; color: #9be7af; font-weight: 700; }
table.arc.replays th:first-child, table.arc.replays td:first-child { text-align: left; }

.section {
  background: #11131a;
  border: 1px solid #2a2d36;
  border-radius: 8px;
  padding: 20px 24px;
  margin: 16px 0;
}

footer { margin: 36px 0 16px 0; padding-top: 20px;
         border-top: 1px solid #2a2d36; color: #6a6d78; font-size: 12px;
         line-height: 1.6; }
footer code { color: #9ad; }
"""


def render(sweep_dir: Path) -> Path:
    by_label = _discover_arcs(sweep_dir)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build the per-seed series in the order labels were first discovered.
    series = []
    for label, replays in by_label.items():
        arcs = [arc for _, arc in replays]
        series.append({
            "label": label,
            "replays": replays,
            "arcs": arcs,
            "stats": _stats_per_iteration(arcs),
        })

    # Hero metric panels: F1, Recall, Precision side-by-side
    hero_charts = "".join(
        f'<div class="metric-tabs">'
        f'<span class="tab {m}">{m.upper()} mean ± stddev across replays</span>'
        f'</div>'
        f'{_band_svg(None, series, m)}'
        for m in METRIC_KEYS
    )

    # Legend
    legend_items = []
    for i, s in enumerate(series):
        col = SEED_PALETTE[i % len(SEED_PALETTE)]
        legend_items.append(
            f'<li><span class="sw" style="background:{col["line"]}"></span>'
            f'<b>{_esc(s["label"])}</b> · '
            f'{len(s["replays"])} replays × {len(s["arcs"][0])} iters</li>'
        )
    legend = f'<ul class="legend">{"".join(legend_items)}</ul>'

    # Verdict cards
    verdicts = "".join(
        _verdict_block(s["label"], s["stats"],
                       SEED_PALETTE[i % len(SEED_PALETTE)]["line"])
        for i, s in enumerate(series)
    )

    # Per-seed tables
    tables = "".join(
        _stats_table(s["label"], s["stats"],
                     SEED_PALETTE[i % len(SEED_PALETTE)]["line"])
        + _replays_table(s["label"], s["replays"],
                         SEED_PALETTE[i % len(SEED_PALETTE)]["line"])
        for i, s in enumerate(series)
    )

    # Inputs summary
    n_total = sum(len(s["replays"]) for s in series)
    iters_per_arc = (
        f"{series[0]['stats'][-1]['iteration']}"
        if series and series[0]["stats"] else "?"
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Flywheel sweep · seed comparison</title>
<style>{CSS}</style>
</head>
<body>

<h1>Flywheel sweep · seed comparison</h1>
<div class="sub">
  Variance-aware comparison across <b>{n_total}</b> replay arcs ·
  {len(series)} seeds × ~{iters_per_arc} iterations each ·
  model <code>{ANALYZE_MODEL}</code> · video <code>{DEFAULT_GAME}</code> ·
  rendered {timestamp}
</div>

<section class="hero">
  {legend}
  {hero_charts}
</section>

<h3>Did the optimizer learn?</h3>
<div class="section">
  {verdicts}
  <div class="sub" style="margin-top:14px">
    σ score = (mean<sub>final</sub> − mean<sub>v1</sub>) / pooled stddev. Roughly:
    ≥1.5σ = signal above noise, 0.5–1.5σ = trending up but inside noise,
    ≤−0.5σ = regressing.
  </div>
</div>

<h3>Per-seed numbers</h3>
<div class="section">
  {tables}
</div>

<footer>
<b>Where the data lives</b><br>
Rendered from <code>{sweep_dir}/loop_arc_*.json</code>. Filename pattern
<code>loop_arc_&lt;label&gt;_r&lt;i&gt;.json</code> determines the seed group
and replay index. Means are arithmetic, stddev is population stddev across
replays at each iteration position.<br><br>
Re-render anytime with <code>python -m flywheel.render_sweep
[--sweep-dir flywheel/outputs/sweep]</code>.
</footer>
</body>
</html>
"""
    out = sweep_dir / "comparison_report.html"
    out.write_text(html)
    print(f"Wrote {out}")
    print(f"  seeds:   {', '.join(s['label'] for s in series)}")
    print(f"  replays: {', '.join(str(len(s['replays'])) for s in series)}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Render variance-aware comparison report from a sweep.")
    ap.add_argument(
        "--sweep-dir",
        type=Path,
        default=DEFAULT_SWEEP_DIR,
        help=f"Directory of loop_arc_*.json files (default: {DEFAULT_SWEEP_DIR})",
    )
    args = ap.parse_args()
    render(args.sweep_dir)


if __name__ == "__main__":
    main()
