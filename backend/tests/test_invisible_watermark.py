import cv2
import numpy as np
import pytest

from app.services import invisible_watermark_service as iw
from tests.synth_splice import jpeg_roundtrip, photo_like

KEY = b"unit-test-key-not-a-secret"


@pytest.fixture(scope="module")
def marked():
    img = photo_like(640, 480, seed=5)
    return img, iw.embed(img, "Acme-2026", KEY)


def test_embed_is_invisible_and_keeps_shape(marked):
    img, r = marked
    assert r.image.shape == img.shape and r.image.dtype == np.uint8
    assert r.psnr_db > 40
    assert np.abs(r.image.astype(int) - img.astype(int)).max() < 40
    assert not np.array_equal(r.image, img)


def test_verify_recovers_exact_payload(marked):
    v = iw.verify(marked[1].image, KEY)
    assert v.status == "verified" and v.owner == "Acme-2026" and v.integrity_verified


def test_unmarked_image_not_verified(marked):
    assert iw.verify(marked[0], KEY).status == "not_detected"


def test_wrong_key_does_not_verify(marked):
    v = iw.verify(marked[1].image, b"a-different-key")
    assert v.status != "verified" and v.owner is None


def test_tampered_payload_fails_integrity(marked):
    img, _ = marked
    other = iw.embed(img, "Acme-2026", b"another-key").image
    assert iw.verify(other, KEY).status != "verified"


@pytest.mark.parametrize("q", [95, 85, 75, 60])
def test_survives_jpeg_recompression(marked, q):
    assert iw.verify(jpeg_roundtrip(marked[1].image, q), KEY).owner == "Acme-2026"


def test_survives_mild_noise(marked):
    rng = np.random.default_rng(0)
    noisy = np.clip(marked[1].image + rng.normal(0, 3, marked[1].image.shape), 0, 255).astype(np.uint8)
    assert iw.verify(noisy, KEY).status == "verified"


def test_survives_small_crop(marked):
    assert iw.verify(marked[1].image[13:-9, 7:-21], KEY).status == "verified"


def test_resize_is_not_supported_and_reported_as_not_verified(marked):
    small = cv2.resize(marked[1].image, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)
    assert iw.verify(small, KEY).status != "verified"  # documented limitation


@pytest.mark.parametrize("owner", ["", "x" * 13, "café"])
def test_invalid_owner_rejected(owner):
    with pytest.raises(iw.WatermarkError):
        iw.embed(photo_like(300, 300), owner, KEY)


def test_too_small_image_rejected():
    with pytest.raises(iw.WatermarkError):
        iw.embed(photo_like(100, 100), "a", KEY)


def test_strength_changes_distortion_and_all_levels_verify():
    img = photo_like(512, 384, seed=2)
    psnr = {}
    for s in iw.STRENGTHS:
        r = iw.embed(img, "id1", KEY, s)
        psnr[s] = r.psnr_db
        assert iw.verify(r.image, KEY).status == "verified"
    assert psnr["low"] > psnr["standard"] > psnr["high"]


def test_payload_roundtrip_and_mac():
    p = iw.build_payload("owner", KEY)
    assert iw.parse_payload(p, KEY) == (True, "owner", True)
    assert iw.parse_payload(p, b"x")[2] is False
    bad = bytearray(p); bad[16] ^= 1
    assert iw.parse_payload(bytes(bad), KEY)[2] is False


def test_invisible_watermark_8_transformations_robustness_matrix(marked):
    """Systematically evaluate survival and documented failure modes across all 8 Attack Lab transformations."""
    from app.services import attack_lab_service as lab

    img, r = marked
    marked_img = r.image

    # 1. Occlusion: Small patch (50x50 out of 640x480) leaves enough intact blocks -> verifies
    occ_small, _, _ = lab.occlude_watermark(marked_img, 50, 50, 50, 50, "#000000", 1.0)
    v_occ_small = iw.verify(occ_small, KEY)
    assert v_occ_small.status == "verified"
    assert v_occ_small.owner == "Acme-2026"

    # 2. Crop: Small crop (preserve watermark or edge_small) survives grid search
    cropped_small, _, _ = lab.crop_image(marked_img, preset="edge_small")
    v_crop = iw.verify(cropped_small, KEY)
    assert v_crop.status == "verified"

    # 3. Blur: Mild blur (sigma=1.0) survives, heavy blur (sigma=6.0) disrupts high/mid DCT coefficients
    blur_mild, _, _ = lab.blur_image(marked_img, radius=1.0)
    assert iw.verify(blur_mild, KEY).status == "verified"
    blur_heavy, _, _ = lab.blur_image(marked_img, radius=6.0)
    assert iw.verify(blur_heavy, KEY).status != "verified"

    # 4. JPEG recompression: High/moderate quality (95, 70) survives; low quality (25) fails
    jpeg_q95, _, _, _ = lab.jpeg_recompress(marked_img, quality=95)
    assert iw.verify(jpeg_q95, KEY).status == "verified"
    jpeg_q70, _, _, _ = lab.jpeg_recompress(marked_img, quality=70)
    assert iw.verify(jpeg_q70, KEY).status == "verified"
    jpeg_q25, _, _, _ = lab.jpeg_recompress(marked_img, quality=25)
    assert iw.verify(jpeg_q25, KEY).status != "verified"

    # 5. Resizing: Breaks 8x8 block grid synchronization -> documented limitation: does not verify
    resized, _, _ = lab.resize_image(marked_img, scale=0.75)
    assert iw.verify(resized, KEY).status != "verified"

    # 6. Rotation: Breaks block grid axis alignment -> documented limitation: does not verify
    rotated, _, _ = lab.rotate_image(marked_img, angle=15.0)
    assert iw.verify(rotated, KEY).status != "verified"

    # 7. Copy-Move: Localized modification leaves remaining blocks intact -> verifies
    tampered_cm, _, _ = lab.copy_move_tamper(marked_img, src_x=50, src_y=50, src_w=60, src_h=60, dst_x=300, dst_y=200)
    v_cm = iw.verify(tampered_cm, KEY)
    assert v_cm.status == "verified"
    assert v_cm.owner == "Acme-2026"

    # 8. Splicing: Localized donor insertion leaves remaining blocks intact -> verifies
    donor = photo_like(100, 100, seed=99)
    tampered_splice, _, _ = lab.splice_content(marked_img, donor, donor_x=0, donor_y=0, donor_w=60, donor_h=60, target_x=200, target_y=150, target_w=60, target_h=60)
    v_sp = iw.verify(tampered_splice, KEY)
    assert v_sp.status == "verified"
    assert v_sp.owner == "Acme-2026"
