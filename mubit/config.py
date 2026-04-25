"""Centralized config for the MuBit submission-detection demo.

Architecture: VLM-gemini/video_processor_v3_fast.py produces a rich
result.json. MuBit owns a "submission filter" prompt (versioned) that
takes that result.json's events and outputs a canonical submission list.
That filtered list is then evaluated against subs.json by VLM-gemini/eval/.

So the optimizer iterates on the filter prompt — fast, cheap, no video calls.
"""

from pathlib import Path

# --- MuBit resource identifiers ---
PROJECT_ID = "proj-0ea4de0c-5ca2-4eed-a443-9df064ec2099"
PROJECT_SLUG = "jiujitsu-rt3hsz"
AGENT_ID = "submission-detector"

# --- Paths ---
MUBIT_DIR = Path(__file__).resolve().parent
REPO_ROOT = MUBIT_DIR.parent
PROMPTS_DIR = MUBIT_DIR / "prompts"
OUTPUTS_DIR = MUBIT_DIR / "outputs"

VLM_GEMINI_DIR = REPO_ROOT / "VLM-gemini"
VLM_PROCESSOR = VLM_GEMINI_DIR / "video_processor_v3_fast.py"

# Default ryan-thomas dataset committed under VLM-gemini/input-data/.
DEFAULT_GAME = "ryan-thomas"
DEFAULT_VIDEO = VLM_GEMINI_DIR / "input-data" / DEFAULT_GAME / "video.mov"
DEFAULT_GT = VLM_GEMINI_DIR / "input-data" / DEFAULT_GAME / "subs.json"
DEFAULT_VLM_OUT = VLM_GEMINI_DIR / "runs" / DEFAULT_GAME / "baseline"  # where v3-fast writes result.json

# --- Gemini ---
# Filter call is text-only; flash is plenty.
GEMINI_FILTER_MODEL = "gemini-2.5-flash"

# --- Eval matching ---
# Tolerance window for greedy timestamp matching (seconds). Mirrors the default
# in VLM-gemini/eval/run_eval.py; keep them in sync.
MATCH_TOLERANCE_S = 10.0


# --- MuBit run scoping ---
def run_id_for_video(video_path: Path) -> str:
    """One MuBit run per (game, video) — re-running the same video accumulates outcomes."""
    return f"sub-detect:{video_path.stem}"
