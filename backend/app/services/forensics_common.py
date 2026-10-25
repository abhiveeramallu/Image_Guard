"""Shared helpers for score-map based detectors (splicing heuristic, model localization)."""
import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image


@dataclass
class MapOutput:
    """Result of a score-map method. `score` is float32 HxW in [0, 1] at original resolution."""
    status: str
    status_reason: str
    score: np.ndarray | None
    threshold: float
    regions: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    processing_ms: float = 0.0
    mask: np.ndarray | None = None  # uint8 0/255


def threshold_mask(score: np.ndarray, threshold: float, min_area: int, close_px: int = 5) -> tuple[np.ndarray, list[dict]]:
    """Binary mask (0/255) from a score map plus connected-component regions >= min_area pixels."""
    m = (score >= threshold).astype(np.uint8) * 255
    if close_px > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px, close_px))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros_like(m)
    regions = []
    order = sorted(range(1, n), key=lambda i: -stats[i, cv2.CC_STAT_AREA])
    for i in order:
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        keep[labels == i] = 255
        regions.append({
            "id": len(regions) + 1, "area_px": area,
            "bbox": {"x": int(stats[i, 0]), "y": int(stats[i, 1]), "width": int(stats[i, 2]), "height": int(stats[i, 3])},
        })
    return keep, regions


def heatmap_overlay(rgb: np.ndarray, score: np.ndarray) -> np.ndarray:
    """JET colour overlay of a [0,1] score map, blended in row chunks to bound memory."""
    out = np.empty_like(rgb)
    H = rgb.shape[0]
    for y in range(0, H, 256):
        n = np.clip(score[y:y + 256], 0, 1)
        color = cv2.cvtColor(cv2.applyColorMap((n * 255).astype(np.uint8), cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)
        a = (0.65 * np.clip(n * 1.5, 0, 1))[..., None]
        out[y:y + 256] = (rgb[y:y + 256] * (1 - a) + color * a).astype(np.uint8)
    return out


def mask_overlay(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Original with a translucent red fill and outline where mask is set."""
    out = rgb.copy()
    sel = mask > 0
    out[sel] = (0.55 * out[sel] + 0.45 * np.array([255, 40, 40])).astype(np.uint8)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, cnts, -1, (255, 255, 0), max(1, round(max(mask.shape) / 600)))
    return out


def score_png16(score: np.ndarray) -> bytes:
    """16-bit grayscale PNG of a [0,1] score map (kept so thresholds can be re-applied later)."""
    arr = np.clip(score * 65535.0 + 0.5, 0, 65535).astype(np.uint16)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def red_layer_png(score_png: bytes, threshold: float, min_area: int) -> tuple[bytes, int]:
    """Transparent red RGBA layer (+ region count) for a stored 16-bit score map at a new threshold."""
    arr = np.asarray(Image.open(io.BytesIO(score_png)))
    score = arr.astype(np.float32) / 65535.0
    mask, regions = threshold_mask(score, threshold, min_area)
    layer = np.zeros((*mask.shape, 4), np.uint8)
    layer[mask > 0] = (255, 40, 40, 150)
    buf = io.BytesIO()
    Image.fromarray(layer, "RGBA").save(buf, "PNG")
    return buf.getvalue(), len(regions)
