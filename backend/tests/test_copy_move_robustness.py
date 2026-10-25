"""Deterministic regression tests for Copy-Move Tampering Transformation, ORB Detection,
and Forensic Evaluation.

Validates:
1. Transformation correctness (pixel copy, bounds, overlapping regions, ground truth mask).
2. Detector responsiveness on textured copy-move (both non-overlapping and partially overlapping).
3. Negative cases rejection: clean scene, flat low-texture, smooth gradient, repeated pattern.
4. Mathematical exactness of ground-truth evaluation metrics and undefined state handling.
5. Safe diagnostic output (keypoints, raw matches, filtered matches, retained, clusters).
"""
import cv2
import numpy as np
import pytest

from app.core.errors import ApiError
from app.services import attack_lab_service as lab
from app.services.copy_move_service import CopyMoveParams, detect_copy_move
from tests import synth


# ---------------------------------------------------------------------------
# 1. Transformation Tests
# ---------------------------------------------------------------------------

def test_copy_move_transformation_pixels_and_gt():
    """Verify that source pixels are accurately copied to destination and GT mask marks destination."""
    img = synth.textured(w=600, h=400, seed=10)
    orig = img.copy()

    # 160x110 patch (area 17,600 px)
    src_x, src_y, w, h = 40, 50, 160, 110
    dst_x, dst_y = 300, 200

    mod, gt, meta = lab.copy_move_tamper(img, src_x, src_y, w, h, dst_x, dst_y)

    # Original array was untouched
    assert np.array_equal(img, orig)

    # Destination in modified image exactly matches original source patch
    assert np.array_equal(mod[dst_y:dst_y + h, dst_x:dst_x + w], orig[src_y:src_y + h, src_x:src_x + w])

    # Unaffected regions remain identical
    assert np.array_equal(mod[:src_y, :], orig[:src_y, :])

    # Ground truth mask marks exactly the manipulated destination area
    assert gt.shape == (400, 600)
    assert (gt[dst_y:dst_y + h, dst_x:dst_x + w] == 255).all()
    assert (gt > 0).sum() == 17600

    # Metadata records coordinates
    assert meta["source"] == {"x": src_x, "y": src_y, "width": w, "height": h}
    assert meta["destination"] == {"x": dst_x, "y": dst_y, "width": w, "height": h}


def test_copy_move_overlapping_regions():
    """Verify that overlapping source and destination regions copy pristine pixels and mark destination."""
    img = synth.textured(w=600, h=400, seed=20)
    orig = img.copy()

    # Partial overlap: src [50..210, 50..160], dst [100..260, 100..210]
    src_x, src_y, w, h = 50, 50, 160, 110
    dst_x, dst_y = 100, 100

    mod, gt, meta = lab.copy_move_tamper(img, src_x, src_y, w, h, dst_x, dst_y)

    # Copied patch at destination matches pristine original source patch
    assert np.array_equal(mod[dst_y:dst_y + h, dst_x:dst_x + w], orig[src_y:src_y + h, src_x:src_x + w])
    assert (gt[dst_y:dst_y + h, dst_x:dst_x + w] == 255).all()
    assert (gt > 0).sum() == 17600


def test_copy_move_boundary_validation():
    """Verify bounds and coordinate validation."""
    img = synth.textured(w=400, h=300, seed=30)
    # Zero / negative size
    with pytest.raises(ApiError) as exc_info:
        lab.copy_move_tamper(img, 10, 10, 0, 50, 100, 100)
    assert exc_info.value.code == "invalid_parameters"

    # Out of bounds source
    with pytest.raises(ApiError):
        lab.copy_move_tamper(img, 300, 10, 150, 50, 50, 50)

    # Out of bounds destination
    with pytest.raises(ApiError):
        lab.copy_move_tamper(img, 10, 10, 50, 50, 380, 50)

    # Identical src and dst
    with pytest.raises(ApiError):
        lab.copy_move_tamper(img, 50, 50, 60, 60, 50, 50)


# ---------------------------------------------------------------------------
# 2. Positive Detection Tests (Displaced and Overlapping)
# ---------------------------------------------------------------------------

def test_positive_copy_move_non_overlapping():
    """Verify detector identifies clean non-overlapping copy-move with candidate regions and high metrics."""
    base = synth.textured(w=800, h=600, seed=42)
    src_x, src_y, w, h = 50, 50, 160, 110
    dst_x, dst_y = 350, 250

    mod, gt, _ = lab.copy_move_tamper(base, src_x, src_y, w, h, dst_x, dst_y)

    # Detector runs strictly without seeing ground truth
    out = detect_copy_move(mod)
    assert out.status == "candidate_regions_found"
    assert len(out.regions) >= 1
    assert out.matches_retained >= 6
    assert out.keypoints >= 50
    assert out.matches_before_filtering > 0
    assert out.matches_after_descriptor_filtering > 0

    # Evaluate prediction mask against destination ground truth
    ev = lab.evaluate_detection(gt, out.mask, "copy_move")
    assert ev is not None
    assert ev["tp"] > 0
    assert ev["recall"] > 0.4
    assert ev["iou"] > 0.2


def test_positive_copy_move_partially_overlapping():
    """Verify detector handles partially overlapping copy-move without premature bbox rejection."""
    base = synth.textured(w=800, h=600, seed=42)
    # 160x110 patch, offset by 50 in x and y (overlapping area = 110 x 60 = 6,600 px)
    src_x, src_y, w, h = 50, 50, 160, 110
    dst_x, dst_y = 100, 100

    mod, gt, _ = lab.copy_move_tamper(base, src_x, src_y, w, h, dst_x, dst_y)

    out = detect_copy_move(mod)
    assert out.status == "candidate_regions_found", f"Failed with reason: {out.status_reason}"
    assert len(out.regions) >= 1
    assert out.matches_retained >= 6

    ev = lab.evaluate_detection(gt, out.mask, "copy_move")
    assert ev is not None
    assert ev["tp"] > 0
    assert ev["recall"] > 0.2
    assert ev["iou"] > 0.15


# ---------------------------------------------------------------------------
# 3. Negative Detection Tests
# ---------------------------------------------------------------------------

def test_negative_clean_image_no_candidates():
    """Clean unmanipulated textured scene must produce no candidate regions."""
    clean = synth.textured(w=800, h=600, seed=99)
    out = detect_copy_move(clean)
    assert out.status == "no_candidate_regions_found"
    assert len(out.regions) == 0
    assert out.matches_retained == 0
    assert (out.mask == 0).all()


def test_negative_flat_low_texture_inconclusive():
    """Flat/monochrome image must be reported as inconclusive due to lack of texture."""
    flat = np.full((400, 500, 3), 180, dtype=np.uint8)
    out = detect_copy_move(flat)
    assert out.status == "inconclusive"
    assert out.keypoints < 50
    assert len(out.regions) == 0
    assert (out.mask == 0).all()


def test_negative_smooth_gradient_inconclusive():
    """Smooth luminance gradient has insufficient corner texture and must be inconclusive."""
    g = np.tile(np.linspace(20, 220, 500, dtype=np.uint8), (400, 1))
    grad = np.stack([g, g, g], axis=2)
    out = detect_copy_move(grad)
    assert out.status == "inconclusive"
    assert len(out.regions) == 0


def test_negative_repeated_pattern_not_single_forgery():
    """Repeated regular tiles produce multiple repetitive transforms and must be flagged as inconclusive/inconclusive patterns."""
    tile = synth.textured(w=64, h=64, seed=15)
    pattern = np.tile(tile, (6, 8, 1))
    out = detect_copy_move(pattern)
    assert out.status in ("inconclusive", "no_candidate_regions_found")
    if out.status == "inconclusive":
        assert "repeated" in out.status_reason.lower() or "pattern" in out.status_reason.lower()


# ---------------------------------------------------------------------------
# 4. Ground-Truth Evaluation & Undefined Metric Tests
# ---------------------------------------------------------------------------

def test_ground_truth_evaluation_mathematical_precision():
    """Verify TP, FP, FN, precision, recall, F1, and IoU calculations."""
    gt = np.zeros((100, 100), dtype=np.uint8)
    gt[10:30, 10:30] = 255  # 400 pixels

    pred = np.zeros((100, 100), dtype=np.uint8)
    pred[10:30, 20:40] = 255  # 400 pixels (overlap: 10..30 x 20..30 = 200 pixels)

    ev = lab.evaluate_detection(gt, pred, "copy_move")
    assert ev is not None
    assert ev["tp"] == 200
    assert ev["fp"] == 200
    assert ev["fn"] == 200
    assert ev["tn"] == 10000 - 600
    # precision = 200 / 400 = 0.5
    assert ev["precision"] == 0.5
    # recall = 200 / 400 = 0.5
    assert ev["recall"] == 0.5
    # f1 = 2 * 200 / (2 * 200 + 200 + 200) = 400 / 800 = 0.5
    assert ev["f1"] == 0.5
    # iou = 200 / (200 + 200 + 200) = 200 / 600 = 0.3333
    assert abs(ev["iou"] - 0.3333) < 1e-3


def test_ground_truth_undefined_metrics_handled():
    """When TP+FP=0 or TP+FN=0, undefined metrics must be None rather than fabricated."""
    # Empty GT, empty Pred
    counts = lab.pixel_counts(np.zeros((50, 50), dtype=np.uint8), np.zeros((50, 50), dtype=np.uint8))
    metrics = lab.prf(counts)
    assert metrics["precision"] is None
    assert metrics["recall"] is None
    assert metrics["f1"] is None
    assert metrics["iou"] is None

    # Empty Pred against positive GT (the failure mode that prompted this task)
    gt = np.zeros((100, 100), dtype=np.uint8)
    gt[10:50, 10:50] = 255  # 1600 px
    pred = np.zeros((100, 100), dtype=np.uint8)
    ev = lab.evaluate_detection(gt, pred, "copy_move")
    assert ev is not None
    assert ev["tp"] == 0
    assert ev["fp"] == 0
    assert ev["fn"] == 1600
    assert ev["precision"] is None  # Undefined (0 predicted positives)
    assert ev["recall"] == 0.0
    assert ev["f1"] == 0.0
    assert ev["iou"] == 0.0


# ---------------------------------------------------------------------------
# 5. Diagnostic Metadata Integrity
# ---------------------------------------------------------------------------

def test_diagnostic_metadata_fields():
    """Verify DetectionOutput provides all diagnostic counts without exposing secrets or paths."""
    img = synth.textured(w=400, h=300, seed=5)
    mod, _, _ = lab.copy_move_tamper(img, 20, 20, 80, 80, 150, 120)
    out = detect_copy_move(mod)

    # All diagnostic properties are integers >= 0
    assert isinstance(out.keypoints, int) and out.keypoints >= 0
    assert isinstance(out.matches_before_filtering, int) and out.matches_before_filtering >= 0
    assert isinstance(out.matches_after_descriptor_filtering, int) and out.matches_after_descriptor_filtering >= 0
    assert isinstance(out.matches_retained, int) and out.matches_retained >= 0
    assert isinstance(out.accepted_clusters, int) and out.accepted_clusters >= 0
    assert isinstance(out.rejected_clusters, int) and out.rejected_clusters >= 0

    # Status reason is informative prose, not empty
    assert len(out.status_reason) > 10
    # No server path leakage in reason or warnings
    assert "/Users" not in out.status_reason
    assert "/home" not in out.status_reason
    for w in out.warnings:
        assert "/Users" not in w and "/home" not in w
