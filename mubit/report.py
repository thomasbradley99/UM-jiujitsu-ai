"""Render a side-by-side HTML report comparing two prompt versions.

Reads outputs/runs/<run_id>/predicted.json + matched.json + metrics.json
for two distinct prompt_version_ids and produces report.html.

The report is the visual demo: left column is v1 events, right column is
the events under the new prompt, with per-event status (TP / FP / FN) color-coded
and a metrics table at the top.
"""

from __future__ import annotations

import json
from pathlib import Path

from mubit.config import OUTPUTS_DIR


HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>MuBit Submission Detection — {run_id}</title>
<style>
  body {{ font-family: ui-monospace, Menlo, monospace; background:#0b0c10; color:#e6e6e6; margin: 24px; }}
  h1 {{ margin: 0 0 8px 0; font-weight: 600; }}
  h2 {{ margin: 24px 0 8px 0; font-weight: 500; color: #9ad; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #2a2d36; padding: 6px 12px; text-align: left; }}
  th {{ background: #16181f; }}
  .row {{ display: flex; gap: 24px; }}
  .col {{ flex: 1; min-width: 0; }}
  .ev {{ border: 1px solid #2a2d36; border-left-width: 4px; padding: 8px 12px; margin: 8px 0; border-radius: 4px; background:#11131a; }}
  .ev.tp {{ border-left-color: #5cb85c; }}
  .ev.fp {{ border-left-color: #d9534f; }}
  .ev.fn {{ border-left-color: #f0ad4e; background:#1c1814; }}
  .ts {{ color: #9ad; font-weight: 600; }}
  .tag {{ display:inline-block; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-left: 6px; }}
  .tag.tp {{ background:#1f3d20; color:#9c9; }}
  .tag.fp {{ background:#3a1f1f; color:#f99; }}
  .tag.fn {{ background:#3a2f1f; color:#fc9; }}
</style></head>
<body>
<h1>MuBit Submission Detection</h1>
<div>run: <code>{run_id}</code> &nbsp; video: <code>{video}</code></div>

<h2>Metrics</h2>
{metrics_table}

<h2>Side-by-side events</h2>
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


def _metrics_table(metrics_a: dict, metrics_b: dict, label_a: str, label_b: str) -> str:
    rows = [
        ("GT count", metrics_a.get("n_gt"), metrics_b.get("n_gt")),
        ("Predictions", metrics_a.get("n_pred"), metrics_b.get("n_pred")),
        ("True positives", metrics_a.get("tp"), metrics_b.get("tp")),
        ("False positives", metrics_a.get("fp"), metrics_b.get("fp")),
        ("False negatives", metrics_a.get("fn"), metrics_b.get("fn")),
        ("Precision", f"{metrics_a.get('precision', 0):.3f}", f"{metrics_b.get('precision', 0):.3f}"),
        ("Recall", f"{metrics_a.get('recall', 0):.3f}", f"{metrics_b.get('recall', 0):.3f}"),
        ("F1", f"{metrics_a.get('f1', 0):.3f}", f"{metrics_b.get('f1', 0):.3f}"),
        (
            "Timestamp MAE",
            f"{metrics_a.get('timestamp_mae'):.2f}s" if metrics_a.get("timestamp_mae") is not None else "—",
            f"{metrics_b.get('timestamp_mae'):.2f}s" if metrics_b.get("timestamp_mae") is not None else "—",
        ),
    ]
    body = "".join(
        f"<tr><td>{name}</td><td>{a}</td><td>{b}</td></tr>" for name, a, b in rows
    )
    return f"<table><tr><th>Metric</th><th>{label_a}</th><th>{label_b}</th></tr>{body}</table>"


def _render_event(m: dict) -> str:
    kind = m.get("kind", "tp")
    if kind == "true_positive":
        cls = "tp"
        tag = '<span class="tag tp">TP</span>'
        ts = f"{m['pred']['timestamp']:.1f}s"
        body = (
            f"<b>{m['pred']['sub_type']}</b> ({m['pred']['outcome']}, conf={m['pred']['confidence']:.2f}) "
            f"vs GT <i>{m['gt']['title']}</i>"
        )
    elif kind == "false_positive":
        cls = "fp"
        tag = '<span class="tag fp">FP</span>'
        ts = f"{m['pred']['timestamp']:.1f}s"
        body = f"<b>{m['pred']['sub_type']}</b> hallucinated (conf={m['pred']['confidence']:.2f})"
    else:  # false_negative
        cls = "fn"
        tag = '<span class="tag fn">FN</span>'
        ts = f"{m['gt']['timestamp']:.1f}s"
        body = f"<b>{m['gt']['sub_type']}</b> missed — GT: <i>{m['gt']['description']}</i>"
    return f'<div class="ev {cls}"><span class="ts">{ts}</span> {tag}<br>{body}</div>'


def _events_html(matched_path: Path) -> str:
    if not matched_path.exists():
        return "<i>no run data yet</i>"
    matches = json.loads(matched_path.read_text()).get("matches", [])
    matches.sort(
        key=lambda m: (
            (m.get("pred") or m.get("gt") or {}).get("timestamp", 0.0)
        )
    )
    return "\n".join(_render_event(m) for m in matches)


def render(run_id: str, version_a: str, version_b: str, label_a: str = "v1", label_b: str = "v2") -> Path:
    """Generate report.html for two completed runs."""
    run_dir = OUTPUTS_DIR / "runs" / run_id
    metrics_a = json.loads((run_dir / f"metrics.{version_a}.json").read_text())
    metrics_b = json.loads((run_dir / f"metrics.{version_b}.json").read_text())

    html = HTML_TEMPLATE.format(
        run_id=run_id,
        video=metrics_a.get("video", ""),
        metrics_table=_metrics_table(metrics_a, metrics_b, label_a, label_b),
        label_a=label_a,
        label_b=label_b,
        ver_a=version_a[:12],
        ver_b=version_b[:12],
        events_a=_events_html(run_dir / f"matched.{version_a}.json"),
        events_b=_events_html(run_dir / f"matched.{version_b}.json"),
    )
    out = run_dir / "report.html"
    out.write_text(html)
    print(f"Wrote {out}")
    return out
