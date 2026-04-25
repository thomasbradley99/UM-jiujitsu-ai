import os
from pathlib import Path
from typing import List

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None  # type: ignore


def load_env_multisource(extra_paths: List[Path] | None = None) -> None:
    """Load environment variables from common locations without overriding.

    Search order:
    1) Current shell environment
    2) Project .env.local (JS app root)
    3) Project .env
    4) Repo root .env
    5) Any extra paths passed in
    """
    if load_dotenv is None:
        return

    # Keep anything already exported in the shell
    try:
        load_dotenv()  # override=False by default
    except Exception:
        pass

    project_root = Path(__file__).resolve().parents[1]
    repo_root = project_root.parents[0]

    candidates: List[Path] = [
        project_root / '.env.local',
        project_root / '.env',
        repo_root / '.env',
    ]
    if extra_paths:
        candidates.extend(extra_paths)

    for env_path in candidates:
        try:
            if env_path.exists():
                load_dotenv(str(env_path), override=False)
        except Exception:
            # Best-effort loading; ignore malformed files
            pass


def require(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"Required env var {var_name} is not set")
    return value


