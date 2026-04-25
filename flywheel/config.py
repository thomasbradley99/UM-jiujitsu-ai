"""Single config file for the flywheel.

Two kinds of values live here:

  - MuBit identifiers (where prompts and outcomes go)
  - Local paths (video, GT, v3-fast cache dir, flywheel outputs)

Nothing else imports the MuBit SDK. The SDK lives in `mubit_client.py`.
"""

from __future__ import annotations

from pathlib import Path

# --- MuBit -----------------------------------------------------------------
PROJECT_ID = "proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099"
PROJECT_SLUG = "jiujitsu-rt3hsz"
AGENT_ID = "submission-detector"

# --- Paths -----------------------------------------------------------------
FLYWHEEL_DIR = Path(__file__).resolve().parent
REPO_ROOT = FLYWHEEL_DIR.parent
PROMPTS_DIR = FLYWHEEL_DIR / "prompts"
OUTPUTS_DIR = FLYWHEEL_DIR / "outputs"
SEED_PROMPT = PROMPTS_DIR / "filter_v1.md"

VLM_GEMINI_DIR = REPO_ROOT / "VLM-gemini"
VLM_PROCESSOR = VLM_GEMINI_DIR / "video_processor_v3_fast.py"

# Default ryan-thomas dataset committed under VLM-gemini/input-data/.
DEFAULT_GAME = "ryan-thomas"
DEFAULT_VIDEO = VLM_GEMINI_DIR / "input-data" / DEFAULT_GAME / "video.mov"
DEFAULT_GT = VLM_GEMINI_DIR / "input-data" / DEFAULT_GAME / "subs.json"
# Where v3-fast's slow Stage-1/Stage-2 output is cached.
DEFAULT_VLM_OUT = VLM_GEMINI_DIR / "runs" / DEFAULT_GAME / "baseline"

# --- Gemini ----------------------------------------------------------------
# Filter call is text-only, so flash is plenty.
GEMINI_FILTER_MODEL = "gemini-2.5-flash"

# --- Eval matching ---------------------------------------------------------
# Tolerance window for greedy timestamp matching (seconds). Mirrors the
# default in VLM-gemini/eval/run_eval.py; keep them in sync.
MATCH_TOLERANCE_S = 10.0


def run_id_for_video(video_path: Path) -> str:
    """One MuBit run per video. Re-running the same video accumulates outcomes."""
    return f"sub-detect:{video_path.stem}"
