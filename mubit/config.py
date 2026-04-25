"""Centralized config for the MuBit submission-detection demo.

Edit AGENT_ID here if you created the agent in the Console with a different name.
PROJECT_ID is the one already created at console.mubit.ai.
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

DEFAULT_VIDEO = REPO_ROOT / "full-gym-short.mov"
DEFAULT_GT = REPO_ROOT / "eval" / "gt.json"

# --- Gemini ---
GEMINI_MODEL = "gemini-2.5-pro"

# --- Eval matching ---
# A predicted submission counts as matching a GT submission if their timestamps
# are within this many seconds AND (later, optionally) sub_type matches.
TIMESTAMP_TOLERANCE_S = 5.0

# Event types in the GT that count as "submission-related" for this detector.
# Anything not in this set is filtered out by gt.load_submission_gt().
SUBMISSION_EVENT_TYPES = {"submission", "sub_attempt", "near_finish"}

# --- MuBit run scoping ---
# Each detect run is one "run" in MuBit. Format keeps videos separable
# while letting cross-run reflection pull in patterns from previous fights.
def run_id_for_video(video_path: Path) -> str:
    return f"sub-detect:{video_path.stem}"
