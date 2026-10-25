import json
import time

import numpy as np
from PIL import Image

from app.api.deps import store
from tests import synth
from tests.conftest import decode, to_bytes


def detect(client, arr, name="forged.png", **form):
    return client.post("/api/detect/copy-move", files={"file": (name, to_bytes(arr), "image/png")}, data=form)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["version"]


def test_detect_endpoint_end_to_end_and_artifacts_download(client):
    forged, gt, *_ = synth.copy_move(synth.textured(seed=0))
    r = detect(client, forged)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "candidate_regions_found" and j["candidate_region_count"] == 1
    assert j["image"]["width"] == 800 and j["image"]["height"] == 600
    assert j["keypoints"] >= j["matches_before_filtering"] >= j["matches_after_descriptor_filtering"] >= j["matches_retained"] > 0
    assert j["processing_ms"] > 0 and j["method"]["name"] and j["limitations"]
    assert "confidence" not in json.dumps(j).lower() and "probab" not in json.dumps(j["status_reason"]).lower()

    mask = decode(client.get(j["artifacts"]["mask"]).content)
    assert mask.size == (800, 600) and synth.iou(np.asarray(mask.convert("L")), gt) > 0.35
    for key in ("annotated", "heatmap"):
        res = client.get(j["artifacts"][key])
        assert res.status_code == 200 and res.headers["content-type"] == "image/png"
        assert decode(res.content).size == (800, 600)
    rep = client.get(j["artifacts"]["report_json"])
    assert rep.status_code == 200 and rep.json()["analysis_id"] == j["analysis_id"]
    assert rep.json()["uploaded_filename"] == "forged" and "disclaimer" in rep.json()
    html = client.get(j["artifacts"]["report_html"])
    assert html.status_code == 200 and b"data:image/png;base64" in html.content
    assert "content-security-policy" in html.headers


def test_clean_image_reports_no_candidates_without_authenticity_claim(client):
    j = detect(client, synth.textured(seed=1)).json()
    assert j["status"] == "no_candidate_regions_found" and j["regions"] == []
    assert any("authentic" in l.lower() for l in j["limitations"])


def test_settings_are_applied(client):
    forged, *_ = synth.copy_move(synth.textured(seed=0))
    j = detect(client, forged, min_matches=100).json()
    assert j["settings"]["min_matches"] == 100 and j["status"] == "no_candidate_regions_found"
    j = detect(client, synth.textured(1600, 1200, seed=0), max_dimension=512).json()
    assert j["image"]["analysis_width"] == 512


def test_invalid_detection_input(client):
    r = client.post("/api/detect/copy-move", files={"file": ("x.png", b"junk", "image/png")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_image"
    gif = to_bytes(Image.fromarray(synth.textured(100, 100)).convert("P"), "GIF")
    assert client.post("/api/detect/copy-move", files={"file": ("x.gif", gif, "image/gif")}).status_code == 415
    r = detect(client, synth.textured(seed=0), ratio=3)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameters"
    r = client.post("/api/detect/copy-move")
    assert r.status_code == 422


def test_oversized_dimensions_and_upload_rejected(client, monkeypatch):
    from app.api import routes_detect
    monkeypatch.setattr(routes_detect.settings, "max_image_pixels", 10_000)
    r = detect(client, synth.textured(200, 200, seed=0))
    assert r.status_code == 413 and r.json()["error"]["code"] == "image_too_large"
    monkeypatch.setattr(routes_detect.settings, "max_upload_bytes", 1000)
    r = detect(client, synth.textured(200, 200, seed=0))
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"


def test_too_small_image_rejected(client):
    assert detect(client, np.zeros((8, 8, 3), np.uint8)).status_code == 422


def test_artifact_access_is_allowlisted(client):
    assert client.get("/api/results/..%2F..%2Fetc/passwd").status_code == 404
    assert client.get("/api/results/AAAAAAAAAAAAAAAAAAAAAA/annotated").status_code == 404
    j = detect(client, synth.textured(seed=2)).json()
    aid = j["analysis_id"]
    assert client.get(f"/api/results/{aid}/secret").status_code == 404
    assert client.get(f"/api/results/{aid}/..%2Fmask").status_code == 404


def test_artifacts_expire(client, monkeypatch):
    j = detect(client, synth.textured(seed=2)).json()
    aid = j["analysis_id"]
    assert client.get(f"/api/results/{aid}/mask").status_code == 200
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 10_000)
    assert client.get(f"/api/results/{aid}/mask").status_code == 404


def test_exif_orientation_applied(client):
    img = Image.fromarray(synth.textured(300, 200, seed=0))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    import io
    buf = io.BytesIO(); img.save(buf, "JPEG", exif=exif)
    r = client.post("/api/watermark", files={"file": ("e.jpg", buf.getvalue(), "image/jpeg")}, data={"text": "x", "output_format": "jpeg"})
    assert decode(r.content).size == (200, 300)


def test_cors_allows_only_configured_origin(client):
    ok = client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
