import io
import json
import numpy as np
import pytest
from PIL import Image

from tests import synth
from tests.conftest import to_bytes, decode


@pytest.fixture
def test_image():
    return synth.textured(640, 480, seed=12)


def test_prepare_baseline_and_retrieve(client, test_image):
    file_bytes = to_bytes(test_image, "PNG")
    r = client.post(
        "/api/attack-lab/prepare",
        files={"file": ("test.png", file_bytes, "image/png")},
        data={"visible_watermark": "true", "watermark_text": "Lab Baseline"},
    )
    assert r.status_code == 200
    j = r.json()
    assert "experiment_id" in j
    exp_id = j["experiment_id"]
    assert j["baseline_image"]["has_visible_watermark"] is True
    assert j["baseline_image"]["visible_watermark_text"] == "Lab Baseline"

    # Artifacts accessible
    orig_res = client.get(f"/api/results/{exp_id}/original.png")
    assert orig_res.status_code == 200
    base_res = client.get(f"/api/results/{exp_id}/baseline.png")
    assert base_res.status_code == 200

    # Retrieve experiment status
    exp_res = client.get(f"/api/attack-lab/experiments/{exp_id}")
    assert exp_res.status_code == 200
    assert exp_res.json()["experiment_id"] == exp_id


def test_transform_copy_move_and_chaining(client, test_image):
    file_bytes = to_bytes(test_image, "PNG")
    r = client.post(
        "/api/attack-lab/prepare",
        files={"file": ("test.png", file_bytes, "image/png")},
    )
    exp_id = r.json()["experiment_id"]

    # Step 1: Copy-move
    cm_params = {"src_x": 40, "src_y": 50, "src_w": 80, "src_h": 60, "dst_x": 200, "dst_y": 250}
    r2 = client.post(
        "/api/attack-lab/transform",
        data={
            "experiment_id": exp_id,
            "transformation": "copy_move",
            "target": "baseline",
            "params": json.dumps(cm_params),
        },
    )
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["ground_truth"]["has_mask"] is True
    assert len(j2["history"]) == 1
    assert j2["history"][0]["transformation"] == "copy_move"

    # Step 2: Blur on top of current working copy
    r3 = client.post(
        "/api/attack-lab/transform",
        data={
            "experiment_id": exp_id,
            "transformation": "blur",
            "target": "current",
            "params": json.dumps({"radius": 2.0}),
        },
    )
    assert r3.status_code == 200
    j3 = r3.json()
    assert len(j3["history"]) == 2
    assert j3["history"][1]["transformation"] == "blur"

    # Reset to baseline
    r_reset = client.post("/api/attack-lab/reset", data={"experiment_id": exp_id})
    assert r_reset.status_code == 200
    assert len(r_reset.json()["history"]) == 0


def test_transform_splicing_with_donor(client, test_image):
    donor_image = synth.textured(300, 300, seed=55)
    file_bytes = to_bytes(test_image, "PNG")
    donor_bytes = to_bytes(donor_image, "PNG")

    r = client.post(
        "/api/attack-lab/prepare",
        files={"file": ("test.png", file_bytes, "image/png")},
    )
    exp_id = r.json()["experiment_id"]

    splice_params = {
        "donor_x": 10, "donor_y": 10, "donor_w": 50, "donor_h": 50,
        "target_x": 100, "target_y": 100, "target_w": 50, "target_h": 50,
    }
    r_splice = client.post(
        "/api/attack-lab/transform",
        data={
            "experiment_id": exp_id,
            "transformation": "splicing",
            "target": "baseline",
            "params": json.dumps(splice_params),
        },
        files={"donor_file": ("donor.png", donor_bytes, "image/png")},
    )
    assert r_splice.status_code == 200
    j = r_splice.json()
    assert j["ground_truth"]["has_mask"] is True
    gt_res = client.get(f"/api/results/{exp_id}/ground_truth.png")
    assert gt_res.status_code == 200


def test_analyze_and_reports(client, test_image):
    file_bytes = to_bytes(test_image, "PNG")
    r = client.post(
        "/api/attack-lab/prepare",
        files={"file": ("test.png", file_bytes, "image/png")},
    )
    exp_id = r.json()["experiment_id"]

    # Apply copy move
    cm_params = {"src_x": 30, "src_y": 30, "src_w": 70, "src_h": 70, "dst_x": 150, "dst_y": 150}
    client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "copy_move", "params": json.dumps(cm_params)},
    )

    # Analyze
    r_an = client.post(
        "/api/attack-lab/analyze",
        data={
            "experiment_id": exp_id,
            "methods": "copy_move,splicing,watermark_verify",
            "splicing_threshold": 0.5,
        },
    )
    assert r_an.status_code == 200
    jan = r_an.json()
    assert "answers" in jan
    assert "question_a" in jan["answers"]
    assert "question_b" in jan["answers"]
    assert "question_c" in jan["answers"]
    assert len(jan["detection_results"]) >= 2

    # Verify JSON report
    r_rep_json = client.get(f"/api/attack-lab/experiments/{exp_id}/report?format=json")
    assert r_rep_json.status_code == 200
    assert r_rep_json.headers["content-type"].startswith("application/json")
    rep_j = r_rep_json.json()
    assert rep_j["experiment_id"] == exp_id

    # Verify HTML report
    r_rep_html = client.get(f"/api/attack-lab/experiments/{exp_id}/report?format=html")
    assert r_rep_html.status_code == 200
    assert "text/html" in r_rep_html.headers["content-type"]
    assert f"attack-lab-report-{exp_id}.html" in r_rep_html.headers["content-disposition"]
    assert b"ImageGuard" in r_rep_html.content


def test_expired_or_invalid_experiment_returns_404(client):
    r = client.get("/api/attack-lab/experiments/nonexistent-experiment-id")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    r_rep = client.get("/api/attack-lab/experiments/nonexistent-experiment-id/report")
    assert r_rep.status_code == 404


def test_prepare_validation_errors(client):
    # Empty file
    r1 = client.post("/api/attack-lab/prepare", files={"file": ("empty.png", b"", "image/png")})
    assert r1.status_code == 400
    assert r1.json()["error"]["code"] == "empty_file"

    # Unsupported format (e.g. text/plain)
    r2 = client.post("/api/attack-lab/prepare", files={"file": ("test.txt", b"not an image", "text/plain")})
    assert r2.status_code in (400, 415)

    # Corrupted image bytes
    r3 = client.post("/api/attack-lab/prepare", files={"file": ("bad.png", b"\x89PNG\r\n\x1a\ncorrupted", "image/png")})
    assert r3.status_code == 400
    assert r3.json()["error"]["code"] in ("invalid_image", "unsupported_format")


def test_transform_validation_errors(client, test_image):
    file_bytes = to_bytes(test_image, "PNG")
    r = client.post("/api/attack-lab/prepare", files={"file": ("test.png", file_bytes, "image/png")})
    exp_id = r.json()["experiment_id"]

    # Invalid target
    r_bad_target = client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "blur", "target": "invalid_target"},
    )
    assert r_bad_target.status_code == 422
    assert r_bad_target.json()["error"]["code"] == "invalid_parameters"

    # Unsupported transformation
    r_bad_trans = client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "unsupported_xyz"},
    )
    assert r_bad_trans.status_code == 422

    # Splicing missing donor file
    r_no_donor = client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "splicing", "params": "{}"},
    )
    assert r_no_donor.status_code == 422

    # Invalid JSON params
    r_bad_json = client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "blur", "params": "not-json"},
    )
    assert r_bad_json.status_code == 422


def test_analyze_validation_errors(client, test_image):
    file_bytes = to_bytes(test_image, "PNG")
    r = client.post("/api/attack-lab/prepare", files={"file": ("test.png", file_bytes, "image/png")})
    exp_id = r.json()["experiment_id"]

    # Unknown method
    r_bad_method = client.post(
        "/api/attack-lab/analyze",
        data={"experiment_id": exp_id, "methods": "copy_move,nonexistent_method"},
    )
    assert r_bad_method.status_code == 422

    # Invalid report format
    r_bad_fmt = client.get(f"/api/attack-lab/experiments/{exp_id}/report?format=pdf")
    assert r_bad_fmt.status_code == 422


def test_ground_truth_geometric_tracking(client, test_image):
    file_bytes = to_bytes(test_image, "PNG")
    r = client.post("/api/attack-lab/prepare", files={"file": ("test.png", file_bytes, "image/png")})
    exp_id = r.json()["experiment_id"]

    # Step 1: Copy-move (at 100, 100, 80x80)
    cm_params = {"src_x": 20, "src_y": 20, "src_w": 80, "src_h": 80, "dst_x": 100, "dst_y": 100}
    r1 = client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "copy_move", "params": json.dumps(cm_params)},
    )
    assert r1.status_code == 200
    assert r1.json()["ground_truth"]["has_mask"] is True

    # Step 2: Resize by 0.5x on current working copy
    r2 = client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "resize", "target": "current", "params": json.dumps({"scale": 0.5})},
    )
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["image"]["width"] == 320
    assert j2["image"]["height"] == 240
    assert j2["ground_truth"]["has_mask"] is True

    # Verify mask downloaded matches resized dimensions 320x240 and scaled position
    gt_res = client.get(f"/api/results/{exp_id}/ground_truth.png")
    assert gt_res.status_code == 200
    mask_arr = np.asarray(Image.open(io.BytesIO(gt_res.content)))
    assert mask_arr.shape == (240, 320)
    # Scaled destination region should be active (around 50, 50, 40x40)
    assert (mask_arr[55:85, 55:85] == 255).any()


def test_detector_isolation_anti_leakage(client, test_image, monkeypatch):
    file_bytes = to_bytes(test_image, "PNG")
    r = client.post("/api/attack-lab/prepare", files={"file": ("test.png", file_bytes, "image/png")})
    exp_id = r.json()["experiment_id"]

    # Apply copy-move with unique marker coordinates
    marker_x, marker_y = 123, 147
    cm_params = {"src_x": 20, "src_y": 20, "src_w": 50, "src_h": 50, "dst_x": marker_x, "dst_y": marker_y}
    client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "copy_move", "params": json.dumps(cm_params)},
    )

    recorded_calls = []

    # Spy on detector invocation
    from app.services import copy_move_service as cm_mod
    orig_cm = cm_mod.detect_copy_move

    def spy_detect_copy_move(rgb, params):
        recorded_calls.append(("copy_move", rgb, params))
        return orig_cm(rgb, params)

    monkeypatch.setattr(cm_mod, "detect_copy_move", spy_detect_copy_move)

    # Run analysis
    r_an = client.post(
        "/api/attack-lab/analyze",
        data={"experiment_id": exp_id, "methods": "copy_move"},
    )
    assert r_an.status_code == 200
    assert len(recorded_calls) == 1

    method_name, passed_rgb, passed_params = recorded_calls[0]
    # Check that passed_rgb is just the image (3-channel uint8 array)
    assert passed_rgb.ndim == 3 and passed_rgb.shape[2] == 3
    # Check that params only contains standard detector settings, NO ground-truth or attack info
    params_dict = passed_params.__dict__
    assert "src_x" not in params_dict and "dst_x" not in params_dict
    assert "ground_truth" not in params_dict
    assert "transformation" not in params_dict
    assert marker_x not in params_dict.values()
    assert marker_y not in params_dict.values()


def test_reproducibility_seeded_experiment(client):
    img1 = synth.textured(320, 240, seed=12345)
    img2 = synth.textured(320, 240, seed=12345)

    r1 = client.post("/api/attack-lab/prepare", files={"file": ("s.png", to_bytes(img1), "image/png")})
    r2 = client.post("/api/attack-lab/prepare", files={"file": ("s.png", to_bytes(img2), "image/png")})

    id1, id2 = r1.json()["experiment_id"], r2.json()["experiment_id"]

    cm_p = {"src_x": 10, "src_y": 10, "src_w": 40, "src_h": 40, "dst_x": 80, "dst_y": 80}
    t1 = client.post("/api/attack-lab/transform", data={"experiment_id": id1, "transformation": "copy_move", "params": json.dumps(cm_p)})
    t2 = client.post("/api/attack-lab/transform", data={"experiment_id": id2, "transformation": "copy_move", "params": json.dumps(cm_p)})

    b1 = client.get(f"/api/results/{id1}/modified.png").content
    b2 = client.get(f"/api/results/{id2}/modified.png").content
    assert b1 == b2

    gt1 = client.get(f"/api/results/{id1}/ground_truth.png").content
    gt2 = client.get(f"/api/results/{id2}/ground_truth.png").content
    assert gt1 == gt2


def test_report_generation_and_html_sanitization(client, test_image):
    file_bytes = to_bytes(test_image, "PNG")
    xss_payload = "<script>alert('xss')</script>"
    # Prepare image with XSS text in watermark
    r = client.post(
        "/api/attack-lab/prepare",
        data={"visible_watermark": "true", "watermark_text": xss_payload},
        files={"file": ("test.png", file_bytes, "image/png")},
    )
    assert r.status_code == 200
    exp_id = r.json()["experiment_id"]

    # Transform: Occlusion
    client.post(
        "/api/attack-lab/transform",
        data={"experiment_id": exp_id, "transformation": "occlusion", "params": json.dumps({"x": 10, "y": 10, "width": 50, "height": 50})},
    )

    # Analyze
    client.post(
        "/api/attack-lab/analyze",
        data={"experiment_id": exp_id, "methods": "copy_move,splicing"},
    )

    # 1. JSON Report
    r_json = client.get(f"/api/attack-lab/experiments/{exp_id}/report?format=json")
    assert r_json.status_code == 200
    j_rep = r_json.json()
    assert "experiment_id" in j_rep
    assert "report_generated_at" in j_rep
    assert "disclaimer" in j_rep
    assert "answers" in j_rep
    assert "evaluation" in j_rep
    # Ensure server secret key is never present
    json_str = r_json.text
    assert "IMAGEGUARD_WATERMARK_KEY" not in json_str
    assert "unit-test-key" not in json_str

    # 2. HTML Report
    r_html = client.get(f"/api/attack-lab/experiments/{exp_id}/report?format=html")
    assert r_html.status_code == 200
    assert "text/html" in r_html.headers.get("content-type", "")
    html_text = r_html.text
    # Ensure raw script tag is escaped and not executed
    assert "<script>alert('xss')</script>" not in html_text
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_text or "&lt;script&gt;" in html_text
    # Ensure embedded base64 images exist
    assert "data:image/png;base64," in html_text
    # Ensure internal file system paths are not leaked
    assert "/Users/" not in html_text
    assert "/home/" not in html_text


def test_attack_lab_security_limits(client, test_image, monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()

    # 1. Reject oversized uploads
    monkeypatch.setattr(settings, "max_upload_bytes", 500)
    file_bytes = to_bytes(test_image, "PNG")
    r_large = client.post("/api/attack-lab/prepare", files={"file": ("large.png", file_bytes, "image/png")})
    assert r_large.status_code == 413
    assert r_large.json()["error"]["code"] == "file_too_large"

    # Reset max upload bytes
    monkeypatch.setattr(settings, "max_upload_bytes", 10_000_000)

    # 2. Reject unsupported formats (e.g. GIF)
    gif_bytes = to_bytes(Image.fromarray(test_image).convert("P"), "GIF")
    r_gif = client.post("/api/attack-lab/prepare", files={"file": ("test.gif", gif_bytes, "image/gif")})
    assert r_gif.status_code == 415
    assert r_gif.json()["error"]["code"] == "unsupported_format"

    # 3. Path traversal attempts on results endpoint
    assert client.get("/api/results/../../etc/passwd").status_code == 404
    assert client.get("/api/results/exp123/../../../etc/passwd").status_code == 404


