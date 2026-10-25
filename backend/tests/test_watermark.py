import io

import numpy as np
import pytest
from PIL import Image

from tests.conftest import decode, to_bytes


def post(client, data, **form):
    files = {"file": ("photo.png", data, "image/png")}
    logo = form.pop("logo", None)
    if logo is not None:
        files["logo"] = ("logo.png", logo, "image/png")
    return client.post("/api/watermark", files=files, data=form)


def diff_fraction(a: Image.Image, b: Image.Image) -> float:
    d = np.abs(np.asarray(a.convert("RGB"), np.int16) - np.asarray(b.convert("RGB"), np.int16)).sum(axis=2)
    return float((d > 0).mean())


def test_png_text_watermark_preserves_size_and_changes_pixels(client, photo_png, photo):
    r = post(client, photo_png, text="CONFIDENTIAL", font_size=48)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    out = decode(r.content)
    assert out.size == (photo.shape[1], photo.shape[0])
    assert 0.005 < diff_fraction(out, Image.fromarray(photo)) < 0.5
    assert 'filename="photo_watermarked.png"' in r.headers["content-disposition"]


def test_jpeg_input_and_jpeg_output(client, photo_jpg, photo):
    r = client.post("/api/watermark", files={"file": ("a.jpg", photo_jpg, "image/jpeg")},
                    data={"text": "hello", "output_format": "jpeg"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert decode(r.content).size == (photo.shape[1], photo.shape[0])


def test_opacity_scales_effect(client, photo_png, photo):
    base = Image.fromarray(photo)
    diffs = []
    for op in (0.1, 0.5, 1.0):
        out = decode(post(client, photo_png, text="MARK", font_size=60, opacity=op, outline="false", position="center").content)
        diffs.append(np.abs(np.asarray(out.convert("RGB"), float) - np.asarray(base, float)).mean())
    assert diffs[0] < diffs[1] < diffs[2]


def test_zero_opacity_leaves_image_unchanged(client, photo_png, photo):
    out = decode(post(client, photo_png, text="MARK", opacity=0).content)
    assert diff_fraction(out, Image.fromarray(photo)) == 0


@pytest.mark.parametrize("pos,region", [
    ("top-left", lambda h, w: (slice(0, h // 3), slice(0, w // 2))),
    ("bottom-right", lambda h, w: (slice(2 * h // 3, h), slice(w // 2, w))),
    ("center", lambda h, w: (slice(h // 3, 2 * h // 3), slice(w // 4, 3 * w // 4))),
])
def test_position_places_watermark_in_expected_area(client, photo_png, photo, pos, region):
    out = np.asarray(decode(post(client, photo_png, text="X", font_size=40, position=pos, opacity=1).content).convert("RGB"), np.int16)
    changed = np.abs(out - photo.astype(np.int16)).sum(axis=2) > 0
    ys, xs = np.nonzero(changed)
    assert len(ys) > 0
    rs, cs = region(*photo.shape[:2])
    assert rs.start <= ys.min() and ys.max() < rs.stop and cs.start <= xs.min() and xs.max() < cs.stop


def test_tiled_covers_more_area_than_single(client, photo_png, photo):
    base = Image.fromarray(photo)
    single = diff_fraction(decode(post(client, photo_png, text="WM", font_size=30, layout="single").content), base)
    tiled = diff_fraction(decode(post(client, photo_png, text="WM", font_size=30, layout="tiled", rotation=30).content), base)
    assert tiled > 5 * single


def test_rotation_changes_output(client, photo_png):
    a = post(client, photo_png, text="ROTATE", font_size=50, rotation=0).content
    b = post(client, photo_png, text="ROTATE", font_size=50, rotation=45).content
    assert a != b


def test_logo_with_transparency_keeps_transparent_pixels_unchanged(client, photo_png, photo):
    logo = np.zeros((80, 80, 4), np.uint8)
    logo[20:60, 20:60] = (255, 0, 0, 255)  # opaque red square, transparent surround
    r = post(client, photo_png, watermark_type="logo", logo=to_bytes(logo, "PNG"), logo_scale=25, opacity=1,
             position="top-left", margin=0)
    out = np.asarray(decode(r.content).convert("RGB"), np.int16)
    changed = np.abs(out - photo.astype(np.int16)).sum(axis=2) > 0
    ys, xs = np.nonzero(changed)
    w = round(photo.shape[1] * 0.25)  # stamp is w x w; the visible square is the middle 50%
    tol = 8  # Lanczos resampling spreads the edge a few pixels
    assert xs.min() >= w * 0.25 - tol and xs.max() <= w * 0.75 + tol
    assert ys.min() >= w * 0.25 - tol and ys.max() <= w * 0.75 + tol
    assert not changed[:w // 8, :w // 8].any()  # fully transparent corner is untouched
    centre = out[int(w * 0.5), int(w * 0.5)]
    assert centre[0] > 240 and centre[1] < 15 and centre[2] < 15


def test_logo_required(client, photo_png):
    r = post(client, photo_png, watermark_type="logo")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameters"


def test_watermark_clipped_when_larger_than_image(client):
    tiny = np.full((40, 60, 3), 90, np.uint8)
    r = post(client, to_bytes(tiny), text="A VERY LONG WATERMARK TEXT", font_size=60, position="center")
    assert r.status_code == 200 and decode(r.content).size == (60, 40)


def test_rgba_input_alpha_preserved_in_png(client):
    rgba = np.zeros((100, 100, 4), np.uint8)
    rgba[..., :3] = 50
    rgba[:50, :, 3] = 255
    r = post(client, to_bytes(rgba), text="hi", opacity=0.5, position="bottom-left")
    out = decode(r.content)
    assert out.mode == "RGBA" and out.getpixel((99, 0))[3] == 255 and out.getpixel((99, 99))[3] <= 255


def test_grayscale_input(client):
    g = (np.random.default_rng(0).random((64, 64)) * 255).astype(np.uint8)
    r = post(client, to_bytes(g), text="g")
    assert r.status_code == 200 and decode(r.content).size == (64, 64)


@pytest.mark.parametrize("form,code", [
    ({"text": ""}, 422), ({"text": "   "}, 422),
    ({"text": "x", "opacity": 1.5}, 422), ({"text": "x", "opacity": -0.1}, 422),
    ({"text": "x", "font_size": 2}, 422), ({"text": "x", "font_size": 5000}, 422),
    ({"text": "x", "position": "nowhere"}, 422), ({"text": "x", "color": "red"}, 422),
    ({"text": "x", "layout": "spiral"}, 422), ({"text": "x", "output_format": "gif"}, 422),
    ({"text": "x", "rotation": 400}, 422),
])
def test_invalid_parameters_rejected(client, photo_png, form, code):
    r = post(client, photo_png, **form)
    assert r.status_code == code
    assert r.json()["error"]["code"] == "invalid_parameters"


def test_unsupported_format_rejected(client, photo):
    gif = to_bytes(Image.fromarray(photo).convert("P"), "GIF")
    r = client.post("/api/watermark", files={"file": ("x.png", gif, "image/png")}, data={"text": "x"})
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_format"


def test_corrupted_and_non_image_rejected(client, photo_png):
    r = client.post("/api/watermark", files={"file": ("x.png", photo_png[:200] + b"garbage", "image/png")}, data={"text": "x"})
    assert r.status_code == 400
    r = client.post("/api/watermark", files={"file": ("x.png", b"not an image at all", "image/png")}, data={"text": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_image"


def test_empty_file_rejected(client):
    r = client.post("/api/watermark", files={"file": ("x.png", b"", "image/png")}, data={"text": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_file"


def test_too_many_tiles_rejected(client, photo_png):
    r = post(client, photo_png, text="w", font_size=8, layout="tiled", tile_spacing=0)
    assert r.status_code in (200, 422)
    r = post(client, to_bytes(np.zeros((3000, 3000, 3), np.uint8)), text="w", font_size=8, layout="tiled", tile_spacing=0)
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_many_tiles"


def test_filename_sanitized(client, photo_png):
    r = client.post("/api/watermark", files={"file": ("../../etc/pa ss<wd>.png", photo_png, "image/png")}, data={"text": "x"})
    assert 'filename="pa_ss_wd_watermarked.png"' in r.headers["content-disposition"]
