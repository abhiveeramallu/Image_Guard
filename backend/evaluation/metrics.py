"""Pixel- and image-level metrics."""
import numpy as np


def pixel_counts(pred: np.ndarray, gt: np.ndarray) -> dict:
    p, g = pred > 0, gt > 0
    return {"tp": int((p & g).sum()), "fp": int((p & ~g).sum()), "tn": int((~p & ~g).sum()), "fn": int((~p & g).sum())}


def prf(c: dict) -> dict:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn and tp + fn > 0) else None
    iou = tp / (tp + fp + fn) if (tp + fp + fn and tp + fn > 0) else None
    return {"precision": precision, "recall": recall, "f1": f1, "iou": iou}


def aggregate_pixels(rows: list[dict]) -> dict:
    """Micro-average: sum counts over images that have ground-truth positives or predictions."""
    tot = {k: sum(r[k] for r in rows) for k in ("tp", "fp", "tn", "fn")}
    return {**tot, **prf(tot)}


def image_level(rows: list[tuple[bool, bool]]) -> dict:
    """rows: (is_manipulated, predicted_positive)."""
    tp = sum(1 for g, p in rows if g and p)
    fp = sum(1 for g, p in rows if not g and p)
    tn = sum(1 for g, p in rows if not g and not p)
    fn = sum(1 for g, p in rows if g and not p)
    n = len(rows)
    return {"n": n, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "accuracy": (tp + tn) / n if n else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None}
