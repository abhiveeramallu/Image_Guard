import json

import cv2
import numpy as np
import pytest

from app.core.config import Settings
from app.services import localization_service as loc
from app.services.splicing_service import detect_splicing
from tests import onnx_fixtures as ox
from tests.synth import iou
from tests.synth_splice import jpeg_roundtrip, photo_like, splice


# ---- splicing heuristic (EXPERIMENTAL: these assert behaviour on synthetic data, not real-world accuracy) ----
def test_splice_with_different_noise_is_localized():
    ious = []
    for seed in range(300, 304):
        f, gt = splice(photo_like(seed=seed), donor_seed=seed + 7)
        out = detect_splicing(f, is_jpeg=False)
        assert out.status == "candidate_regions_found"
        assert out.score.shape == gt.shape and out.mask.shape == gt.shape
        ious.append(iou(out.mask, gt))
    assert np.mean(ious) > 0.4


def test_unspliced_png_has_no_candidates():
    for seed in range(300, 305):
        out = detect_splicing(photo_like(seed=seed), is_jpeg=False)
        assert out.status == "no_candidate_regions_found" and out.mask.max() == 0
        assert any("not a JPEG" in w for w in out.warnings)


def test_flat_and_tiny_images_are_inconclusive():
    assert detect_splicing(np.full((300, 300, 3), 100, np.uint8), False).status == "inconclusive"
    assert detect_splicing(photo_like(100, 100), False).status == "inconclusive"


def test_threshold_changes_mask():
    f, _ = splice(photo_like(seed=301), donor_seed=9)
    from app.services.splicing_service import SplicingParams
    lo = detect_splicing(f, False, SplicingParams(threshold=0.2)).mask.sum()
    hi = detect_splicing(f, False, SplicingParams(threshold=0.95)).mask.sum()
    assert lo >= hi


def test_jpeg_input_uses_ela_component():
    f, _ = splice(photo_like(seed=302), donor_seed=11)
    out = detect_splicing(jpeg_roundtrip(f, 90), is_jpeg=True)
    assert "error_level_analysis" in out.metrics["components"]


# ---- model localization (PIPELINE tests with a generated, untrained ONNX graph) ----
def settings_for(path, **kw):
    return Settings(localization_model_path=str(path) if path else None, model_device="cpu", **kw)


def fresh():
    return loc.ModelManager()


def test_unconfigured_model_is_unavailable_and_never_mocked():
    mgr = fresh()
    st = mgr.status(settings_for(None))
    assert st["available"] is False and "IMAGEGUARD_LOCALIZATION_MODEL_PATH" in st["reason"]
    with pytest.raises(loc.ModelUnavailable):
        loc.localize(photo_like(), settings_for(None), mgr=mgr)


def test_missing_file_and_missing_card(tmp_path):
    mgr = fresh()
    assert "does not exist" in mgr.status(settings_for(tmp_path / "nope.onnx"))["reason"]
    m = tmp_path / "m.onnx"; ox.edge_model(m)
    assert "model card" in mgr.status(settings_for(m))["reason"]


def test_invalid_card_rejected(tmp_path):
    m = tmp_path / "m.onnx"; ox.edge_model(m)
    (tmp_path / "m.onnx.json").write_text(json.dumps({"id": "x"}))
    assert "missing required field" in fresh().status(settings_for(m))["reason"]
    ox.write_card(m, "logits")
    assert "semantics" in fresh().status(settings_for(m))["reason"]
    (tmp_path / "m.onnx.json").write_text("{not json")
    assert "not valid JSON" in fresh().status(settings_for(m))["reason"]


def test_corrupt_onnx_file_fails_to_load(tmp_path):
    m = tmp_path / "bad.onnx"; m.write_bytes(b"not an onnx file")
    ox.write_card(m, "probability")
    st = fresh().status(settings_for(m))
    assert st["available"] is False and "could not be loaded" in st["reason"]


def test_cuda_requested_but_unavailable_is_explicit(tmp_path):
    import onnxruntime as ort
    if "CUDAExecutionProvider" in ort.get_available_providers():
        pytest.skip("CUDA present")
    m = tmp_path / "m.onnx"; ox.edge_model(m, "probability"); ox.write_card(m, "probability")
    st = fresh().status(Settings(localization_model_path=str(m), model_device="cuda"))
    assert st["available"] is False and "CUDA" in st["reason"]


@pytest.mark.parametrize("sem,builder", [("probability", lambda p: ox.edge_model(p, "probability")),
                                         ("sigmoid_logit", lambda p: ox.edge_model(p, "logit")),
                                         ("softmax_logits", ox.softmax_model)])
def test_real_onnx_inference_output_shapes_and_range(tmp_path, sem, builder):
    m = tmp_path / "m.onnx"; builder(m); ox.write_card(m, sem)
    img = photo_like(333, 211, seed=1)  # odd size: preprocessing pads to multiple_of
    out = loc.localize(img, settings_for(m), threshold=0.5, mgr=fresh())
    assert out.score.shape == (211, 333) and out.mask.shape == (211, 333)
    assert out.score.dtype == np.float32 and 0.0 <= out.score.min() and out.score.max() <= 1.0
    assert out.metrics["model_input_shape"][2] % 8 == 0 and out.metrics["model_input_shape"][3] % 8 == 0
    assert out.metrics["model"]["output_semantics"] == sem
    assert out.status in ("candidate_regions_found", "no_candidate_regions_found")


def test_softmax_semantics_matches_hand_computation(tmp_path):
    m = tmp_path / "m.onnx"; ox.softmax_model(m); ox.write_card(m, "softmax_logits")
    img = np.zeros((64, 64, 3), np.uint8); img[:, 32:, 0] = 255  # red=0 -> logits (0,0) -> p=0.5 ; red=1 -> logits (-4,4) -> p=sigmoid(8)
    out = loc.localize(img, settings_for(m), threshold=0.6, mgr=fresh())
    assert np.allclose(out.score[:, :20], 0.5, atol=1e-4) and out.score[:, 44:].min() > 0.99
    assert np.allclose(out.score[:, 44:], 1 / (1 + np.exp(-8.0)), atol=1e-3)
    assert out.mask[:, 44:].min() == 255 and out.mask[:, 1:20].max() == 0  # p=0.5 is below threshold 0.6


def test_normalisation_card_values_are_applied(tmp_path):
    m = tmp_path / "m.onnx"; ox.softmax_model(m)
    ox.write_card(m, "softmax_logits", input={"size": 64, "scale": 255.0, "mean": [0.5, 0, 0], "std": [0.5, 1, 1]})
    img = np.zeros((64, 64, 3), np.uint8)  # normalised red = -1 -> logits (4, -4) -> p(fg)~0
    assert loc.localize(img, settings_for(m), mgr=fresh()).score.max() < 0.01
    img[..., 0] = 255                       # normalised red = +1
    assert loc.localize(img, settings_for(m), mgr=fresh()).score.min() > 0.99


def test_fixed_input_size_resizes_back_to_original(tmp_path):
    m = tmp_path / "m.onnx"; ox.edge_model(m, "probability"); ox.write_card(m, "probability", input={"size": [48, 64], "scale": 255.0})
    out = loc.localize(photo_like(400, 300), settings_for(m), mgr=fresh())
    assert out.metrics["model_input_shape"] == [1, 3, 48, 64] and out.score.shape == (300, 400)


def test_model_loaded_once_and_reloaded_on_change(tmp_path):
    m = tmp_path / "m.onnx"; ox.edge_model(m, "probability"); ox.write_card(m, "probability")
    mgr = fresh(); s = settings_for(m)
    first = mgr.get(s)
    assert mgr.get(s) is first


def test_timeout_reported(tmp_path):
    m = tmp_path / "m.onnx"; ox.edge_model(m, "probability"); ox.write_card(m, "probability")
    with pytest.raises(TimeoutError):
        loc.localize(photo_like(), settings_for(m, inference_timeout_seconds=1e-6), mgr=fresh())
