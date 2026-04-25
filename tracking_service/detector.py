"""YOLO model loader + single-frame person detection.

Used by the /detect_frame endpoint so the user can pick a fighter
to track from a still frame before kicking off the full video pass.
"""

from __future__ import annotations

import io
from functools import lru_cache
from typing import List, TypedDict

import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO

# yolov8x = best quality, ~1.5GB VRAM, slow on CPU.
# yolov8n = fast, fine for the picker frame on CPU/Mac.
# Override via env if you need to swap.
DEFAULT_WEIGHTS = "yolov8x.pt"
PERSON_CLASS_ID = 0


class Detection(TypedDict):
    id: int
    bbox: List[float]  # [x, y, w, h] in pixels, top-left origin
    conf: float


@lru_cache(maxsize=1)
def get_model(weights: str = DEFAULT_WEIGHTS) -> YOLO:
    """Lazy-load + cache the YOLO model. Ultralytics auto-downloads weights."""
    return YOLO(weights)


def detect_people(image_bytes: bytes, conf_threshold: float = 0.4) -> List[Detection]:
    """Run YOLO on a single frame and return person bboxes only.

    bbox is returned as [x, y, w, h] (top-left + width/height) in pixel
    coordinates so the frontend can draw it directly on the rendered frame.
    """
    pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(pil)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    model = get_model()
    results = model.predict(
        source=bgr,
        classes=[PERSON_CLASS_ID],
        conf=conf_threshold,
        verbose=False,
    )

    out: List[Detection] = []
    if not results:
        return out

    boxes = results[0].boxes
    if boxes is None:
        return out

    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        out.append(
            {
                "id": i,
                "bbox": [float(x1), float(y1), float(x2 - x1), float(y2 - y1)],
                "conf": float(box.conf[0]),
            }
        )
    return out
