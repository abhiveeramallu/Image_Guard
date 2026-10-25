"""EXPERIMENTAL splicing / local-inconsistency heuristic (not a trained or validated detector).

Two classical forensic cues, each turned into a robust z-score map and mapped to [0, 1]:

* Noise-residual inconsistency: the high-pass residual (image - 3x3 median) is averaged in
  local windows; regions whose log residual energy deviates strongly from the image-wide
  median (in MAD units) are flagged. Content from another source camera/processing chain
  often has a different noise level.
* Error-level analysis (JPEG inputs only): re-compress at a fixed quality and measure the
  local error. Regions with a different compression history respond differently.

The score is a normalised heuristic, NOT a probability. Natural texture, edges, sharpening,
vignetting and local retouching all trigger it; many splices will not.
"""
import time
from dataclasses import asdict, dataclass

import cv2
import numpy as np

from app.services.forensics_common import MapOutput, threshold_mask

METHOD_NAME = "noise-ela-heuristic"
METHOD_VERSION = "0.1.0-experimental"

LIMITATIONS = [
    "Experimental heuristic based on noise-residual and (for JPEG) error-level cues. It is not a trained model and has not been validated on real-world data.",
    "Cannot identify every splice: clean composites, matched noise, or re-saved/resized images defeat both cues.",
    "Natural texture changes, sharp edges, retouching and uneven lighting can produce false alarms.",
    "The score is a normalised heuristic, not a probability of manipulation.",
    "Error-level analysis only applies to JPEG uploads; for PNG only the noise cue is used.",
    "A result of 'no candidate regions' does not show the image is authentic.",
]


@dataclass
class SplicingParams:
    threshold: float = 0.5
    z_low: float = 4.0     # robust z at which score starts rising
    z_high: float = 8.0    # robust z at which score saturates at 1
    window: int = 0        # 0 = automatic from image size
    min_area_fraction: float = 0.002
    max_area_fraction: float = 0.5   # flagged area above this => inconclusive (global inhomogeneity)
    ela_quality: int = 90
    ela_z_low: float = 7.0   # ELA is strongly content-dependent, so it needs a stricter z than the noise cue
    ela_z_high: float = 11.0
    mad_floor: float = 0.15  # floor on the robust scale (log units) so nearly uniform images don't yield huge z-scores
    min_side: int = 128


def _robust_z(log_energy: np.ndarray, mad_floor: float) -> np.ndarray:
    med = float(np.median(log_energy))
    mad = float(np.median(np.abs(log_energy - med))) * 1.4826
    mad = max(mad, mad_floor)
    return np.abs(log_energy - med) / mad


def _to_score(z: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip((z - lo) / (hi - lo), 0, 1).astype(np.float32)


def detect_splicing(rgb: np.ndarray, is_jpeg: bool, params: SplicingParams | None = None) -> MapOutput:
    p = params or SplicingParams()
    t0 = time.perf_counter()
    H, W = rgb.shape[:2]
    warnings: list[str] = []
    settings = asdict(p)

    def done(status, reason, score=None, mask=None, regions=None, metrics=None):
        return MapOutput(status=status, status_reason=reason, score=score, threshold=p.threshold,
                         regions=regions or [], metrics={**(metrics or {}), "settings": settings}, warnings=warnings,
                         processing_ms=round((time.perf_counter() - t0) * 1000, 1), mask=mask)

    if min(H, W) < p.min_side:
        return done("inconclusive", f"Image is smaller than {p.min_side}px on one side; local statistics are unreliable.")

    win = p.window or max(32, min(H, W) // 16)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    res = gray.astype(np.float32) - cv2.medianBlur(gray, 3).astype(np.float32)
    energy = np.sqrt(cv2.boxFilter(res * res, -1, (win, win), borderType=cv2.BORDER_REFLECT))
    if float(np.median(energy)) < 0.15:
        warnings.append("Residual noise is almost zero (flat or synthetic content).")
        return done("inconclusive", "The image has too little texture/noise for the noise-inconsistency cue to be meaningful.")
    z_noise = _robust_z(np.log(energy + 0.05), p.mad_floor)
    score_noise = _to_score(z_noise, p.z_low, p.z_high)
    components = ["noise_residual"]
    score = score_noise
    metrics: dict = {"window_px": win, "noise_z_p99": round(float(np.percentile(z_noise, 99)), 2)}

    if is_jpeg:
        ok, enc = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, p.ela_quality])
        if ok:
            re = cv2.cvtColor(cv2.imdecode(enc, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            ela = np.abs(rgb.astype(np.float32) - re.astype(np.float32)).mean(axis=2)
            ela_local = cv2.boxFilter(ela, -1, (win, win), borderType=cv2.BORDER_REFLECT)
            z_ela = _robust_z(np.log(ela_local + 0.05), p.mad_floor)
            score_ela = _to_score(z_ela, p.ela_z_low, p.ela_z_high)
            score = np.maximum(score, score_ela)
            components.append("error_level_analysis")
            metrics["ela_z_p99"] = round(float(np.percentile(z_ela, 99)), 2)
    else:
        warnings.append("Input is not a JPEG, so error-level analysis was skipped.")

    score = cv2.GaussianBlur(score, (0, 0), max(2.0, win / 8))
    mask, regions = threshold_mask(score, p.threshold, max(64, int(p.min_area_fraction * H * W)), close_px=9)
    frac = float((mask > 0).mean())
    metrics.update({"components": components, "max_score": round(float(score.max()), 3),
                    "flagged_area_fraction": round(frac, 4), "threshold_semantics": "normalised heuristic score (not a probability)"})
    for r in regions:
        r["area_fraction"] = round(r["area_px"] / (H * W), 4)

    if frac > p.max_area_fraction:
        return done("inconclusive", f"{frac:.0%} of the image was flagged, which suggests global inhomogeneity rather than a local splice.",
                    score, mask, regions, metrics)
    if regions:
        return done("candidate_regions_found",
                    f"{len(regions)} region(s) have noise/compression statistics that differ strongly from the rest of the image. Heuristic only; review visually.",
                    score, mask, regions, metrics)
    return done("no_candidate_regions_found", "No region exceeded the heuristic threshold.", score, np.zeros((H, W), np.uint8), [], metrics)
