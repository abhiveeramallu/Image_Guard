"""Reproducible synthetic evaluation.

    cd backend && .venv/bin/python -m evaluation.run [--out evaluation/results]

Generates the synthetic set, runs copy-move, the experimental splicing heuristic, (if configured) the
ONNX localization model, and invisible-watermark robustness trials, then writes JSON, CSV and a Markdown
summary. Synthetic results demonstrate that the pipelines execute and behave on controlled inputs; they do
NOT demonstrate forensic accuracy on real photographs.
"""
import argparse
import csv
import json
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from app.core.config import get_settings
from app.services import copy_move_service as cm
from app.services import invisible_watermark_service as iw
from app.services import localization_service as loc
from app.services import splicing_service as sp
from evaluation import dataset, metrics
from tests.synth_splice import jpeg_roundtrip, photo_like

KEY = b"evaluation-only-key"


def load(case, root):
    bgr = cv2.imread(str(root / case["file"]), cv2.IMREAD_COLOR)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    gt = cv2.imread(str(root / case["gt"]), cv2.IMREAD_GRAYSCALE) if case["gt"] else np.zeros(rgb.shape[:2], np.uint8)
    return rgb, gt


def run_detection(cases, root) -> dict:
    s = get_settings()
    model_status = loc.manager.status(s)
    rows = []
    for c in cases:
        rgb, gt = load(c, root)
        for method in ("copy_move", "splicing", "localization"):
            if method == "localization" and not model_status["available"]:
                continue
            t0 = time.perf_counter()
            if method == "copy_move":
                o = cm.detect_copy_move(rgb)
                pred, positive, status = o.mask, o.status == "candidate_regions_found", o.status
            elif method == "splicing":
                o = sp.detect_splicing(rgb, is_jpeg=c["jpeg"])
                pred, positive, status = o.mask if o.mask is not None else np.zeros(gt.shape, np.uint8), o.status == "candidate_regions_found", o.status
            else:
                o = loc.localize(rgb, s)
                pred, positive, status = o.mask, o.status == "candidate_regions_found", o.status
            ms = (time.perf_counter() - t0) * 1000
            cnt = metrics.pixel_counts(pred, gt)
            rows.append({"case": c["id"], "category": c["category"], "method": method, "manipulated": c["manipulated"],
                         "status": status, "predicted_positive": positive, "ms": round(ms, 1), **cnt, **{k: v for k, v in metrics.prf(cnt).items()}})
    return {"rows": rows, "localization": model_status}


def summarise_detection(rows) -> dict:
    out: dict = {}
    # Which cases are relevant to which method (ground truth defined for that manipulation type)
    relevant = {
        "copy_move": lambda r: r["category"].startswith("copy_move") or r["category"] in ("clean", "clean_jpeg", "repeated_pattern", "low_texture"),
        "splicing": lambda r: r["category"].startswith("splice") or r["category"] in ("clean", "clean_jpeg", "repeated_pattern", "low_texture"),
        "localization": lambda r: True,
    }
    for method in sorted({r["method"] for r in rows}):
        sub = [r for r in rows if r["method"] == method and relevant[method](r)]
        pos = [r for r in sub if r["manipulated"]]
        per_cat = {}
        for cat in sorted({r["category"] for r in sub}):
            cr = [r for r in sub if r["category"] == cat]
            entry = {"n": len(cr), "positive_rate": round(sum(r["predicted_positive"] for r in cr) / len(cr), 3),
                     "mean_ms": round(float(np.mean([r["ms"] for r in cr])), 1),
                     "inconclusive_rate": round(sum(r["status"] == "inconclusive" for r in cr) / len(cr), 3)}
            if any(r["manipulated"] for r in cr):
                agg = metrics.aggregate_pixels(cr)
                entry["pixel"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in agg.items()}
                ious = [r["iou"] for r in cr if r["iou"] is not None]
                entry["mean_per_image_iou"] = round(float(np.mean(ious)), 3) if ious else None
            per_cat[cat] = entry
        out[method] = {
            "image_level": metrics.image_level([(r["manipulated"], r["predicted_positive"]) for r in sub]),
            "pixel_level_on_manipulated": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in metrics.aggregate_pixels(pos).items()} if pos else None,
            "by_category": per_cat,
        }
    return out


def run_watermark_robustness(n_images=6) -> dict:
    transforms = {
        "none (in-memory)": lambda x: x,
        "jpeg_q95": lambda x: jpeg_roundtrip(x, 95), "jpeg_q85": lambda x: jpeg_roundtrip(x, 85),
        "jpeg_q75": lambda x: jpeg_roundtrip(x, 75), "jpeg_q60": lambda x: jpeg_roundtrip(x, 60),
        "jpeg_q40": lambda x: jpeg_roundtrip(x, 40), "jpeg_q25": lambda x: jpeg_roundtrip(x, 25),
        "gaussian_noise_sigma2": lambda x: _noise(x, 2), "gaussian_noise_sigma5": lambda x: _noise(x, 5),
        "gaussian_noise_sigma10": lambda x: _noise(x, 10),
        "crop_13_7_px": lambda x: x[13:, 7:], "crop_5%_each_side": lambda x: x[int(.05 * x.shape[0]):-int(.05 * x.shape[0]), int(.05 * x.shape[1]):-int(.05 * x.shape[1])],
        "resize_0.9": lambda x: cv2.resize(x, None, fx=.9, fy=.9, interpolation=cv2.INTER_AREA),
        "resize_0.75": lambda x: cv2.resize(x, None, fx=.75, fy=.75, interpolation=cv2.INTER_AREA),
        "resize_up_1.25": lambda x: cv2.resize(x, None, fx=1.25, fy=1.25, interpolation=cv2.INTER_CUBIC),
        "rotate_2deg": lambda x: _rotate(x, 2),
        "gaussian_blur_sigma1": lambda x: cv2.GaussianBlur(x, (0, 0), 1.0),
    }
    imgs = [photo_like(640, 480, seed=900 + i) for i in range(n_images)]
    marked = [iw.embed(im, f"owner{i}", KEY) for i, im in enumerate(imgs)]
    res = {"n_images": n_images, "mean_psnr_db": round(float(np.mean([m.psnr_db for m in marked])), 2), "transforms": {},
           "unmarked_false_verified": sum(iw.verify(im, KEY).status == "verified" for im in imgs),
           "wrong_key_verified": sum(iw.verify(m.image, b"wrong-key").status == "verified" for m in marked)}
    for name, fn in transforms.items():
        ok = exact = inc = 0
        for i, m in enumerate(marked):
            v = iw.verify(np.ascontiguousarray(fn(m.image)), KEY)
            ok += v.status == "verified"
            exact += v.owner == f"owner{i}"
            inc += v.status == "inconclusive"
        res["transforms"][name] = {"verified": ok, "exact_payload": exact, "integrity_verified_rate": round(ok / n_images, 3),
                                   "inconclusive": inc, "n": n_images}
    return res


def _noise(x, sigma):
    return np.clip(x + np.random.default_rng(0).normal(0, sigma, x.shape), 0, 255).astype(np.uint8)


def _rotate(x, deg):
    h, w = x.shape[:2]
    return cv2.warpAffine(x, cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0), (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def write_markdown(path: Path, det: dict, summary: dict, wm: dict, n_cases: int):
    L = ["# Synthetic evaluation summary", "",
         "> **Synthetic data only.** These numbers describe behaviour on generated images with fixed seeds. They are not evidence of",
         "> accuracy on real photographs, and the splicing heuristic was tuned on different (but similar-generator) seeds.", "",
         f"Cases: {n_cases}. Generated by `python -m evaluation.run`.", ""]
    ms = det["localization"]
    L += [f"**Model localization:** " + ("evaluated with model `" + ms["model"]["id"] + "`." if ms["available"] else
                                        f"NOT evaluated - no model available ({ms['reason']}). Real inference performance has not been measured."), ""]
    for method, s in summary.items():
        il = s["image_level"]
        L += [f"## {method}", "", f"Image-level (relevant cases, n={il['n']}): TP={il['tp']} FP={il['fp']} TN={il['tn']} FN={il['fn']}, "
              f"recall={_f(il['recall'])}, precision={_f(il['precision'])}, false-positive rate={_f(il['false_positive_rate'])}", ""]
        px = s["pixel_level_on_manipulated"]
        if px:
            L += [f"Pixel-level on manipulated images (micro-avg): precision={_f(px['precision'])}, recall={_f(px['recall'])}, F1={_f(px['f1'])}, IoU={_f(px['iou'])} "
                  f"(TP={px['tp']} FP={px['fp']} TN={px['tn']} FN={px['fn']})", ""]
        L += ["| category | n | flagged rate | inconclusive rate | mean ms | pixel P | pixel R | pixel F1 | pixel IoU | mean per-image IoU |", "|---|---|---|---|---|---|---|---|---|---|"]
        for cat, e in s["by_category"].items():
            p = e.get("pixel", {})
            L.append(f"| {cat} | {e['n']} | {e['positive_rate']} | {e['inconclusive_rate']} | {e['mean_ms']} | {_f(p.get('precision'))} | {_f(p.get('recall'))} | {_f(p.get('f1'))} | {_f(p.get('iou'))} | {_f(e.get('mean_per_image_iou'))} |")
        L.append("")
    L += ["## Invisible watermark robustness (synthetic 640x480 images)", "",
          f"Images: {wm['n_images']}, mean PSNR {wm['mean_psnr_db']} dB. Unmarked images verified: {wm['unmarked_false_verified']}; wrong key verified: {wm['wrong_key_verified']}.", "",
          "| transformation | exact payload recovered | integrity verified | inconclusive |", "|---|---|---|---|"]
    for name, t in wm["transforms"].items():
        L.append(f"| {name} | {t['exact_payload']}/{t['n']} | {t['verified']}/{t['n']} ({t['integrity_verified_rate']:.0%}) | {t['inconclusive']} |")
    path.write_text("\n".join(L) + "\n")


def _f(v):
    return "n/a" if v is None else f"{v:.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evaluation/results")
    ap.add_argument("--data", default=str(dataset.ROOT))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    root = Path(a.data)
    cases = dataset.build(root)
    det = run_detection(cases, root)
    summary = summarise_detection(det["rows"])
    wm = run_watermark_robustness()
    (out / "detection_rows.json").write_text(json.dumps(det["rows"], indent=1))
    with open(out / "detection_rows.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(det["rows"][0])); w.writeheader(); w.writerows(det["rows"])
    (out / "summary.json").write_text(json.dumps({"detection": summary, "localization": det["localization"], "watermark": wm,
                                                  "n_cases": len(cases), "synthetic_only": True}, indent=1))
    write_markdown(out / "summary.md", det, summary, wm, len(cases))
    print((out / "summary.md").read_text())


if __name__ == "__main__":
    main()
