"""Attack Lab service: controlled image transformations, ground-truth tracking,
independent forensic analysis, and evaluation metrics.
"""
from __future__ import annotations

import base64
import html
import io
import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageFilter

from app.core.config import get_settings
from app.core.errors import ApiError
from app.services import copy_move_service as cm
from app.services import image_service as imgs
from app.services import invisible_watermark_service as iw
from app.services import localization_service as loc
from app.services import splicing_service as sp
from app.services.forensics_common import heatmap_overlay, mask_overlay, score_png16

log = logging.getLogger("imageguard.attack_lab")
settings = get_settings()

ATTACK_LAB_DISCLAIMER = (
    "This Attack Lab is an educational and forensic evaluation workspace. "
    "Transformations are applied in a controlled simulation with known ground truth. "
    "Forensic detectors evaluate the modified image independently without prior knowledge of the manipulation. "
    "Results are indicators for review, not legal proof of authenticity or tampering. "
    "The presence of a watermark does not prove genuine origin, nor does its absence prove forgery."
)


def pixel_counts(pred: np.ndarray, gt: np.ndarray) -> dict[str, int]:
    """Compute TP, FP, TN, FN pixel counts between binary prediction and ground truth masks."""
    p, g = pred > 0, gt > 0
    return {
        "tp": int((p & g).sum()),
        "fp": int((p & ~g).sum()),
        "tn": int((~p & ~g).sum()),
        "fn": int((~p & g).sum()),
    }


def prf(c: dict[str, int]) -> dict[str, float | None]:
    """Compute Precision, Recall, F1, and IoU from pixel count dict."""
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn and tp + fn > 0) else None
    iou = tp / (tp + fp + fn) if (tp + fp + fn and tp + fn > 0) else None
    return {"precision": precision, "recall": recall, "f1": f1, "iou": iou}


def parse_hex_color(hex_str: str) -> tuple[int, int, int]:
    """Parse #RRGGBB or #RGB to (R, G, B) tuple."""
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return (0, 0, 0)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 0, 0)


# -----------------------------------------------------------------------------
# Transformations
# -----------------------------------------------------------------------------

def occlude_watermark(
    image_rgb: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
    color_hex: str = "#000000",
    opacity: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Cover a rectangular patch with a solid or semi-transparent color."""
    H, W = image_rgb.shape[:2]
    if width <= 0 or height <= 0:
        raise ApiError(422, "invalid_parameters", "Patch width and height must be positive integers.")
    if x < 0 or y < 0 or x >= W or y >= H:
        raise ApiError(422, "invalid_parameters", f"Patch origin ({x}, {y}) is outside image bounds ({W}x{H}).")

    opacity = max(0.0, min(1.0, float(opacity)))
    color_rgb = np.array(parse_hex_color(color_hex), dtype=np.float32)

    x2 = min(W, x + width)
    y2 = min(H, y + height)
    actual_w = x2 - x
    actual_h = y2 - y

    out = image_rgb.copy()
    patch = out[y:y2, x:x2].astype(np.float32)
    blended = np.round(opacity * color_rgb + (1.0 - opacity) * patch).astype(np.uint8)
    out[y:y2, x:x2] = blended

    # Ground-truth mask
    gt_mask = np.zeros((H, W), dtype=np.uint8)
    gt_mask[y:y2, x:x2] = 255

    meta = {
        "x": x, "y": y, "width": actual_w, "height": actual_h,
        "color": color_hex, "opacity": opacity,
    }
    return out, gt_mask, meta


def crop_image(
    image_rgb: np.ndarray,
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    preset: str | None = None,
) -> tuple[np.ndarray, np.ndarray | None, dict[str, Any]]:
    """Crop image using coordinates or preset."""
    H, W = image_rgb.shape[:2]
    if preset == "edge_small":
        # 5% crop off bottom/right edges
        x, y = 0, 0
        width = max(16, int(round(W * 0.95)))
        height = max(16, int(round(H * 0.95)))
    elif preset == "watermark_corner":
        # Crops off 15% bottom-right corner where watermarks are commonly placed
        x, y = 0, 0
        width = max(16, int(round(W * 0.85)))
        height = max(16, int(round(H * 0.85)))
    elif preset == "preserve_watermark":
        # Crops top/left 15%, preserving bottom-right
        x = int(round(W * 0.15))
        y = int(round(H * 0.15))
        width = W - x
        height = H - y
    else:
        if width is None or height is None:
            raise ApiError(422, "invalid_parameters", "Width and height must be provided for custom crop.")

    if width < 16 or height < 16:
        raise ApiError(422, "invalid_parameters", "Cropped image must be at least 16x16 pixels.")
    if x < 0 or y < 0 or x + width > W or y + height > H:
        raise ApiError(422, "invalid_parameters", f"Crop box ({x}, {y}, {width}, {height}) exceeds image bounds ({W}x{H}).")

    out = image_rgb[y:y + height, x:x + width].copy()
    meta = {
        "preset": preset or "custom",
        "crop_box": {"x": x, "y": y, "width": width, "height": height},
        "original_size": [W, H],
        "output_size": [width, height],
    }
    return out, None, meta


def blur_image(image_rgb: np.ndarray, radius: float = 3.0) -> tuple[np.ndarray, None, dict[str, Any]]:
    """Apply Gaussian blur with radius in [0.5, 50.0]."""
    radius = float(radius)
    if radius < 0.5 or radius > 50.0:
        raise ApiError(422, "invalid_parameters", "Blur radius must be between 0.5 and 50.0.")

    out = cv2.GaussianBlur(image_rgb, (0, 0), sigmaX=radius, sigmaY=radius)
    meta = {"radius": radius, "method": "gaussian"}
    return out, None, meta


def jpeg_recompress(
    image_rgb: np.ndarray,
    quality: int = 70,
    source_format: str = "PNG",
) -> tuple[np.ndarray, None, dict[str, Any], bytes]:
    """Recompress image as lossy JPEG at specified quality [1, 100]."""
    quality = int(quality)
    if quality < 1 or quality > 100:
        raise ApiError(422, "invalid_parameters", "JPEG quality must be between 1 and 100.")

    buf = io.BytesIO()
    Image.fromarray(image_rgb).save(buf, "JPEG", quality=quality, optimize=True)
    jpeg_bytes = buf.getvalue()

    reopened = Image.open(io.BytesIO(jpeg_bytes))
    out = np.asarray(reopened.convert("RGB"))
    meta = {
        "quality": quality,
        "is_lossy_jpeg": True,
        "source_format": source_format,
        "compressed_bytes": len(jpeg_bytes),
    }
    return out, None, meta, jpeg_bytes


def resize_image(
    image_rgb: np.ndarray,
    scale: float = 0.75,
    max_pixels: int = 16_000_000,
) -> tuple[np.ndarray, None, dict[str, Any]]:
    """Resize image by scale factor."""
    scale = float(scale)
    if scale < 0.1 or scale > 4.0:
        raise ApiError(422, "invalid_parameters", "Resize scale must be between 0.1 and 4.0.")

    H, W = image_rgb.shape[:2]
    new_w = max(16, int(round(W * scale)))
    new_h = max(16, int(round(H * scale)))

    if new_w * new_h > max_pixels:
        raise ApiError(413, "image_too_large", f"Resized dimensions ({new_w}x{new_h}) exceed max pixel limit.")

    pil_img = Image.fromarray(image_rgb).resize((new_w, new_h), Image.Resampling.LANCZOS)
    out = np.asarray(pil_img)
    meta = {
        "scale": scale,
        "original_size": [W, H],
        "output_size": [new_w, new_h],
    }
    return out, None, meta


def rotate_image(
    image_rgb: np.ndarray,
    angle: float = 5.0,
    expand: bool = False,
) -> tuple[np.ndarray, None, dict[str, Any]]:
    """Rotate image by angle in [-180, 180] degrees."""
    angle = float(angle)
    if angle < -180.0 or angle > 180.0:
        raise ApiError(422, "invalid_parameters", "Rotation angle must be between -180 and 180 degrees.")

    pil_img = Image.fromarray(image_rgb).rotate(angle, resample=Image.Resampling.BICUBIC, expand=expand)
    out = np.asarray(pil_img)
    meta = {
        "angle": angle,
        "expand": expand,
        "interpolation": "bicubic",
        "border_note": "Rotation introduces black padding along non-axial borders." if not expand else "Image expanded to accommodate rotation.",
    }
    return out, None, meta


def copy_move_tamper(
    image_rgb: np.ndarray,
    src_x: int,
    src_y: int,
    src_w: int,
    src_h: int,
    dst_x: int,
    dst_y: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Simulate copy-move tampering: copy rectangular source region and paste at destination."""
    H, W = image_rgb.shape[:2]
    if src_w <= 0 or src_h <= 0:
        raise ApiError(422, "invalid_parameters", "Source region width and height must be positive.")
    if src_x < 0 or src_y < 0 or src_x + src_w > W or src_y + src_h > H:
        raise ApiError(422, "invalid_parameters", f"Source region ({src_x}, {src_y}, {src_w}, {src_h}) exceeds image bounds ({W}x{H}).")
    if dst_x < 0 or dst_y < 0 or dst_x + src_w > W or dst_y + src_h > H:
        raise ApiError(422, "invalid_parameters", f"Destination region ({dst_x}, {dst_y}, {src_w}, {src_h}) exceeds image bounds ({W}x{H}).")
    if src_x == dst_x and src_y == dst_y:
        raise ApiError(422, "invalid_parameters", "Destination coordinates must differ from source coordinates.")

    out = image_rgb.copy()
    patch = out[src_y:src_y + src_h, src_x:src_x + src_w].copy()
    out[dst_y:dst_y + src_h, dst_x:dst_x + src_w] = patch

    # Ground-truth mask: 255 at the manipulated destination region
    gt_mask = np.zeros((H, W), dtype=np.uint8)
    gt_mask[dst_y:dst_y + src_h, dst_x:dst_x + src_w] = 255

    meta = {
        "source": {"x": src_x, "y": src_y, "width": src_w, "height": src_h},
        "destination": {"x": dst_x, "y": dst_y, "width": src_w, "height": src_h},
    }
    return out, gt_mask, meta


def splice_content(
    image_rgb: np.ndarray,
    donor_rgb: np.ndarray,
    donor_x: int,
    donor_y: int,
    donor_w: int,
    donor_h: int,
    target_x: int,
    target_y: int,
    target_w: int,
    target_h: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Splice content from a donor image into the target image."""
    H, W = image_rgb.shape[:2]
    dH, dW = donor_rgb.shape[:2]

    if donor_w <= 0 or donor_h <= 0 or target_w <= 0 or target_h <= 0:
        raise ApiError(422, "invalid_parameters", "Donor and target dimensions must be positive.")
    if donor_x < 0 or donor_y < 0 or donor_x + donor_w > dW or donor_y + donor_h > dH:
        raise ApiError(422, "invalid_parameters", f"Donor crop ({donor_x}, {donor_y}, {donor_w}, {donor_h}) exceeds donor image bounds ({dW}x{dH}).")
    if target_x < 0 or target_y < 0 or target_x + target_w > W or target_y + target_h > H:
        raise ApiError(422, "invalid_parameters", f"Target region ({target_x}, {target_y}, {target_w}, {target_h}) exceeds target image bounds ({W}x{H}).")

    donor_crop = donor_rgb[donor_y:donor_y + donor_h, donor_x:donor_x + donor_w]
    if (donor_w, donor_h) != (target_w, target_h):
        pil_crop = Image.fromarray(donor_crop).resize((target_w, target_h), Image.Resampling.BICUBIC)
        donor_crop = np.asarray(pil_crop)

    out = image_rgb.copy()
    out[target_y:target_y + target_h, target_x:target_x + target_w] = donor_crop

    # Ground-truth mask: 255 at the inserted region
    gt_mask = np.zeros((H, W), dtype=np.uint8)
    gt_mask[target_y:target_y + target_h, target_x:target_x + target_w] = 255

    meta = {
        "donor_source": {"x": donor_x, "y": donor_y, "width": donor_w, "height": donor_h, "image_size": [dW, dH]},
        "target_region": {"x": target_x, "y": target_y, "width": target_w, "height": target_h},
    }
    return out, gt_mask, meta


def transform_ground_truth_mask(
    gt_mask: np.ndarray,
    transformation: str,
    meta: dict[str, Any],
) -> np.ndarray:
    """Transform an existing ground-truth mask using the exact geometric mapping of the transformation."""
    if transformation == "crop":
        box = meta.get("crop_box")
        if box:
            x, y, w, h = box["x"], box["y"], box["width"], box["height"]
            return gt_mask[y:y + h, x:x + w].copy()
        return gt_mask
    elif transformation == "resize":
        out_sz = meta.get("output_size")
        if out_sz:
            return cv2.resize(gt_mask, (out_sz[0], out_sz[1]), interpolation=cv2.INTER_NEAREST)
        return gt_mask
    elif transformation == "rotation":
        angle = float(meta.get("angle", 0.0))
        expand = bool(meta.get("expand", False))
        pil_mask = Image.fromarray(gt_mask).rotate(angle, resample=Image.Resampling.NEAREST, expand=expand)
        return np.asarray(pil_mask)
    return gt_mask


# -----------------------------------------------------------------------------
# Evaluation
# -----------------------------------------------------------------------------

def evaluate_detection(
    gt_mask: np.ndarray | None,
    pred_mask: np.ndarray | None,
    method_name: str,
) -> dict[str, Any] | None:
    """Evaluate detector prediction mask against ground truth mask."""
    if gt_mask is None or pred_mask is None:
        return None

    # Harmonize shapes if slightly mismatched due to scaling
    if gt_mask.shape != pred_mask.shape:
        pred_mask = cv2.resize(pred_mask, (gt_mask.shape[1], gt_mask.shape[0]), interpolation=cv2.INTER_NEAREST)

    counts = pixel_counts(pred_mask, gt_mask)
    metrics_prf = prf(counts)

    semantics_note = {
        "copy_move": "Evaluated against ORB candidate region polygon hulls. Note: Geometric convex hulls encompass more pixels than the raw manipulated patch, which normally lowers pixel precision.",
        "splicing": "Evaluated against pixel-level noise/ELA anomaly thresholded regions.",
        "localization": "Evaluated against model probability mask thresholded at default confidence.",
    }.get(method_name, "Pixel-level binary overlap evaluation.")

    return {
        "tp": counts["tp"],
        "fp": counts["fp"],
        "tn": counts["tn"],
        "fn": counts["fn"],
        "precision": round(metrics_prf["precision"], 4) if metrics_prf["precision"] is not None else None,
        "recall": round(metrics_prf["recall"], 4) if metrics_prf["recall"] is not None else None,
        "f1": round(metrics_prf["f1"], 4) if metrics_prf["f1"] is not None else None,
        "iou": round(metrics_prf["iou"], 4) if metrics_prf["iou"] is not None else None,
        "semantics_note": semantics_note,
    }


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------

def build_experiment_report(experiment_data: dict[str, Any]) -> dict[str, Any]:
    """Build structured JSON report for the experiment."""
    return {
        "report_generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disclaimer": ATTACK_LAB_DISCLAIMER,
        **experiment_data,
    }


def report_html_bytes(report: dict[str, Any], images: dict[str, bytes]) -> bytes:
    """Generate self-contained HTML report with embedded images and structured results."""
    e = html.escape

    def img_tag(name: str, caption: str) -> str:
        if name not in images or not images[name]:
            return ""
        b64 = base64.b64encode(images[name]).decode()
        return (
            f'<div class="figure-card">'
            f'<img alt="{e(caption)}" src="data:image/png;base64,{b64}">'
            f'<div class="caption">{e(caption)}</div>'
            f'</div>'
        )

    # History rows
    history_rows = "".join(
        f"<tr><td>#{s['step']}</td><td><b>{e(s['transformation'])}</b></td>"
        f"<td>{e(s['description'])}</td><td>{s['output_size'][0]}&times;{s['output_size'][1]}</td></tr>"
        for s in report.get("history", [])
    ) or '<tr><td colspan="4">No transformations applied (Baseline only)</td></tr>'

    # Detection rows
    detection_rows = ""
    for d in report.get("detection_results", []):
        method = d.get("method", "Unknown")
        status = d.get("status", "-")
        reason = d.get("status_reason", "-")
        regs = d.get("region_count", 0)
        ms = d.get("processing_ms", 0.0)
        detection_rows += (
            f"<tr><td><b>{e(method)}</b></td><td><span class='badge status-{e(status)}'>{e(status)}</span></td>"
            f"<td>{regs}</td><td>{ms} ms</td><td>{e(reason)}</td></tr>"
        )
    if not detection_rows:
        detection_rows = '<tr><td colspan="5">No detectors run</td></tr>'

    # Evaluation rows
    eval_rows = ""
    for ev in report.get("evaluation", []):
        m = ev.get("metrics")
        if not m:
            continue
        p = f"{m['precision']:.3f}" if m.get("precision") is not None else "-"
        r = f"{m['recall']:.3f}" if m.get("recall") is not None else "-"
        f1 = f"{m['f1']:.3f}" if m.get("f1") is not None else "-"
        iou = f"{m['iou']:.3f}" if m.get("iou") is not None else "-"
        eval_rows += (
            f"<tr><td><b>{e(ev['method'])}</b></td><td>{p}</td><td>{r}</td><td>{f1}</td><td>{iou}</td>"
            f"<td>TP:{m['tp']} FP:{m['fp']} FN:{m['fn']}</td></tr>"
        )
    if not eval_rows:
        eval_rows = '<tr><td colspan="6">No ground truth mask or matching detection mask available for quantitative evaluation</td></tr>'

    # Answers section
    answers = report.get("answers", {})
    ans_a = e(answers.get("question_a", "N/A"))
    ans_b = e(answers.get("question_b", "N/A"))
    ans_c = e(answers.get("question_c", "N/A"))

    # Watermark info
    wm_ver = report.get("watermark_verification")
    wm_html = ""
    if wm_ver:
        wm_status = wm_ver.get("status", "unavailable")
        wm_reason = wm_ver.get("status_reason", "")
        wm_owner = wm_ver.get("owner", "n/a")
        wm_html = (
            f"<div class='info-box'>"
            f"<h3>Invisible Watermark Verification</h3>"
            f"<p><b>Status:</b> <span class='badge status-{e(wm_status)}'>{e(wm_status)}</span> &mdash; {e(wm_reason)}</p>"
            f"<p><b>Recovered Owner:</b> <code>{e(str(wm_owner))}</code></p>"
            f"</div>"
        )

    # Baseline configuration
    base = report.get("baseline") or report.get("baseline_image") or {}
    base_format = e(str(base.get("format", "PNG")))
    base_dim = f"{base.get('width', '-')} &times; {base.get('height', '-')}"
    base_vis = e(str(base.get("visible_watermark_text") if base.get("has_visible_watermark") else "None"))
    base_invis = e(str(base.get("invisible_owner") if base.get("has_invisible_watermark") else "None"))

    # Baseline notice
    is_baseline_only = len(report.get("history", [])) == 0
    baseline_notice_html = ""
    if is_baseline_only:
        baseline_notice_html = (
            "<div class='note' style='border-left-color: #3b82f6; background: #eff6ff;'>"
            "<b>Baseline-Only Reference Analysis:</b> No attack transformations were applied in this experiment. "
            "Forensic detectors evaluated the unmodified protected baseline to establish a reference detection profile. "
            "Any candidate regions flagged represent natural image features, repeated textures, or heuristic false positives on clean input—not proof of tampering."
            "</div>"
        )

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ImageGuard Attack Lab Report &mdash; {e(report.get('experiment_id', ''))}</title>
<style>
  body {{ font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; max-width: 1040px; margin: 2rem auto; padding: 0 1.5rem; color: #1e293b; background: #f8fafc; }}
  h1, h2, h3 {{ color: #0f172a; margin-top: 1.5rem; }}
  .header {{ background: #0f172a; color: white; padding: 1.5rem; border-radius: 8px; margin-bottom: 2rem; }}
  .header h1 {{ color: white; margin: 0 0 0.5rem 0; font-size: 1.5rem; }}
  .note {{ background: #eff6ff; border-left: 4px solid #3b82f6; padding: 0.75rem 1rem; border-radius: 4px; margin: 1rem 0; }}
  .warning {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 0.75rem 1rem; border-radius: 4px; margin: 1rem 0; font-size: 13px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; background: white; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  th, td {{ border: 1px solid #e2e8f0; padding: 0.6rem 0.8rem; text-align: left; }}
  th {{ background: #f1f5f9; font-weight: 600; color: #334155; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.25rem; margin: 1rem 0; }}
  .figure-card {{ background: white; border: 1px solid #e2e8f0; border-radius: 6px; padding: 0.5rem; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  .figure-card img {{ max-width: 100%; height: auto; border-radius: 4px; display: block; margin: 0 auto; }}
  .caption {{ font-size: 12px; font-weight: 600; color: #475569; margin-top: 0.5rem; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
  .status-verified, .status-suspicious_regions_found {{ background: #dcfce7; color: #166534; }}
  .status-not_detected, .status-no_suspicious_regions {{ background: #f1f5f9; color: #475569; }}
  .status-inconclusive {{ background: #fef3c7; color: #92400e; }}
  .status-failed, .status-unavailable {{ background: #fee2e2; color: #991b1b; }}
  .info-box {{ background: white; border: 1px solid #e2e8f0; border-radius: 6px; padding: 1rem; margin: 1rem 0; }}
  .qa-card {{ background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 1rem; margin-bottom: 0.75rem; }}
  .qa-title {{ font-weight: bold; color: #0284c7; margin-bottom: 0.25rem; }}
</style>
</head>
<body>

<div class="header">
  <h1>ImageGuard &mdash; Watermark Attack &amp; Tampering Lab Report</h1>
  <div><b>Experiment ID:</b> {e(report.get('experiment_id', ''))} | <b>Generated:</b> {e(report.get('report_generated_at', ''))}</div>
</div>

<div class="warning">
  <b>Disclaimer &amp; Methodological Notice:</b> {e(report.get('disclaimer', ''))}
</div>

{baseline_notice_html}

<h2>Core Forensic Questions</h2>
<div class="qa-card">
  <div class="qa-title">Question A: Was the image changed in the experiment?</div>
  <div>{ans_a}</div>
</div>
<div class="qa-card">
  <div class="qa-title">Question B: Was the watermark damaged or still verifiable?</div>
  <div>{ans_b}</div>
</div>
<div class="qa-card">
  <div class="qa-title">Question C: Did a forgery detector identify suspicious evidence?</div>
  <div>{ans_c}</div>
</div>

{wm_html}

<h2>Protected Baseline Configuration</h2>
<table>
  <thead>
    <tr><th>Format</th><th>Dimensions</th><th>Visible Watermark</th><th>Invisible Watermark</th></tr>
  </thead>
  <tbody>
    <tr><td>{base_format}</td><td>{base_dim}</td><td>{base_vis}</td><td>{base_invis}</td></tr>
  </tbody>
</table>

<h2>Experiment Image Artifacts</h2>
<div class="grid">
  {img_tag('original.png', '1. Original Source Image')}
  {img_tag('baseline.png', '2. Protected Baseline Image')}
  {img_tag('modified.png', '3. Modified Image')}
  {img_tag('ground_truth.png', '4. Simulated Ground-Truth Mask')}
  {img_tag('copy_move.annotated', '5. Copy-Move Detection Overlay')}
  {img_tag('splicing.overlay', '6. Splicing Heuristic Overlay')}
</div>

<h2>Transformation Sequence</h2>
<table>
  <thead>
    <tr><th>Step</th><th>Operation</th><th>Details</th><th>Output Dimensions</th></tr>
  </thead>
  <tbody>
    {history_rows}
  </tbody>
</table>

<h2>Detector Findings (Operated on Modified Image Independently)</h2>
<table>
  <thead>
    <tr><th>Method</th><th>Status</th><th>Regions Found</th><th>Processing Time</th><th>Finding Summary</th></tr>
  </thead>
  <tbody>
    {detection_rows}
  </tbody>
</table>

<h2>Quantitative Evaluation vs Simulated Ground Truth</h2>
<table>
  <thead>
    <tr><th>Method</th><th>Precision</th><th>Recall</th><th>F1 Score</th><th>IoU</th><th>Counts</th></tr>
  </thead>
  <tbody>
    {eval_rows}
  </tbody>
</table>

<h2>Method Limitations</h2>
<ul>
  <li><b>Copy-Move (ORB):</b> Detects duplicated keypoints clustered by geometric transformation. Misses featureless flat areas, severe blur, heavy compression, and non-rigid warping.</li>
  <li><b>Splicing (Noise/ELA):</b> Experimental heuristic measuring high-frequency inconsistencies and JPEG block artifacts. Prone to false alarms on natural high-contrast edges and textures.</li>
  <li><b>Invisible Watermark (DCT-QIM):</b> Designed to survive modest JPEG compression, but vulnerable to scale changes, non-trivial rotations, cropping of the DCT block grid, or heavy filtering.</li>
</ul>

</body>
</html>
"""
    return doc.encode("utf-8")
