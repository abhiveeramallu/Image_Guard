import cv2
import numpy as np
import pytest

from app.services.copy_move_service import CopyMoveParams, detect_copy_move
from tests import synth


def bbox_ok(b, w, h):
    return b["x"] >= 0 and b["y"] >= 0 and b["width"] > 0 and b["height"] > 0 and b["x"] + b["width"] <= w and b["y"] + b["height"] <= h


def test_translation_copy_move_detected_with_iou():
    ious = []
    for seed in range(5):
        forged, gt, gs, gd = synth.copy_move(synth.textured(seed=seed))
        out = detect_copy_move(forged)
        assert out.status == "candidate_regions_found", f"seed {seed}: {out.status_reason}"
        assert len(out.regions) == 1
        r = out.regions[0]
        # the two reported regions must sit on the true source and destination (in either order)
        boxes = [r.region_a["bbox"], r.region_b["bbox"]]
        centers = sorted([(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2) for b in boxes])
        assert abs(centers[0][0] - 160) < 40 and abs(centers[0][1] - 150) < 40
        assert abs(centers[1][0] - 510) < 40 and abs(centers[1][1] - 350) < 40
        assert abs(abs(r.transform["translation_x"]) - 350) < 6 and abs(abs(r.transform["translation_y"]) - 200) < 6
        ious.append(synth.iou(out.mask, gt))
    assert np.mean(ious) > 0.5 and min(ious) > 0.35


def test_rotated_and_scaled_copy_detected():
    base = synth.textured(seed=1)
    for kw in ({"angle": 20}, {"scale": 0.8}):
        forged, gt, *_ = synth.copy_move(base, **kw)
        out = detect_copy_move(forged)
        assert out.status == "candidate_regions_found"
        assert synth.iou(out.mask, gt) > 0.2


@pytest.mark.parametrize("seed", range(5))
def test_unmodified_random_texture_has_no_candidates(seed):
    out = detect_copy_move(synth.textured(seed=seed))
    assert out.status == "no_candidate_regions_found"
    assert out.regions == [] and out.mask.max() == 0


def test_blank_image_is_inconclusive_not_clean():
    out = detect_copy_move(np.full((300, 400, 3), 120, np.uint8))
    assert out.status == "inconclusive" and out.keypoints < 50
    assert out.mask.shape == (300, 400) and out.mask.max() == 0


def test_low_texture_gradient_inconclusive():
    g = np.tile(np.linspace(0, 255, 400, dtype=np.uint8), (300, 1))
    out = detect_copy_move(np.stack([g] * 3, axis=2))
    assert out.status == "inconclusive"


def test_repeated_pattern_not_reported_as_single_forgery():
    # Regular tiled texture: many periodic self-matches. Must not claim a confident single-region finding.
    tile = synth.textured(64, 64, seed=9)
    pattern = np.tile(tile, (8, 10, 1))
    out = detect_copy_move(pattern)
    assert out.status in ("inconclusive", "no_candidate_regions_found")


def test_small_duplicated_object_is_flagged_as_candidate():
    # Documents (not hides) the known weakness: a genuinely duplicated object is reported as a candidate.
    base = synth.textured(seed=2)
    forged, *_ = synth.copy_move(base, src=(50, 50, 90, 90), dst=(300, 350))
    assert detect_copy_move(forged).status == "candidate_regions_found"


@pytest.mark.parametrize("w,h", [(320, 240), (1000, 400), (400, 1000)])
def test_various_dimensions_and_bounds(w, h):
    base = synth.textured(w, h, seed=4)
    forged, *_ = synth.copy_move(base, src=(20, 20, 100, 90), dst=(w - 140, h - 130))
    out = detect_copy_move(forged)
    assert out.annotated.shape == (h, w, 3) and out.mask.shape == (h, w) and out.heatmap.shape == (h, w, 3)
    assert out.original_size == (w, h)
    for r in out.regions:
        assert bbox_ok(r.region_a["bbox"], w, h) and bbox_ok(r.region_b["bbox"], w, h)
        for poly in (r.region_a["polygon"], r.region_b["polygon"]):
            assert all(0 <= x < w and 0 <= y < h for x, y in poly)


def test_downscaled_analysis_maps_back_to_original_coordinates():
    base = synth.textured(1600, 1200, seed=5)
    forged, gt, *_ = synth.copy_move(base, src=(200, 200, 300, 250), dst=(1000, 700))
    out = detect_copy_move(forged, CopyMoveParams(max_dimension=800))
    assert out.scale == 0.5 and out.analysis_size == (800, 600)
    assert out.status == "candidate_regions_found"
    assert synth.iou(out.mask, gt) > 0.35
    assert out.mask.shape == (1200, 1600)


def test_artifacts_reflect_detection():
    forged, gt, *_ = synth.copy_move(synth.textured(seed=0))
    out = detect_copy_move(forged)
    assert not np.array_equal(out.annotated, forged)       # boxes drawn
    assert not np.array_equal(out.heatmap, forged)         # overlay drawn
    assert set(np.unique(out.mask)) <= {0, 255}
    inside = np.abs(out.annotated.astype(int) - forged.astype(int)).sum(axis=2) > 0
    assert inside.sum() > 0
    clean = detect_copy_move(synth.textured(seed=0))
    assert np.array_equal(clean.annotated, synth.textured(seed=0))  # nothing drawn when nothing found


def test_input_not_mutated():
    forged, *_ = synth.copy_move(synth.textured(seed=0))
    before = forged.copy()
    detect_copy_move(forged)
    assert np.array_equal(before, forged)


def test_counts_are_monotonic_and_consistent():
    forged, *_ = synth.copy_move(synth.textured(seed=0))
    out = detect_copy_move(forged)
    assert out.keypoints >= out.matches_before_filtering >= out.matches_after_descriptor_filtering >= out.matches_retained > 0
    assert out.matches_retained == sum(r.matches for r in out.regions)
