import numpy as np
import pytest
from PIL import Image

from app.core.errors import ApiError
from app.services import attack_lab_service as lab
from tests import synth


@pytest.fixture
def base_rgb():
    return synth.textured(400, 300, seed=42)


def test_occlusion_valid(base_rgb):
    orig = base_rgb.copy()
    mod, mask, meta = lab.occlude_watermark(base_rgb, 50, 60, 80, 40, "#FF0000", 1.0)
    # Check original unmodified
    assert np.array_equal(base_rgb, orig)
    # Check patch applied
    assert (mod[60:100, 50:130, 0] == 255).all()
    assert (mod[60:100, 50:130, 1:] == 0).all()
    # Check ground truth mask
    assert mask.shape == (300, 400)
    assert (mask[60:100, 50:130] == 255).all()
    assert mask.sum() == 80 * 40 * 255
    assert meta["width"] == 80 and meta["height"] == 40


def test_occlusion_invalid_bounds(base_rgb):
    with pytest.raises(ApiError) as exc:
        lab.occlude_watermark(base_rgb, 450, 10, 50, 50)
    assert exc.value.status_code == 422

    with pytest.raises(ApiError):
        lab.occlude_watermark(base_rgb, 10, 10, 0, 50)


def test_cropping_presets(base_rgb):
    orig = base_rgb.copy()
    # Edge small: 95%
    c1, _, m1 = lab.crop_image(base_rgb, preset="edge_small")
    assert np.array_equal(base_rgb, orig)
    assert c1.shape == (int(round(300 * 0.95)), int(round(400 * 0.95)), 3)

    # Watermark corner: 85%
    c2, _, m2 = lab.crop_image(base_rgb, preset="watermark_corner")
    assert c2.shape == (int(round(300 * 0.85)), int(round(400 * 0.85)), 3)

    # Preserve watermark
    c3, _, m3 = lab.crop_image(base_rgb, preset="preserve_watermark")
    assert c3.shape[0] < 300 and c3.shape[1] < 400

    # Custom
    c4, _, m4 = lab.crop_image(base_rgb, x=20, y=30, width=150, height=100)
    assert c4.shape == (100, 150, 3)


def test_cropping_invalid_bounds(base_rgb):
    with pytest.raises(ApiError):
        lab.crop_image(base_rgb, x=350, y=10, width=100, height=50)

    with pytest.raises(ApiError):
        lab.crop_image(base_rgb, x=0, y=0, width=10, height=10)  # < 16px


def test_blur(base_rgb):
    orig = base_rgb.copy()
    mod, _, meta = lab.blur_image(base_rgb, radius=5.0)
    assert np.array_equal(base_rgb, orig)
    assert mod.shape == base_rgb.shape
    assert not np.array_equal(mod, base_rgb)
    assert meta["radius"] == 5.0

    with pytest.raises(ApiError):
        lab.blur_image(base_rgb, radius=0.1)
    with pytest.raises(ApiError):
        lab.blur_image(base_rgb, radius=100.0)


def test_jpeg_recompression(base_rgb):
    orig = base_rgb.copy()
    mod, _, meta, b = lab.jpeg_recompress(base_rgb, quality=50)
    assert np.array_equal(base_rgb, orig)
    assert mod.shape == base_rgb.shape
    assert meta["is_lossy_jpeg"] is True
    assert len(b) > 0

    with pytest.raises(ApiError):
        lab.jpeg_recompress(base_rgb, quality=0)
    with pytest.raises(ApiError):
        lab.jpeg_recompress(base_rgb, quality=101)


def test_resize(base_rgb):
    orig = base_rgb.copy()
    mod, _, meta = lab.resize_image(base_rgb, scale=0.5)
    assert np.array_equal(base_rgb, orig)
    assert mod.shape == (150, 200, 3)
    assert meta["output_size"] == [200, 150]

    with pytest.raises(ApiError):
        lab.resize_image(base_rgb, scale=0.01)
    with pytest.raises(ApiError):
        lab.resize_image(base_rgb, scale=10.0)


def test_rotate(base_rgb):
    orig = base_rgb.copy()
    mod, _, meta = lab.rotate_image(base_rgb, angle=15.0, expand=False)
    assert np.array_equal(base_rgb, orig)
    assert mod.shape == base_rgb.shape
    assert not np.array_equal(mod, base_rgb)

    with pytest.raises(ApiError):
        lab.rotate_image(base_rgb, angle=200.0)


def test_copy_move_tamper(base_rgb):
    orig = base_rgb.copy()
    mod, mask, meta = lab.copy_move_tamper(base_rgb, src_x=20, src_y=30, src_w=50, src_h=40, dst_x=120, dst_y=150)
    # Original untouched
    assert np.array_equal(base_rgb, orig)
    # Check pixels copied
    assert np.array_equal(mod[150:190, 120:170], orig[30:70, 20:70])
    # Check ground-truth mask
    assert mask.shape == (300, 400)
    assert (mask[150:190, 120:170] == 255).all()
    assert mask.sum() == 50 * 40 * 255
    # Metadata contains separate source and destination
    assert meta["source"] == {"x": 20, "y": 30, "width": 50, "height": 40}
    assert meta["destination"] == {"x": 120, "y": 150, "width": 50, "height": 40}


def test_copy_move_tamper_invalid(base_rgb):
    # Out of bounds source
    with pytest.raises(ApiError):
        lab.copy_move_tamper(base_rgb, src_x=380, src_y=0, src_w=50, src_h=50, dst_x=10, dst_y=10)
    # Out of bounds destination
    with pytest.raises(ApiError):
        lab.copy_move_tamper(base_rgb, src_x=10, src_y=10, src_w=50, src_h=50, dst_x=380, dst_y=10)
    # Identical src and dst
    with pytest.raises(ApiError):
        lab.copy_move_tamper(base_rgb, src_x=50, src_y=50, src_w=50, src_h=50, dst_x=50, dst_y=50)


def test_splicing_content(base_rgb):
    donor_rgb = synth.textured(200, 200, seed=99)
    orig_target = base_rgb.copy()
    orig_donor = donor_rgb.copy()

    mod, mask, meta = lab.splice_content(
        base_rgb, donor_rgb,
        donor_x=10, donor_y=10, donor_w=60, donor_h=50,
        target_x=100, target_y=120, target_w=60, target_h=50,
    )
    # Inputs preserved
    assert np.array_equal(base_rgb, orig_target)
    assert np.array_equal(donor_rgb, orig_donor)

    # Content pasted
    assert np.array_equal(mod[120:170, 100:160], orig_donor[10:60, 10:70])
    # Ground truth mask
    assert mask.shape == (300, 400)
    assert (mask[120:170, 100:160] == 255).all()
    assert mask.sum() == 60 * 50 * 255
    assert meta["target_region"] == {"x": 100, "y": 120, "width": 60, "height": 50}


def test_splicing_invalid_bounds(base_rgb):
    donor_rgb = synth.textured(100, 100, seed=1)
    with pytest.raises(ApiError):
        lab.splice_content(base_rgb, donor_rgb, 0, 0, 150, 50, 10, 10, 50, 50)
    with pytest.raises(ApiError):
        lab.splice_content(base_rgb, donor_rgb, 0, 0, 50, 50, 380, 10, 50, 50)


def test_evaluate_detection_metrics():
    gt = np.zeros((100, 100), dtype=np.uint8)
    gt[20:40, 20:40] = 255  # 400 px

    pred = np.zeros((100, 100), dtype=np.uint8)
    pred[20:40, 20:50] = 255  # 600 px (400 TP, 200 FP)

    ev = lab.evaluate_detection(gt, pred, "copy_move")
    assert ev is not None
    assert ev["tp"] == 400
    assert ev["fp"] == 200
    assert ev["fn"] == 0
    assert abs(ev["precision"] - (400 / 600)) < 1e-3
    assert ev["recall"] == 1.0
    assert "semantics_note" in ev


def test_copy_move_on_flat_image_inconclusive_in_detector():
    from app.services.copy_move_service import detect_copy_move
    flat = np.full((300, 400, 3), 150, dtype=np.uint8)
    tampered, mask, meta = lab.copy_move_tamper(flat, 20, 20, 50, 50, 150, 150)
    # The detector receives only the tampered image (no ground truth)
    res = detect_copy_move(tampered)
    # Since the image is completely flat/untextured, ORB cannot find sufficient keypoints
    assert res.status == "inconclusive"
    assert "insufficient texture" in res.status_reason.lower() or "too little texture" in res.status_reason.lower()
