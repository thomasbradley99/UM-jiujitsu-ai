"""Render a side-by-side HTML report comparing two prompt versions.

Reads `mubit/outputs/runs/<run_id>/<prompt_version_id>/report.json` (which is
`asdict(VLM-gemini/eval/metrics.py:Report)` written by mubit.cli.cmd_eval)
for two distinct prompt versions and produces report.html in the run dir.

The report is the demo visual: per-event rows on each side colored by status
(matched / missed_gt / hallucination), with a metrics table at the top.
"""

from __future__ import annotations

import json
from pathlib import Path

from mubit.config import OUTPUTS_DIR


HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>MuBit Submission Detection — {run_id}</title>
<style>
  body {{ font-family: ui-monospace, Menlo, monospace; background:#0b0c10; color:#e6e6e6; margin: 24px; max-width: 1400px; }}
  h1 {{ margin: 0 0 8px 0; font-weight: 600; }}
  h2 {{ margin: 24px 0 8px 0; font-weight: 500; color: #9ad; }}
  h3 {{ margin: 12px 0 8px 0; font-weight: 500; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #2a2d36; padding: 6px 12px; text-align: left; }}
  th {{ background: #16181f; }}
  td.delta-pos {{ color: #5cb85c; }}
  td.delta-neg {{ color: #d9534f; }}
  td.delta-zero {{ color: #888; }}
  .row {{ display: flex; gap: 24px; }}
  .col {{ flex: 1; min-width: 0; }}
  .ev {{ border: 1px solid #2a2d36; border-left-width: 4px; padding: 8px 12px; margin: 8px 0; border-radius: 4px; background:#11131a; font-size: 13px; }}
  .ev.matched {{ border-left-color: #5cb85c; }}
  .ev.hallucination {{ border-left-color: #d9534f; }}
  .ev.missed_gt {{ border-left-color: #f0ad4e; background:#1c1814; }}
  .ts {{ color: #9ad; font-weight: 600; }}
  .tag {{ display:inline-block; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-left: 6px; }}
  .tag.matched {{ background:#1f3d20; color:#9c9; }}
  .tag.hallucination {{ background:#3a1f1f; color:#f99; }}
  .tag.missed_gt {{ background:#3a2f1f; color:#fc9; }}
  .tick-ok {{ color: #5cb85c; }}
  .tick-bad {{ color: #d9534f; }}
  small {{ color: #888; }}
</style></head>
<body>
<h1>MuBit Submission Detection — {run_id}</h1>
<div><small>Side-by-side comparison of two prompt versions on the same fight, against the same GT.</small></div>

<h2>Metrics</h2>
{metrics_table}

<h2>Per-event detail</h2>
<div class="row">
  <div class="col">
    <h3>{label_a} <small>(prompt {ver_a})</small></h3>
    {events_a}
  </div>
  <div class="col">
    <h3>{label_b} <small>(prompt {ver_b})</small></h3>
    {events_b}
  </div>
</div>
</body></html>
"""


def _pct(x):
    if x is None:
        return "—"
    return f"{x * 100:.0f}%"


def _f(x, suffix=""):
    if x is None:
        return "—"
    return f"{x:.2f}{suffix}"


def _delta_cell(a, b, *, higher_is_better=True, pct=False):
    """HTML <td> with arrow + colour for the b-vs-a delta."""
    if a is None or b is None:
        return "<td>—</td>"
    delta = b - a
    if abs(delta) < 1e-9:
        cls = "delta-zero"
        arrow = "→"
    elif (delta > 0) == higher_is_better:
        cls = "delta-pos"
        arrow = "▲"
    else:
        cls = "delta-neg"
        arrow = "▼"
    if pct:
        return f'<td class="{cls}">{arrow} {delta * 100:+.0f}pp</td>'
    return f'<td class="{cls}">{arrow} {delta:+.2f}</td>'


def _metrics_table(report_a: dict, report_b: dict, label_a: str, label_b: str) -> str:
    rows: list[tuple[str, str, str, str]] = []

    def row(name, key, *, fmt=lambda x: str(x), pct_delta=False, higher_is_better=True):
        a, b = report_a.get(key), report_b.get(key)
        delta = _delta_cell(a, b, higher_is_better=higher_is_better, pct=pct_delta)
        rows.append((name, fmt(a), fmt(b), delta))

    row("GT count", "n_gt")
    row("Predictions", "n_pred")
    row("Matched (TP)", "matched")
    row("Hallucinations (FP)", "hallucinations", higher_is_better=False)
    row("Recall", "sub_recall", fmt=_pct, pct_delta=True)
    row("Precision", "sub_precision", fmt=_pct, pct_delta=True)
    row("F1", "f1", fmt=_pct, pct_delta=True)
    row("Technique accuracy", "technique_acc", fmt=_pct, pct_delta=True)
    row("Submitter accuracy", "submitter_acc", fmt=_pct, pct_delta=True)
    row("Timestamp MAE", "timestamp_mae", fmt=lambda x: _f(x, "s"), higher_is_better=False)

    body = "".join(
        f"<tr><td>{name}</td><td>{a}</td><td>{b}</td>{delta}</tr>"
        for name, a, b, delta in rows
    )
    return (
        f"<table><tr><th>Metric</th><th>{label_a}</th><th>{label_b}</th><th>Δ (b vs a)</th></tr>"
        f"{body}</table>"
    )


def _render_event(d: dict) -> str:
    status = d.get("status", "matched")
    ts_value = d.get("pred_t") if d.get("pred_t") is not None else d.get("gt_t")
    ts = "—" if ts_value is None else f"{ts_value:.1f}s"
    tag = f'<span class="tag {status}">{status.upper()}</span>'

    if status == "matched":
        tick_t = (
            '<span class="tick-ok">✓</span>' if d.get("technique_correct")
            else '<span class="tick-bad">✗</span>'
        )
        tick_s = (
            '<span class="tick-ok">✓</span>' if d.get("submitter_correct")
            else '<span class="tick-bad">✗</span>'
        )
        body = (
            f"<b>{d.get('pred_technique')}</b> "
            f"(GT: <i>{d.get('gt_technique')}</i>) "
            f"Δt={d.get('delta_t'):+.1f}s &nbsp; "
            f"tech {tick_t}  attacker {tick_s}"
        )
    elif status == "hallucination":
        body = (
            f"<b>{d.get('pred_technique')}</b> hallucinated "
            f"(attacker: {d.get('pred_submitter_raw') or '—'})"
        )
    else:  # missed_gt
        body = (
            f"<b>{d.get('gt_technique')}</b> missed "
            f"(submitter: {d.get('gt_submitter') or '—'})"
        )

    return f'<div class="ev {status}"><span class="ts">{ts}</span> {tag}<br>{body}</div>'


def _events_html(report: dict) -> str:
    details = report.get("details", []) or []
    if not details:
        return "<i>no events</i>"
    # Sort by whichever timestamp is available, missed_gt by gt_t.
    details_sorted = sorted(
        details,
        key=lambda d: (d.get("pred_t") if d.get("pred_t") is not None else d.get("gt_t")) or 0.0,
    )
    return "\n".join(_render_event(d) for d in details_sorted)


def _load_report(run_id: str, version_id: str) -> dict:
    path = OUTPUTS_DIR / "runs" / run_id / version_id / "report.json"
    if not path.exists():
        raise SystemExit(
            f"missing {path}. Run `python -m mubit.cli eval` for prompt version {version_id}."
        )
    return json.loads(path.read_text())


def render(
    run_id: str,
    version_a: str,
    version_b: str,
    *,
    label_a: str = "v1",
    label_b: str = "v2",
) -> Path:
    report_a = _load_report(run_id, version_a)
    report_b = _load_report(run_id, version_b)

    html = HTML_TEMPLATE.format(
        run_id=run_id,
        metrics_table=_metrics_table(report_a, report_b, label_a, label_b),
        label_a=label_a,
        label_b=label_b,
        ver_a=version_a[:12],
        ver_b=version_b[:12],
        events_a=_events_html(report_a),
        events_b=_events_html(report_b),
    )
    out = OUTPUTS_DIR / "runs" / run_id / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"Wrote {out}")
    return out
