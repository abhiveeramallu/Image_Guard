"""Synthetic image generators with known ground truth (no external downloads)."""
import cv2
import numpy as np


def textured(w=800, h=600, seed=0) -> np.ndarray:
    """Natural-ish RGB texture: multi-scale smoothed noise plus random shapes. Unique everywhere."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.float32)
    for sigma, amp in ((2, 60), (6, 70), (20, 80)):
        n = rng.normal(0, 1, (h, w, 3)).astype(np.float32)
        n = cv2.GaussianBlur(n, (0, 0), sigma)
        n /= n.std() + 1e-6
        img += n * amp
    img += 128
    out = np.clip(img, 0, 255).astype(np.uint8)
    for _ in range(60):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        if rng.random() < 0.5:
            cv2.circle(out, (x, y), int(rng.integers(5, 30)), c, -1 if rng.random() < .5 else 2)
        else:
            cv2.rectangle(out, (x, y), (x + int(rng.integers(10, 50)), y + int(rng.integers(10, 50))), c, -1 if rng.random() < .5 else 2)
    return cv2.GaussianBlur(out, (0, 0), 0.8)


def copy_move(img: np.ndarray, src=(100, 100, 120, 100), dst=(450, 300), angle=0.0, scale=1.0):
    """Paste patch src=(x,y,w,h) at dst=(x,y). Returns (forged, gt_mask_union, gt_src_mask, gt_dst_mask)."""
    x, y, w, h = src
    patch = img[y:y + h, x:x + w].copy()
    if angle or scale != 1.0:
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
        patch = cv2.warpAffine(patch, M, (w, h), borderMode=cv2.BORDER_REFLECT)
    out = img.copy()
    dx, dy = dst
    out[dy:dy + h, dx:dx + w] = patch
    gs = np.zeros(img.shape[:2], np.uint8); gs[y:y + h, x:x + w] = 255
    gd = np.zeros(img.shape[:2], np.uint8); gd[dy:dy + h, dx:dx + w] = 255
    return out, cv2.bitwise_or(gs, gd), gs, gd


def iou(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a > 0, b > 0
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 0.0
