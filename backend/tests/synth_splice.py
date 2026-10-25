"""Synthetic splicing cases with known masks."""
import cv2
import numpy as np

from tests import synth


def photo_like(w=640, h=480, seed=0, noise=3.0) -> np.ndarray:
    """Smooth textured scene with sensor-like additive noise (so noise statistics are meaningful)."""
    base = synth.textured(w, h, seed=seed).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 1.5)
    rng = np.random.default_rng(seed + 1000)
    return np.clip(base + rng.normal(0, noise, base.shape), 0, 255).astype(np.uint8)


def splice(base: np.ndarray, donor_seed=77, donor_noise=9.0, shape="rect", box=(250, 150, 160, 130), blend=0):
    """Paste a patch from a *different* source (different noise level) into base. Returns (image, gt_mask)."""
    h, w = base.shape[:2]
    donor = photo_like(w, h, seed=donor_seed, noise=donor_noise)
    x, y, bw, bh = box
    m = np.zeros((h, w), np.uint8)
    if shape == "ellipse":
        cv2.ellipse(m, (x + bw // 2, y + bh // 2), (bw // 2, bh // 2), 0, 0, 360, 255, -1)
    else:
        m[y:y + bh, x:x + bw] = 255
    a = (cv2.GaussianBlur(m, (0, 0), blend).astype(np.float32) / 255.0)[..., None] if blend else (m[..., None] / 255.0).astype(np.float32)
    out = (base * (1 - a) + donor * a).astype(np.uint8)
    return out, m


def jpeg_roundtrip(img: np.ndarray, quality: int) -> np.ndarray:
    ok, enc = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.cvtColor(cv2.imdecode(enc, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
