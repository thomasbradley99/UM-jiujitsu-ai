"""BJJ Research Lab — FastAPI backend (Pydantic v2).

Serves experiment data from website/data/ as a strictly-typed JSON API and
streams live analysis results via Server-Sent Events (SSE) so the React
frontend can render updating plots without polling.

Run locally
-----------
    pip install -r backend/requirements.txt
    uvicorn backend.backend:app --reload --port 8000

Render deploy (second Web Service)
-----------------------------------
    Build : pip install -r backend/requirements.txt
    Start : uvicorn backend.backend:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DATA = REPO_ROOT / "website" / "data"
BUILD_SCRIPT = REPO_ROOT / "website" / "build.py"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="BJJ Research Lab API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to your Render URL in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# I/O helper
# ---------------------------------------------------------------------------

def _read(rel: str) -> Any:
    """Read and JSON-parse a file under WEB_DATA, raising 404 if missing."""
    p = WEB_DATA / rel
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Data not found: {rel}")
    return json.loads(p.read_text())


# ===========================================================================
# Domain models — static experiment data
# Pydantic v2: ConfigDict, field_validator, model_validator, computed_field
# ===========================================================================

class Fighter(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    visual: str
    role: str | None = None
    ai_descriptor: str | None = None


class Submission(BaseModel):
    """Ground-truth submission event from a game."""
    model_config = ConfigDict(frozen=True)

    timestamp: float = Field(ge=0.0, description="Seconds into the video")
    technique: str
    submitter: str
    submittee: str
    notes: str | None = None

    @field_validator("technique", "submitter", "submittee", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return str(v).strip()


class Game(BaseModel):
    """A single BJJ training game with ground-truth submission annotations."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    fight_date: str
    source_updated_at: str
    duration_sec: float | None = None
    description: str | None = None
    fighters: dict[str, Fighter]
    submissions: list[Submission] = Field(default_factory=list)
    video_url: str | None = None

    @model_validator(mode="after")
    def _sort_submissions(self) -> "Game":
        """Always return submissions sorted chronologically."""
        self.submissions = sorted(self.submissions, key=lambda s: s.timestamp)
        return self

    @computed_field
    @property
    def n_submissions(self) -> int:
        return len(self.submissions)


class ArcSummary(BaseModel):
    """Lightweight arc summary used in the manifest."""
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    peak_f1: float | None = None

    @computed_field
    @property
    def tier(self) -> Literal["good", "fair", "poor", "unknown"]:
        """Performance tier derived from peak F1."""
        if self.peak_f1 is None:
            return "unknown"
        if self.peak_f1 >= 0.8:
            return "good"
        if self.peak_f1 >= 0.5:
            return "fair"
        return "poor"


class ManifestResponse(BaseModel):
    built_at: str
    games: list[str]
    arcs: list[ArcSummary]
    cross_eval_games: list[str]


class RunSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    video: str
    model: str
    n_iterations: int = Field(ge=1)
    peak_f1: float | None = None


class ArcIteration(BaseModel):
    """One flywheel iteration — a single prompt evaluation round."""
    model_config = ConfigDict(frozen=True)

    iteration: int = Field(ge=1)
    prompt_version_id: str
    f1: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    n_gt: int = Field(ge=0)
    n_pred: int = Field(ge=0)
    n_matched: int = Field(ge=0)
    n_hallucinations: int = Field(ge=0)
    candidate_version_id: str | None = None
    activated: bool = False
    prompt_chars: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_counts(self) -> "ArcIteration":
        if self.n_matched + self.n_hallucinations > self.n_pred + 1:
            raise ValueError(
                f"matched({self.n_matched}) + hallucinations({self.n_hallucinations}) "
                f"exceeds n_pred({self.n_pred})"
            )
        return self

    @computed_field
    @property
    def f1_pct(self) -> str:
        return f"{self.f1:.1%}"


class Arc(BaseModel):
    """Full arc detail including all iterations."""
    id: str
    label: str
    video: str
    model: str
    iterations: list[ArcIteration]

    @computed_field
    @property
    def best_iteration(self) -> ArcIteration | None:
        return max(self.iterations, key=lambda it: it.f1, default=None)

    @computed_field
    @property
    def peak_f1(self) -> float | None:
        best = self.best_iteration
        return best.f1 if best else None


class CrossEvalCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    prompt_version_id: str
    f1: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    technique_acc: float = Field(ge=0.0, le=1.0)
    submitter_acc: float = Field(ge=0.0, le=1.0)
    n_gt: int = Field(ge=0)
    matched: int = Field(ge=0)
    hallucinations: int = Field(ge=0)


class CrossEvalRow(BaseModel):
    game: str
    cells: list[CrossEvalCell]


class BuildResponse(BaseModel):
    ok: bool
    output: str


# ===========================================================================
# Live streaming models — SSE wire format
# ===========================================================================

class DetectedEvent(BaseModel):
    """A single submission detection emitted during live analysis."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_sec: float = Field(ge=0.0)
    technique: str
    submitter: str
    submittee: str
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> float:
        return round(max(0.0, min(1.0, float(v))), 4)

    @computed_field
    @property
    def confidence_pct(self) -> str:
        return f"{self.confidence:.0%}"


class LiveMetrics(BaseModel):
    """Evaluation metric snapshot for one flywheel iteration."""
    model_config = ConfigDict(frozen=True)

    iteration: int = Field(ge=1)
    prompt_label: str
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    n_gt: int = Field(ge=0)
    n_pred: int = Field(ge=0)
    matched: int = Field(ge=0)
    hallucinations: int = Field(ge=0)
    activated: bool = False

    @model_validator(mode="after")
    def _recompute_f1(self) -> "LiveMetrics":
        """Correct F1 if precision+recall disagree due to upstream rounding."""
        denom = self.precision + self.recall
        if denom > 1e-9:
            expected = 2.0 * self.precision * self.recall / denom
            if abs(self.f1 - expected) > 0.02:
                object.__setattr__(self, "f1", round(expected, 4))
        return self

    @computed_field
    @property
    def f1_pct(self) -> str:
        return f"{self.f1:.1%}"

    @computed_field
    @property
    def hallucination_rate(self) -> float:
        return round(self.hallucinations / max(self.n_pred, 1), 4)


FrameType = Literal["event", "metrics", "complete", "heartbeat"]


class StreamFrame(BaseModel):
    """One SSE payload pushed to the client.

    Each frame carries the *full* accumulated state so the client is always
    consistent even if it connects mid-stream or misses a frame.

    Deserializes on the frontend with ``JSON.parse(event.data)``.
    """
    model_config = ConfigDict(frozen=True)

    frame_type: FrameType
    elapsed_sec: Annotated[float, Field(ge=0.0)]
    total_events: int = Field(ge=0, default=0)
    events: list[DetectedEvent] = Field(default_factory=list)
    metrics_history: list[LiveMetrics] = Field(default_factory=list)
    message: str | None = None

    def to_sse(self) -> str:
        """Serialize to the SSE wire format required by the browser EventSource API."""
        return f"data: {self.model_dump_json()}\n\n"


# ===========================================================================
# SSE stream generator
# ===========================================================================

async def _stream_arc(arc_id: str, speed: float) -> AsyncIterator[str]:
    """Replay a flywheel arc as a sequence of SSE frames.

    Each frame carries the full accumulated state so the client is always
    consistent even if it connects mid-stream.
    """
    try:
        arc = Arc.model_validate(_read(f"runs/{arc_id}/index.json"))
    except HTTPException:
        yield StreamFrame(
            frame_type="complete",
            elapsed_sec=0.0,
            message=f"Arc '{arc_id}' not found",
        ).to_sse()
        return

    # Load matching game for ground-truth submission positions
    game: Game | None = None
    try:
        games = [Game.model_validate(g) for g in _read("games/index.json")]
        game = next((g for g in games if g.id == arc.video), None)
    except Exception:
        pass

    start = time.monotonic()
    events_so_far: list[DetectedEvent] = []
    metrics_history: list[LiveMetrics] = []

    # ── Heartbeat ──
    yield StreamFrame(
        frame_type="heartbeat",
        elapsed_sec=0.0,
        message=f"Starting replay of '{arc.label}' · {len(arc.iterations)} iterations",
    ).to_sse()
    await asyncio.sleep(0.5 / speed)

    for it in arc.iterations:
        live_m = LiveMetrics(
            iteration=it.iteration,
            prompt_label=it.prompt_version_id[:28],
            precision=it.precision,
            recall=it.recall,
            f1=it.f1,
            n_gt=it.n_gt,
            n_pred=it.n_pred,
            matched=it.n_matched,
            hallucinations=it.n_hallucinations,
            activated=it.activated,
        )
        metrics_history = [*metrics_history, live_m]

        # ── Emit individual event arrivals ──
        if game:
            visible_subs = game.submissions[: it.n_matched]
            for sub in visible_subs:
                already = any(
                    e.timestamp_sec == sub.timestamp and e.technique == sub.technique
                    for e in events_so_far
                )
                if already:
                    continue

                # Deterministic confidence jitter derived from technique name
                jitter = (sum(ord(c) for c in sub.technique) % 13 - 6) / 100
                confidence = max(0.0, min(1.0, it.f1 + jitter))

                ev = DetectedEvent(
                    timestamp_sec=sub.timestamp,
                    technique=sub.technique,
                    submitter=sub.submitter,
                    submittee=sub.submittee,
                    confidence=confidence,
                    notes=sub.notes,
                )
                events_so_far = [*events_so_far, ev]

                yield StreamFrame(
                    frame_type="event",
                    elapsed_sec=round(time.monotonic() - start, 3),
                    total_events=len(events_so_far),
                    events=list(events_so_far),
                    metrics_history=list(metrics_history),
                ).to_sse()
                await asyncio.sleep(0.4 / speed)

        # ── Metrics snapshot after all events for this iteration ──
        yield StreamFrame(
            frame_type="metrics",
            elapsed_sec=round(time.monotonic() - start, 3),
            total_events=len(events_so_far),
            events=list(events_so_far),
            metrics_history=list(metrics_history),
            message=(
                f"Iter {it.iteration}: "
                f"F1 {it.f1:.1%} | P {it.precision:.1%} | R {it.recall:.1%}"
            ),
        ).to_sse()
        await asyncio.sleep(1.8 / speed)

    # ── Terminal frame ──
    yield StreamFrame(
        frame_type="complete",
        elapsed_sec=round(time.monotonic() - start, 3),
        total_events=len(events_so_far),
        events=list(events_so_far),
        metrics_history=list(metrics_history),
        message="Analysis complete ✓",
    ).to_sse()


# ===========================================================================
# Routes
# ===========================================================================

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/manifest", response_model=ManifestResponse)
def get_manifest() -> ManifestResponse:
    return ManifestResponse.model_validate(_read("manifest.json"))


@app.get("/api/games", response_model=list[Game])
def get_games() -> list[Game]:
    return [Game.model_validate(g) for g in _read("games/index.json")]


@app.get("/api/games/{game_id}", response_model=Game)
def get_game(game_id: str) -> Game:
    raw_list: list[dict] = _read("games/index.json")
    raw = next((g for g in raw_list if g["id"] == game_id), None)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")
    return Game.model_validate(raw)


@app.get("/api/runs", response_model=list[RunSummary])
def get_runs() -> list[RunSummary]:
    return [RunSummary.model_validate(r) for r in _read("runs/index.json")]


@app.get("/api/runs/{arc_id}", response_model=Arc)
def get_arc(arc_id: str) -> Arc:
    return Arc.model_validate(_read(f"runs/{arc_id}/index.json"))


@app.get("/api/cross-eval", response_model=list[CrossEvalRow])
def get_cross_eval() -> list[CrossEvalRow]:
    return [CrossEvalRow.model_validate(r) for r in _read("cross_eval/index.json")]


@app.get(
    "/api/analysis/stream/{arc_id}",
    summary="Stream arc replay as Server-Sent Events",
    response_description="text/event-stream of StreamFrame JSON payloads",
)
async def stream_analysis(
    arc_id: str,
    speed: Annotated[float, Query(ge=0.1, le=10.0)] = 1.0,
) -> StreamingResponse:
    """Connect via ``EventSource`` to receive live ``StreamFrame`` payloads.

    Each frame carries the cumulative event list + metrics history so the
    client is always consistent, even if it joins mid-stream.

    Query params
    ------------
    speed : float (0.1–10.0)
        Replay speed multiplier. ``2.0`` plays at 2× real time.
    """
    return StreamingResponse(
        _stream_arc(arc_id, speed=speed),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering on Render
        },
    )


@app.post("/api/build", response_model=BuildResponse)
def trigger_build() -> BuildResponse:
    """Re-run website/build.py to regenerate the data bundle from raw artifacts."""
    if not BUILD_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="website/build.py not found")
    result = subprocess.run(
        ["python", str(BUILD_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr or "Build failed")
    return BuildResponse(ok=True, output=result.stdout)
