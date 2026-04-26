# Data schema reference

Every file under `website/data/`. Schemas are stable — if you depend on them
in a frontend, they won't change without a deprecation note here.

TypeScript-style interfaces below are copy-paste ready.

---

## `data/manifest.json`

Top-level summary — fetch this first.

```ts
interface Manifest {
  built_at: string;        // ISO 8601 UTC
  games: string[];         // game ids
  arcs: Array<{
    id: string;            // e.g. "handtuned-ryan-thomas"
    label: string;         // human label
    peak_f1: number | null;
  }>;
  cross_eval_games: string[];
}
```

---

## `data/games/index.json`

Array of every input game with full GT inline.

```ts
interface Game {
  id: string;              // folder name, e.g. "ryan-thomas"
  fight_date: string;      // ISO 8601 date for the fight; sourced from GT metadata or file timestamp fallback
  source_updated_at: string; // ISO 8601 timestamp of the GT annotation source file
  duration_sec: number;
  description: string;
  fighters: Record<string, {
    visual: string;        // human-readable description
    role?: string;
    ai_descriptor?: string;
  }>;
  submissions: Array<{
    timestamp: number;     // seconds from start of video
    technique: string;     // canonical token: armbar | rnc | triangle | ...
    submitter: string;     // key into fighters
    submittee: string;
    notes?: string;
  }>;
  video_url: string | null;  // path under /public/, e.g. "/public/games/ryan-thomas/video.mov"
}
```

`data/games/<game>/subs.json` — same shape as one Game's GT slice
(redundant copy for direct fetching by game id).

---

## `data/runs/index.json`

```ts
interface RunSummary {
  id: string;
  label: string;
  video: string;           // game id this arc was run on
  model: string;           // e.g. "gemini-3-flash-preview"
  n_iterations: number;
  peak_f1: number | null;
}
```

## `data/runs/<arc_id>/index.json`

```ts
interface Arc {
  id: string;
  label: string;
  video: string;
  model: string;
  iterations: Array<{
    iteration: number;     // 1-indexed
    prompt_version_id: string;       // pv-XXXXXXXX-...
    f1: number;
    precision: number;
    recall: number;
    n_gt: number;
    n_pred: number;
    n_matched: number;
    n_hallucinations: number;
    candidate_version_id: string | null;  // next iteration's prompt id (null on last)
    activated: boolean;
    prompt_chars: number;
  }>;
}
```

## `data/runs/<arc_id>/<pv>/`

Per-iteration deep data:

- `prompt.md` — the **domain rules** layer of the prompt (the part the
  flywheel optimizes). Markdown, can be rendered or used in a diff view.
- `report.json` — eval result, see `Report` below.
- `result.json` — full pipeline output, see `Result` below.

---

## `Report` (`report.json`)

```ts
interface Report {
  config: string;          // run label, e.g. "verify:video:pv-377be9c6-"
  tau: number;             // matching tolerance in seconds (default 10)
  n_gt: number;
  n_pred: number;
  matched: number;
  sub_recall: number;      // matched / n_gt
  sub_precision: number;   // matched / n_pred
  f1: number;
  technique_acc: number;   // 0..1, fraction of matched events with correct technique
  submitter_acc: number;   // 0..1, fraction of matched events with correct submitter
  timestamp_mae: number;   // mean abs error in seconds
  hallucinations: number;
  details: Array<{
    status: "matched" | "missed_gt" | "hallucination";
    gt_t?: number;
    gt_technique?: string;
    gt_submitter?: string;
    pred_t?: number;
    pred_technique?: string;
    pred_submitter_raw?: string;       // what the model literally said
    pred_submitter_resolved?: string;  // canonicalized to a fighter id
    delta_t?: number;
    technique_correct?: boolean;
    submitter_correct?: boolean;
  }>;
}
```

---

## `Result` (`result.json`)

The full pipeline output. The clusters are the predictions; `all_window_rows`
is forensic data (every 40s window the model scanned).

```ts
interface Result {
  video: string;
  duration_sec: number;
  fighters: Record<string, { visual: string }>;  // Stage 0 output
  submissions: Array<{                           // clustered predictions
    timestamp: number;
    technique: string;
    submitter: string;
    submittee: string;
    confidence: "high" | "medium" | "low";
    reasoning: string;     // model's one-sentence justification for the cluster
    cluster_size: number;  // how many YES windows merged into this cluster
    window_starts: number[];
  }>;
  metadata: {
    model: string;
    window_sec: number;
    grid_step: number;
    cluster_tau: number;
    workers: number;
    n_windows: number;
    n_yes_windows: number;
    stage1_elapsed_sec: number;
    total_elapsed_sec: number;
    domain_rules_source: string;
    all_window_rows: Array<{
      start: number;
      end: number;
      duration: number;
      is_submission: boolean;
      technique: string;
      submitter: string;
      submittee: string;
      confidence: "high" | "medium" | "low";
      reasoning: string;          // model's per-window justification
      tap_offset_sec: number;
      absolute_timestamp: number;
      raw_response?: string;      // raw Gemini response text (added Apr 2026)
      error?: string;             // present if the window failed
    }>;
  };
}
```

---

## `data/cross_eval/index.json`

The matrix view: each game has cells for each prompt tested against it.

```ts
interface CrossEvalMatrix {
  game: string;
  cells: Array<{
    label: string;                 // "v1", "v2", ...
    prompt_version_id: string;
    f1: number;
    precision: number;
    recall: number;
    technique_acc: number;
    submitter_acc: number;
    n_gt: number;
    matched: number;
    hallucinations: number;
  }>;
}
```

`data/cross_eval/<game>/<v#-pv>/{result.json, report.json}` — same shapes as
`Result` and `Report`.

---

## Conventions

- All timestamps are **seconds from the start of the video** (floats OK).
- All probabilities/accuracies are in **[0, 1]**, not percentages.
- Prompt version ids look like `pv-377be9c6-d965-4e43-9511-43ab10ecd725`;
  truncate to `pv-XXXXXXXX-` for display.
- Fighter keys are arbitrary strings — `"BALD"`, `"instructor"`, `"chris"`.
  Match against `pred_submitter_resolved`, not `pred_submitter_raw`.
