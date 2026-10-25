import io
import json
import cv2
import numpy as np
import pytest
from PIL import Image

from tests import synth
from tests.conftest import to_bytes, decode


@pytest.fixture
def sample_image():
    return synth.textured(640, 480, seed=42)


def test_forgery_lab_analyze_unmodified(client, sample_image):
    """Submitting an unmodified image without ground-truth mask evaluates baseline detector behavior."""
    file_bytes = to_bytes(sample_image, "PNG")
    r = client.post(
        "/api/forgery-lab/analyze",
        files={"file": ("unmodified.png", file_bytes, "image/png")},
        data={"methods": "copy_move,splicing,watermark_verify"},
    )
    assert r.status_code == 200
    j = r.json()
    assert "experiment_id" in j
    assert j["image"]["width"] == 640
    assert j["image"]["height"] == 480
    assert len(j["detection_results"]) >= 1

    # Evaluation on clean image has 0 GT pixels
    assert "evaluation" in j
    for ev in j["evaluation"]:
        assert ev["method"] in ["copy_move", "splicing", "localization"]


def test_forgery_lab_analyze_with_manual_edit_and_gt(client, sample_image):
    """Painting scratches and providing ground-truth mask enables quantitative evaluation."""
    # Modified image with painted red stroke
    mod_img = sample_image.copy()
    cv2.rectangle(mod_img, (100, 100), (200, 160), (255, 0, 0), -1)

    # Ground-truth binary mask (white at edited region)
    gt_mask = np.zeros(sample_image.shape[:2], dtype=np.uint8)
    gt_mask[100:160, 100:200] = 255

    mod_bytes = to_bytes(mod_img, "PNG")
    gt_bytes = to_bytes(gt_mask, "PNG")
    orig_bytes = to_bytes(sample_image, "PNG")

    r = client.post(
        "/api/forgery-lab/analyze",
        files={
            "file": ("modified.png", mod_bytes, "image/png"),
            "original_file": ("orig.png", orig_bytes, "image/png"),
            "ground_truth_file": ("gt.png", gt_bytes, "image/png"),
        },
        data={"methods": "copy_move,splicing"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["ground_truth"]["has_mask"] is True
    assert len(j["evaluation"]) >= 1

    # Check artifacts are accessible
    exp_id = j["experiment_id"]
    mod_art = client.get(f"/api/forgery-lab/artifacts/{exp_id}/modified.png")
    assert mod_art.status_code == 200

    gt_art = client.get(f"/api/forgery-lab/artifacts/{exp_id}/ground_truth.png")
    assert gt_art.status_code == 200


def test_forgery_lab_analyze_copy_move(client, sample_image):
    """Copy-move forgery cloned onto textured background should trigger ORB candidate regions."""
    forged, union_gt, src_gt, dst_gt = synth.copy_move(
        sample_image, src=(80, 80, 140, 120), dst=(350, 240)
    )
    forged_bytes = to_bytes(forged, "PNG")
    gt_bytes = to_bytes(dst_gt, "PNG")

    r = client.post(
        "/api/forgery-lab/analyze",
        files={
            "file": ("cm_forged.png", forged_bytes, "image/png"),
            "ground_truth_file": ("gt.png", gt_bytes, "image/png"),
        },
        data={
            "methods": "copy_move",
            "ratio": 0.8,
            "min_matches": 5,
            "min_displacement": 20,
        },
    )
    assert r.status_code == 200
    j = r.json()
    cm_results = [r for r in j["detection_results"] if r["method"] == "copy_move"]
    assert len(cm_results) == 1
    cm = cm_results[0]
    assert cm["status"] == "candidate_regions_found"
    assert cm["region_count"] >= 1
    assert cm["metrics"]["retained_matches"] >= 5


def test_forgery_lab_reports_json_and_html(client, sample_image):
    """Generated analysis reports can be retrieved in both JSON and HTML formats."""
    file_bytes = to_bytes(sample_image, "PNG")
    r = client.post(
        "/api/forgery-lab/analyze",
        files={"file": ("img.png", file_bytes, "image/png")},
        data={"methods": "copy_move"},
    )
    assert r.status_code == 200
    j = r.json()
    exp_id = j["experiment_id"]

    # JSON report
    json_res = client.get(f"/api/forgery-lab/reports/{exp_id}?format=json")
    assert json_res.status_code == 200
    assert "application/json" in json_res.headers["content-type"]
    report_data = json_res.json()
    assert report_data["experiment_id"] == exp_id

    # HTML report
    html_res = client.get(f"/api/forgery-lab/reports/{exp_id}?format=html")
    assert html_res.status_code == 200
    assert "text/html" in html_res.headers["content-type"]
    assert "ImageGuard" in html_res.text


def test_forgery_lab_dimension_mismatch_validation(client, sample_image):
    """Submitting a ground-truth mask with mismatched dimensions returns HTTP 400."""
    mod_bytes = to_bytes(sample_image, "PNG")
    # Mask with 300x300 instead of 640x480
    small_gt = np.zeros((300, 300), dtype=np.uint8)
    gt_bytes = to_bytes(small_gt, "PNG")

    r = client.post(
        "/api/forgery-lab/analyze",
        files={
            "file": ("mod.png", mod_bytes, "image/png"),
            "ground_truth_file": ("gt.png", gt_bytes, "image/png"),
        },
    )
    assert r.status_code == 400
    assert "Ground-truth mask dimensions" in r.text


def test_forgery_lab_clean_image_baseline_honesty(client, sample_image):
    """Clean unedited image must not be labelled as modified even if heuristic detectors trigger candidate regions."""
    file_bytes = to_bytes(sample_image, "PNG")
    r = client.post(
        "/api/forgery-lab/analyze",
        files={
            "file": ("clean.png", file_bytes, "image/png"),
            "original_file": ("orig.png", file_bytes, "image/png"),
        },
        data={"methods": "copy_move,splicing,watermark_verify"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["is_baseline_only"] is True
    assert "No modifications detected" in j["answers"]["question_a"]


def test_forgery_lab_watermark_failure_distinct_from_forgery(client, sample_image):
    """Failing invisible watermark verification on an unmarked image does not claim proof of forgery."""
    file_bytes = to_bytes(sample_image, "PNG")
    r = client.post(
        "/api/forgery-lab/analyze",
        files={"file": ("unmarked.png", file_bytes, "image/png")},
        data={"methods": "watermark_verify"},
    )
    assert r.status_code == 200
    j = r.json()
    wm = j["watermark_verification"]
    assert wm is not None
    assert wm["status"] in ("not_detected", "inconclusive", "failed", "unavailable")
    assert wm["status"] != "verified"
    # Verify disclaimer reinforces that watermark failure does not prove forgery
    assert "not proof of authenticity or tampering" in j["disclaimer"].lower() or "indicator" in j["disclaimer"].lower()


def test_forgery_lab_non_square_landscape_1870x950(client):
    """Regression test: User-reported 1870 x 950 px image with matching ground-truth mask."""
    # Create 1870 x 950 image (width 1870, height 950, numpy shape is (950, 1870, 3))
    w, h = 1870, 950
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    # Add a painted modification
    mod_img = img.copy()
    cv2.rectangle(mod_img, (200, 200), (400, 350), (255, 0, 0), -1)

    gt_mask = np.zeros((h, w), dtype=np.uint8)
    gt_mask[200:350, 200:400] = 255

    mod_bytes = to_bytes(mod_img, "PNG")
    gt_bytes = to_bytes(gt_mask, "PNG")

    r = client.post(
        "/api/forgery-lab/analyze",
        files={
            "file": ("modified_1870x950.png", mod_bytes, "image/png"),
            "ground_truth_file": ("gt_1870x950.png", gt_bytes, "image/png"),
        },
        data={"methods": "copy_move,splicing"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["image"]["width"] == 1870
    assert j["image"]["height"] == 950
    assert j["ground_truth"]["has_mask"] is True
    assert j["ground_truth"]["regions"][0]["pixel_count"] == 200 * 150


def test_forgery_lab_transposed_mask_orientation(client):
    """Transposed ground-truth mask (e.g. height and width swapped) is auto-aligned."""
    w, h = 1870, 950
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    mod_img = img.copy()
    cv2.rectangle(mod_img, (100, 100), (300, 200), (0, 255, 0), -1)

    # Transposed mask: shape (1870, 950) instead of (950, 1870)
    transposed_gt = np.zeros((w, h), dtype=np.uint8)
    transposed_gt[100:300, 100:200] = 255

    mod_bytes = to_bytes(mod_img, "PNG")
    gt_bytes = to_bytes(transposed_gt, "PNG")

    r = client.post(
        "/api/forgery-lab/analyze",
        files={
            "file": ("modified.png", mod_bytes, "image/png"),
            "ground_truth_file": ("transposed_gt.png", gt_bytes, "image/png"),
        },
        data={"methods": "splicing"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["image"]["width"] == 1870
    assert j["image"]["height"] == 950
    assert j["ground_truth"]["has_mask"] is True


def test_forgery_lab_aspect_ratio_scaled_mask(client):
    """Ground-truth mask with same aspect ratio but different scale is resized using nearest neighbor."""
    w, h = 1870, 950
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    # Mask scaled to half resolution: 935 x 475
    scaled_gt = np.zeros((475, 935), dtype=np.uint8)
    scaled_gt[50:100, 100:200] = 255

    mod_bytes = to_bytes(img, "PNG")
    gt_bytes = to_bytes(scaled_gt, "PNG")

    r = client.post(
        "/api/forgery-lab/analyze",
        files={
            "file": ("mod.png", mod_bytes, "image/png"),
            "ground_truth_file": ("scaled_gt.png", gt_bytes, "image/png"),
        },
        data={"methods": "splicing"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["image"]["width"] == 1870
    assert j["image"]["height"] == 950
    assert j["ground_truth"]["has_mask"] is True


def test_forgery_lab_portrait_image_dimensions(client):
    """Portrait image (height > width) preserves (width, height) ordering throughout."""
    w, h = 600, 800
    img = np.full((h, w, 3), 100, dtype=np.uint8)
    gt_mask = np.zeros((h, w), dtype=np.uint8)
    gt_mask[100:200, 100:200] = 255

    r = client.post(
        "/api/forgery-lab/analyze",
        files={
            "file": ("portrait.png", to_bytes(img, "PNG"), "image/png"),
            "ground_truth_file": ("portrait_gt.png", to_bytes(gt_mask, "PNG"), "image/png"),
        },
        data={"methods": "splicing"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["image"]["width"] == 600
    assert j["image"]["height"] == 800
