"""Single config file for the flywheel.

Two kinds of values live here:

  - MuBit identifiers (where prompts and outcomes go)
  - Local paths + analyze.py knobs

Nothing else imports the MuBit SDK. The SDK lives in `mubit_client.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- MuBit -----------------------------------------------------------------
PROJECT_ID = "proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099"
PROJECT_SLUG = "jiujitsu-rt3hsz"
# We optimize the DOMAIN RULES layer of the Stage-1 scan prompt inside
# analyze.py. The rest of the prompt (framing, fighter block, JSON schema)
# stays locked in Python so the optimizer can only touch domain reasoning.
AGENT_ID = "submission-detector-naive"

# --- Paths -----------------------------------------------------------------
FLYWHEEL_DIR = Path(__file__).resolve().parent
REPO_ROOT = FLYWHEEL_DIR.parent
PROMPTS_DIR = FLYWHEEL_DIR / "prompts"
OUTPUTS_DIR = FLYWHEEL_DIR / "outputs"
SEED_PROMPT = PROMPTS_DIR / "verifier_naive.md"

VLM_GEMINI_DIR = REPO_ROOT / "VLM-gemini"
ANALYZE_SCRIPT = VLM_GEMINI_DIR / "analyze.py"

DEFAULT_GAME = "ryan-thomas"
DEFAULT_VIDEO = VLM_GEMINI_DIR / "input-data" / DEFAULT_GAME / "video.mov"
DEFAULT_GT = VLM_GEMINI_DIR / "input-data" / DEFAULT_GAME / "subs.json"

# --- analyze.py knobs ------------------------------------------------------
# Mirror VLM-gemini/analyze.py CLI defaults; tweaking them here changes what
# spin() asks the pipeline to do without touching code.
ANALYZE_MODEL = "gemini-3-flash-preview"
ANALYZE_WINDOW_SEC = 40.0
ANALYZE_GRID_STEP = 15.0
ANALYZE_CLUSTER_TAU = 20.0
ANALYZE_WORKERS = 12

# Python interpreter used to launch analyze.py as a subprocess. analyze.py
# uses google.generativeai; mubit-sdk uses google-genai. Override via
# `FLYWHEEL_ANALYZE_PYTHON` env var if your analyze deps live in a different
# venv from the flywheel deps.
ANALYZE_PYTHON = Path(
    os.environ.get("FLYWHEEL_ANALYZE_PYTHON") or sys.executable
)

# --- Eval matching ---------------------------------------------------------
# Tolerance window for greedy timestamp matching (seconds).
MATCH_TOLERANCE_S = 10.0


def run_id_for_video(video_path: Path) -> str:
    """One MuBit run per video. Re-running the same video accumulates outcomes."""
    return f"verify:{video_path.stem}"
