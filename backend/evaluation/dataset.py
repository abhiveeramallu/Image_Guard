"""Deterministic synthetic evaluation set with ground-truth masks.

Everything is generated from fixed seeds (disjoint from the seeds used to tune the splicing
heuristic: 200-211). Files are written to evaluation/data/synthetic/ as PNG/JPEG plus
manifest.json. These are *synthetic* images; results do not transfer to real photographs.
"""
import json
from pathlib import Path

import cv2
import numpy as np

from tests import synth
from tests.synth_splice import jpeg_roundtrip, photo_like, splice

ROOT = Path(__file__).parent / "data" / "synthetic"
SEEDS = range(500, 506)  # 6 base scenes


def _save(img: np.ndarray, path: Path, jpeg_q: int | None = None) -> None:
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    if jpeg_q:
        cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, jpeg_q])
    else:
        cv2.imwrite(str(path), bgr)


def build(root: Path = ROOT) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []

    def add(case_id, category, img, gt, jpeg_q=None, notes=""):
        ext = "jpg" if jpeg_q else "png"
        _save(img, root / f"{case_id}.{ext}", jpeg_q)
        if gt is not None:
            cv2.imwrite(str(root / f"{case_id}_gt.png"), gt)
        cases.append({"id": case_id, "category": category, "file": f"{case_id}.{ext}",
                      "gt": f"{case_id}_gt.png" if gt is not None else None, "manipulated": gt is not None and bool(gt.any()),
                      "jpeg": bool(jpeg_q), "notes": notes})

    for s in SEEDS:
        base = synth.textured(seed=s)                # unique texture, used for copy-move
        scene = photo_like(seed=s)                   # photo-like noise, used for splicing / clean
        add(f"clean_tex_{s}", "clean", base, None)
        add(f"clean_scene_{s}", "clean", scene, None)
        add(f"clean_scene_jpg85_{s}", "clean_jpeg", jpeg_roundtrip(scene, 85), None, 85)
        add(f"clean_scene_jpg60_{s}", "clean_jpeg", jpeg_roundtrip(scene, 60), None, 60)

        f, gt, *_ = synth.copy_move(base)
        add(f"cm_translate_{s}", "copy_move_translation", f, gt)
        f2, gt2, *_ = synth.copy_move(base, angle=25)
        add(f"cm_rotate25_{s}", "copy_move_rotation", f2, gt2)
        f3, gt3, *_ = synth.copy_move(base, scale=0.8)
        add(f"cm_scale08_{s}", "copy_move_scale", f3, gt3)
        add(f"cm_translate_jpg75_{s}", "copy_move_jpeg", jpeg_roundtrip(f, 75), gt, 75)
        small = cv2.resize(f, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)
        gts = cv2.resize(gt, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
        add(f"cm_translate_resize075_{s}", "copy_move_resized", small, gts)

        sp, spgt = splice(scene, donor_seed=s + 90, donor_noise=9.0)
        add(f"splice_noisy_donor_{s}", "splice_different_noise", sp, spgt)
        add(f"splice_noisy_donor_jpg90_{s}", "splice_different_noise_jpeg", jpeg_roundtrip(sp, 90), spgt, 90)
        sp2, spgt2 = splice(scene, donor_seed=s + 90, donor_noise=3.0, shape="ellipse", blend=3)
        add(f"splice_same_noise_blend_{s}", "splice_matched_noise", sp2, spgt2, notes="donor noise equals base noise; feathered ellipse")
        sp3 = jpeg_roundtrip(sp2, 90)
        add(f"splice_same_noise_jpg90_{s}", "splice_matched_noise_jpeg", sp3, spgt2, 90)

    for s in range(3):
        tile = synth.textured(64, 64, seed=700 + s)
        add(f"repeat_pattern_{s}", "repeated_pattern", np.tile(tile, (8, 10, 1)), None, notes="periodic texture, no manipulation")
    add("flat_gray", "low_texture", np.full((400, 500, 3), 128, np.uint8), None)
    g = np.tile(np.linspace(0, 255, 500, dtype=np.uint8), (400, 1))
    add("gradient", "low_texture", np.stack([g] * 3, axis=2), None)
    (root / "manifest.json").write_text(json.dumps(cases, indent=1))
    return cases
