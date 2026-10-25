import io
import json

import numpy as np
import pytest
from PIL import Image

from app.api import routes_capabilities, routes_invisible
from app.core.config import get_settings
from app.services import localization_service as loc
from tests import onnx_fixtures as ox
from tests import synth
from tests.conftest import decode, to_bytes
from tests.synth_splice import jpeg_roundtrip, photo_like, splice


@pytest.fixture
def wm_key(monkeypatch):
    from pydantic import SecretStr
    monkeypatch.setattr(get_settings(), "watermark_key", SecretStr("api-test-key"))


@pytest.fixture
def onnx_model(tmp_path, monkeypatch):
    m = tmp_path / "m.onnx"; ox.edge_model(m, "probability"); ox.write_card(m, "probability")
    s = get_settings()
    monkeypatch.setattr(s, "localization_model_path", str(m))
    monkeypatch.setattr(s, "model_device", "cpu")
    return m


def analyze(client, arr, methods, name="x.png", fmt="PNG", **form):
    return client.post("/api/detect/analyze", files={"file": (name, to_bytes(arr, fmt), "image/png")},
                       data={"methods": methods, **form})


# ---- capabilities -------------------------------------------------------------------------
def test_capabilities_report_unavailable_without_config(client):
    j = client.get("/api/capabilities").json()
    assert j["methods"]["copy_move"]["available"] and j["methods"]["splicing"]["experimental"]
    assert j["methods"]["localization"]["available"] is False and j["methods"]["localization"]["reason"]
    assert j["invisible_watermark"]["available"] is False and "WATERMARK_KEY" in j["invisible_watermark"]["reason"]
    assert "secret" not in json.dumps(j).lower().replace("secretstr", "")


def test_capabilities_with_model_and_key(client, onnx_model, wm_key):
    j = client.get("/api/capabilities").json()
    assert j["methods"]["localization"]["available"] and j["methods"]["localization"]["model"]["id"] == "test/synthetic-pipeline-model"
    assert j["invisible_watermark"]["available"]


# ---- analyze --------------------------------------------------------------------------------
def test_legacy_copy_move_endpoint_unchanged(client):
    forged, *_ = synth.copy_move(synth.textured(seed=0))
    j = client.post("/api/detect/copy-move", files={"file": ("f.png", to_bytes(forged), "image/png")}).json()
    assert j["status"] == "candidate_regions_found" and "annotated" in j["artifacts"]


def test_analyze_copy_move_matches_legacy_semantics(client):
    forged, gt, *_ = synth.copy_move(synth.textured(seed=0))
    j = analyze(client, forged, "copy_move").json()
    r = j["results"][0]
    assert r["method"] == "copy_move" and r["category"] == "copy_move" and r["evidence_type"] == "feature_match_regions"
    assert r["status"] == "candidate_regions_found" and r["region_count"] == 1 and r["metrics"]["keypoints"] > 0
    mask = np.asarray(decode(client.get(r["artifacts"]["mask"]).content).convert("L"))
    assert synth.iou(mask, gt) > 0.35


def test_splicing_experimental_result_and_artifacts(client):
    f, gt = splice(photo_like(seed=310), donor_seed=17)
    j = analyze(client, f, "splicing").json()
    r = j["results"][0]
    assert r["experimental"] is True and r["evidence_type"] == "heuristic_forensic_map" and r["model"] is None
    assert r["status"] == "candidate_regions_found" and "probab" not in r["threshold_semantics"].replace("not a probability", "")
    for k in ("heatmap", "mask", "overlay", "score"):
        assert decode(client.get(r["artifacts"][k]).content).size == (640, 480)
    mask = np.asarray(decode(client.get(r["artifacts"]["mask"]).content).convert("L"))
    assert synth.iou(mask, gt) > 0.3


def test_localization_unavailable_is_explicit(client):
    j = analyze(client, photo_like(seed=1), "localization").json()
    r = j["results"][0]
    assert r["status"] == "unavailable" and r["artifacts"] == {} and "IMAGEGUARD_LOCALIZATION_MODEL_PATH" in r["status_reason"]


def test_all_supported_runs_each_method_independently(client):
    j = analyze(client, photo_like(seed=2), "all_supported").json()
    by = {r["method"]: r for r in j["results"]}
    assert set(by) == {"copy_move", "splicing", "localization"} and by["localization"]["status"] == "unavailable"
    assert by["copy_move"]["status"] != "unavailable" and by["splicing"]["status"] != "unavailable"
    rep = client.get(j["report_json"]).json()
    assert rep["analysis_id"] == j["analysis_id"] and len(rep["results"]) == 3


def test_localization_with_model_and_threshold_layer(client, onnx_model):
    j = analyze(client, photo_like(seed=3), "localization", localization_threshold="0.7").json()
    r = j["results"][0]
    assert r["status"] in ("candidate_regions_found", "no_candidate_regions_found") and r["evidence_type"] == "model_probability_map"
    assert r["model"]["id"] == "test/synthetic-pipeline-model" and r["threshold"] == 0.7
    assert "inference_ms" in r["metrics"]
    aid = j["analysis_id"]
    lo = client.get(f"/api/results/{aid}/localization/layer", params={"threshold": 0.2})
    hi = client.get(f"/api/results/{aid}/localization/layer", params={"threshold": 0.95})
    assert lo.status_code == 200 and decode(lo.content).mode == "RGBA" and decode(lo.content).size == (640, 480)
    a_lo = np.asarray(decode(lo.content))[..., 3].astype(bool).sum()
    a_hi = np.asarray(decode(hi.content))[..., 3].astype(bool).sum()
    assert a_lo >= a_hi and "x-region-count" in lo.headers


def test_layer_endpoint_validation(client):
    assert client.get("/api/results/AAAAAAAAAAAAAAAAAAAAAA/splicing/layer").status_code == 404
    assert client.get("/api/results/AAAAAAAAAAAAAAAAAAAAAA/copy_move/layer").status_code == 404
    j = analyze(client, photo_like(seed=4), "splicing").json()
    assert client.get(f"/api/results/{j['analysis_id']}/splicing/layer", params={"threshold": 5}).status_code == 422


def test_invalid_methods_and_files(client):
    assert analyze(client, photo_like(seed=1), "magic").status_code == 422
    r = client.post("/api/detect/analyze", files={"file": ("x.png", b"junk", "image/png")}, data={"methods": "all_supported"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_image"


def test_analysis_artifacts_expire_and_are_allowlisted(client, monkeypatch):
    import time
    j = analyze(client, photo_like(seed=5), "splicing").json()
    aid = j["analysis_id"]
    assert client.get(f"/api/results/{aid}/splicing.mask").status_code == 200
    assert client.get(f"/api/results/{aid}/splicing.evil").status_code == 404
    assert client.get(f"/api/results/{aid}/localization.mask").status_code == 404  # never produced
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 10_000)
    assert client.get(f"/api/results/{aid}/splicing.mask").status_code == 404


# ---- invisible watermark API ---------------------------------------------------------------------
def embed(client, arr, owner="Acme", **form):
    return client.post("/api/watermark/invisible/embed", files={"file": ("p.png", to_bytes(arr), "image/png")},
                       data={"owner": owner, **form})


def verify(client, content, name="v.png"):
    return client.post("/api/watermark/invisible/verify", files={"file": (name, content, "image/png")})


def test_invisible_unavailable_without_key(client):
    r = embed(client, photo_like(seed=1))
    assert r.status_code == 503 and r.json()["error"]["code"] == "watermark_unavailable"
    assert verify(client, to_bytes(photo_like(seed=1))).status_code == 503


def test_invisible_embed_download_and_verify_roundtrip(client, wm_key):
    src = photo_like(seed=6)
    r = embed(client, src, owner="Owner-42")
    assert r.status_code == 200
    j = r.json()
    assert j["metrics"]["psnr_db"] > 40 and j["algorithm"]["name"] == "dct-qim-hmac" and "api-test-key" not in json.dumps(j)
    dl = client.get(j["artifact"])
    assert dl.status_code == 200 and dl.headers["content-type"] == "image/png" and "attachment" in dl.headers["content-disposition"]
    assert decode(dl.content).size == (640, 480)
    v = verify(client, dl.content).json()
    assert v["status"] == "verified" and v["owner"] == "Owner-42" and v["integrity_verified"] is True
    assert "api-test-key" not in json.dumps(v)
    # unmarked original is not verified
    assert verify(client, to_bytes(src)).json()["status"] == "not_detected"


def test_invisible_verify_after_jpeg_download_and_recompression(client, wm_key):
    j = embed(client, photo_like(seed=7), owner="JPG", output_format="jpeg").json()
    dl = client.get(j["artifact"])
    assert dl.headers["content-type"] == "image/jpeg" and any("lossy" in w for w in j["warnings"])
    assert verify(client, dl.content, "v.jpg").json()["status"] == "verified"
    buf = io.BytesIO(); Image.open(io.BytesIO(dl.content)).save(buf, "JPEG", quality=65)
    assert verify(client, buf.getvalue(), "v.jpg").json()["owner"] == "JPG"


def test_invisible_wrong_key_is_not_verified(client, wm_key, monkeypatch):
    from pydantic import SecretStr
    j = embed(client, photo_like(seed=8)).json()
    body = client.get(j["artifact"]).content
    monkeypatch.setattr(get_settings(), "watermark_key", SecretStr("rotated-key"))
    assert verify(client, body).json()["status"] != "verified"


def test_invisible_validation(client, wm_key):
    assert embed(client, photo_like(seed=1), owner="x" * 13).status_code == 422
    assert embed(client, photo_like(seed=1), owner="café").status_code == 422
    assert embed(client, photo_like(seed=1), strength="max").status_code == 422
    assert embed(client, photo_like(seed=1), output_format="gif").status_code == 422
    assert embed(client, photo_like(100, 100)).status_code == 422
    r = client.post("/api/watermark/invisible/verify", files={"file": ("x.png", b"junk", "image/png")})
    assert r.status_code == 400


def test_rate_limiter_returns_429_with_retry_after():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.ratelimit import RateLimitMiddleware
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, per_minute=3)

    @app.post("/api/x")
    def x():
        return {"ok": True}

    c = TestClient(app)
    codes = [c.post("/api/x").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert c.post("/api/x").headers["retry-after"] == "60"


def test_cors_exposes_headers_the_frontend_reads(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    exposed = r.headers["access-control-expose-headers"]
    assert "X-Region-Count" in exposed and "Content-Disposition" in exposed
