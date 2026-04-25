"""Person ReID embedding extraction.

Wraps torchreid's OSNet (osnet_x1_0) into a small, lazy-loaded API.
OSNet is purpose-built for person re-identification: 2.2M params,
512-dim L2-normalizable embeddings, fast on MPS/CUDA.

Used to upgrade `merge_tracks` from "are these two bboxes geometrically
close?" to "do these two crops look like the same person?".

First load downloads ImageNet-pretrained weights (~11MB) into
~/.cache/torch/checkpoints/. For real BJJ deployment you'll want
Market-1501-trained weights instead — see TODO in get_extractor().
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional, Sequence

import cv2
import numpy as np
import torch


_DEFAULT_MODEL = "osnet_x1_0"


def _select_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@lru_cache(maxsize=1)
def get_extractor(model_name: str = _DEFAULT_MODEL, device: Optional[str] = None):
    """Lazy-load the torchreid OSNet feature extractor and cache it.

    TODO: swap to market1501-pretrained weights for production. The
    imagenet-pretrained variant is decent but not specifically tuned
    for cross-camera person ReID. Market-1501 weights live at
    https://kaiyangzhou.github.io/deep-person-reid/MODEL_ZOO and can
    be passed via model_path=...
    """
    from torchreid.reid.utils import FeatureExtractor

    return FeatureExtractor(
        model_name=model_name,
        model_path="",
        device=device or _select_device(),
        verbose=False,
    )


def _crop_bbox(image: np.ndarray, bbox: Sequence[float], pad: float = 0.1) -> Optional[np.ndarray]:
    """Crop image to bbox + a small padding. Returns None for unusable crops.

    bbox is [x, y, w, h] in pixels. Padding is a fraction of the box size
    on each side; helps the ReID model see context (e.g. gi sleeves
    poking outside the tight YOLO box).
    """
    x, y, w, h = bbox
    if w <= 0 or h <= 0:
        return None
    H, W = image.shape[:2]
    px, py = int(round(w * pad)), int(round(h * pad))
    x1 = max(0, int(round(x)) - px)
    y1 = max(0, int(round(y)) - py)
    x2 = min(W, int(round(x + w)) + px)
    y2 = min(H, int(round(y + h)) + py)
    if x2 - x1 < 16 or y2 - y1 < 32:
        # too small to embed reliably (jersey-number territory)
        return None
    return image[y1:y2, x1:x2]


def embed_crops(
    crops: List[np.ndarray],
    batch_size: int = 64,
    on_progress: Optional[callable] = None,  # type: ignore[type-arg]
) -> np.ndarray:
    """Run a list of BGR crops through OSNet, return L2-normalized features.

    Always batches in chunks of ``batch_size`` (default 64) — torchreid's
    FeatureExtractor will happily accept the whole list at once but on
    MPS that ends up being a single huge graph that allocates a lot of
    memory and never returns a progress signal. Chunking keeps memory
    flat and lets callers stream a progress bar.

    Returns (N, 512) float32 array. Empty input -> shape (0, 512).
    """
    if not crops:
        return np.zeros((0, 512), dtype=np.float32)

    extractor = get_extractor()
    out = np.empty((len(crops), 512), dtype=np.float32)

    for start in range(0, len(crops), batch_size):
        end = min(start + batch_size, len(crops))
        # torchreid expects RGB uint8 numpy arrays (or file paths).
        rgb = [cv2.cvtColor(c, cv2.COLOR_BGR2RGB) for c in crops[start:end]]
        with torch.no_grad():
            feats = extractor(rgb)
        block = feats.detach().cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(block, axis=1, keepdims=True)
        norms = np.where(norms < 1e-9, 1.0, norms)
        out[start:end] = block / norms
        if on_progress is not None:
            on_progress(end, len(crops))
    return out


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for L2-normalized vectors. Output in [-1, 1]."""
    return float(np.dot(a, b))
