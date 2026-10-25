import io
import json
import logging
import time
from datetime import datetime, timezone
from typing import Annotated, Any

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from PIL import Image

from app.api.deps import job_slot, store
from app.api.routes_capabilities import watermark_key_status
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.attack_lab import (
    BaselineInfo,
    EvaluationMetrics,
    ExperimentAnalysisResponse,
    ExperimentImageInfo,
    ExperimentPrepareResponse,
    ExperimentTransformResponse,
    GroundTruthInfo,
    MethodEvaluation,
    TransformationStep,
)
from app.services import attack_lab_service as lab
from app.services import copy_move_service as cm
from app.services import image_service as imgs
from app.services import invisible_watermark_service as iw
from app.services import localization_service as loc
from app.services import splicing_service as sp
from app.services import watermark_service as wm
from app.services.forensics_common import heatmap_overlay, mask_overlay, score_png16

router = APIRouter(prefix="/attack-lab")
settings = get_settings()
log = logging.getLogger("imageguard.attack_lab")


def _get_meta(experiment_id: str) -> dict[str, Any]:
    meta_bytes = store.get(experiment_id, "analysis.json")
    if meta_bytes is None:
        raise ApiError(404, "not_found", "Experiment session expired or not found. Please prepare a new image.")
    return json.loads(meta_bytes.decode("utf-8"))


def _save_meta(experiment_id: str, meta: dict[str, Any], extra_files: dict[str, bytes] | None = None) -> None:
    # Existing files in store must be preserved
    current_files: dict[str, bytes] = {}
    with store._lock:
        item = store._items.get(experiment_id)
        if item:
            current_files.update(item[1])
    if extra_files:
        current_files.update(extra_files)
    current_files["analysis.json"] = json.dumps(meta, indent=2).encode("utf-8")
    store.put(experiment_id, current_files)


@router.post("/prepare", response_model=ExperimentPrepareResponse)
def prepare(
    file: Annotated[UploadFile, File(description="Source image (JPEG or PNG)")],
    visible_watermark: Annotated[bool, Form()] = False,
    watermark_text: Annotated[str, Form()] = "ImageGuard Protected",
    watermark_position: Annotated[str, Form()] = "bottom-right",
    watermark_opacity: Annotated[float, Form(ge=0, le=1)] = 0.5,
    watermark_font_size: Annotated[int, Form(ge=8, le=400)] = 36,
    watermark_color: Annotated[str, Form()] = "#FFFFFF",
    invisible_watermark: Annotated[bool, Form()] = False,
    invisible_owner: Annotated[str, Form(min_length=1, max_length=12)] = "OWNER-01",
    invisible_strength: Annotated[str, Form()] = "standard",
    logo: Annotated[UploadFile | None, File(description="Optional logo watermark")] = None,
) -> ExperimentPrepareResponse:
    data = imgs.read_upload(file, settings.max_upload_bytes, "source image")
    dec = imgs.decode_image(
        data,
        max_pixels=settings.max_image_pixels,
        max_side=settings.max_image_side,
        min_side=settings.min_image_side,
        label="source image",
    )
    img = dec.image
    if dec.has_alpha:
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    orig_rgb = np.asarray(img.convert("RGB"))
    del data

    warnings: list[str] = []
    if dec.has_alpha:
        warnings.append("Transparency was flattened onto white background.")

    # Create Baseline
    baseline_img = img.copy()

    # 1. Visible watermark
    if visible_watermark:
        logo_img = None
        w_type = "text"
        if logo and logo.filename:
            logo_data = imgs.read_upload(logo, settings.max_logo_bytes, "logo")
            logo_img = imgs.decode_image(logo_data, max_pixels=settings.max_logo_pixels, max_side=4000, label="logo")
            w_type = "logo"

        opts = wm.WatermarkOptions(
            watermark_type=w_type,
            text=watermark_text,
            position=watermark_position,
            opacity=watermark_opacity,
            font_size=watermark_font_size,
            color=watermark_color,
            rotation=0.0,
            margin=24,
            layout="single",
            outline=True,
            shadow=False,
            logo_scale=20.0,
            tile_spacing=60,
        )
        wm.validate_options(opts)
        with job_slot():
            baseline_img = wm.apply_watermark(imgs.DecodedImage(image=baseline_img, has_alpha=False, source_format="PNG"), opts, logo_img)

    # 2. Invisible watermark
    has_invis = False
    if invisible_watermark:
        ok, why = watermark_key_status()
        if not ok:
            warnings.append(f"Invisible watermark could not be embedded: {why}")
        else:
            key = settings.watermark_key.get_secret_value().encode()  # type: ignore[union-attr]
            base_rgb = np.asarray(baseline_img.convert("RGB"))
            if base_rgb.shape[0] * base_rgb.shape[1] < settings.watermark_min_pixels:
                warnings.append("Image is too small for invisible watermark embedding (min 256x256 required). Skipped.")
            else:
                try:
                    with job_slot():
                        res = iw.embed(base_rgb, invisible_owner, key, invisible_strength)
                        baseline_img = Image.fromarray(res.image)
                        has_invis = True
                except iw.WatermarkError as e:
                    warnings.append(f"Invisible watermarking failed: {e}")

    exp_id = store.new_id()
    orig_bytes = imgs.encode_png_array(orig_rgb)
    base_rgb = np.asarray(baseline_img.convert("RGB"))
    base_bytes = imgs.encode_png_array(base_rgb)

    orig_info = ExperimentImageInfo(
        width=orig_rgb.shape[1],
        height=orig_rgb.shape[0],
        format=dec.source_format,
        size_bytes=len(orig_bytes),
    )
    base_info = BaselineInfo(
        width=base_rgb.shape[1],
        height=base_rgb.shape[0],
        format="PNG",
        has_visible_watermark=visible_watermark,
        visible_watermark_text=watermark_text if visible_watermark else None,
        has_invisible_watermark=has_invis,
        invisible_owner=invisible_owner if has_invis else None,
    )

    artifacts = {
        "original": f"/api/results/{exp_id}/original.png",
        "baseline": f"/api/results/{exp_id}/baseline.png",
        "modified": f"/api/results/{exp_id}/modified.png",
    }

    meta = {
        "experiment_id": exp_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "original_image": orig_info.model_dump(),
        "baseline_image": base_info.model_dump(),
        "history": [],
        "ground_truth": {"has_mask": False, "regions": []},
        "artifacts": artifacts,
        "warnings": warnings,
    }

    files = {
        "original.png": orig_bytes,
        "baseline.png": base_bytes,
        "modified.png": base_bytes,
        "analysis.json": json.dumps(meta).encode("utf-8"),
    }
    store.put(exp_id, files)

    return ExperimentPrepareResponse(
        experiment_id=exp_id,
        original_image=orig_info,
        baseline_image=base_info,
        artifacts=artifacts,
        history=[],
        warnings=warnings,
    )


@router.post("/transform", response_model=ExperimentTransformResponse)
def transform(
    experiment_id: Annotated[str, Form()],
    transformation: Annotated[str, Form()],
    target: Annotated[str, Form()] = "current",  # "current" | "baseline"
    params: Annotated[str, Form()] = "{}",
    donor_file: Annotated[UploadFile | None, File(description="Optional donor image for splicing")] = None,
) -> ExperimentTransformResponse:
    if target not in ("current", "baseline"):
        raise ApiError(422, "invalid_parameters", "target must be 'current' or 'baseline'.")

    meta = _get_meta(experiment_id)
    try:
        p = json.loads(params)
    except json.JSONDecodeError:
        raise ApiError(422, "invalid_parameters", "params must be valid JSON.")

    source_key = "baseline.png" if target == "baseline" else "modified.png"
    source_bytes = store.get(experiment_id, source_key)
    if source_bytes is None:
        raise ApiError(404, "not_found", "Source image not found in experiment session.")

    source_img = Image.open(io.BytesIO(source_bytes)).convert("RGB")
    source_rgb = np.asarray(source_img)

    warnings: list[str] = []
    desc = ""
    gt_mask: np.ndarray | None = None
    gt_regions: list[dict[str, Any]] = []

    with job_slot():
        if transformation == "occlusion":
            x = int(p.get("x", 0))
            y = int(p.get("y", 0))
            w = int(p.get("width", 100))
            h = int(p.get("height", 100))
            color = str(p.get("color", "#000000"))
            opacity = float(p.get("opacity", 1.0))
            mod_rgb, gt_mask, meta_t = lab.occlude_watermark(source_rgb, x, y, w, h, color, opacity)
            desc = f"Visible patch occlusion at ({x}, {y}, {w}x{h}) with opacity {opacity}"
            gt_regions.append({"type": "occlusion", **meta_t})

        elif transformation == "crop":
            preset = p.get("preset")
            x = int(p.get("x", 0)) if not preset else 0
            y = int(p.get("y", 0)) if not preset else 0
            w = int(p.get("width", 0)) if not preset else None
            h = int(p.get("height", 0)) if not preset else None
            mod_rgb, _, meta_t = lab.crop_image(source_rgb, x, y, w, h, preset)
            desc = f"Cropping: {preset or f'{w}x{h} from ({x}, {y})'}"
            warnings.append("Cropping modifies spatial dimensions and DCT block grid alignment.")

        elif transformation == "blur":
            radius = float(p.get("radius", 3.0))
            mod_rgb, _, meta_t = lab.blur_image(source_rgb, radius)
            desc = f"Gaussian blur with radius {radius}"

        elif transformation == "jpeg":
            quality = int(p.get("quality", 70))
            mod_rgb, _, meta_t, _ = lab.jpeg_recompress(source_rgb, quality)
            desc = f"JPEG recompression at quality {quality}"
            warnings.append(f"Lossy JPEG compression derivative created at quality {quality}.")

        elif transformation == "resize":
            scale = float(p.get("scale", 0.75))
            mod_rgb, _, meta_t = lab.resize_image(source_rgb, scale, max_pixels=settings.max_image_pixels)
            desc = f"Resized by {scale}x ({meta_t['original_size'][0]}x{meta_t['original_size'][1]} -> {meta_t['output_size'][0]}x{meta_t['output_size'][1]})"
            warnings.append("Resizing disrupts pixel coordinate alignments and DCT watermark grids.")

        elif transformation == "rotation":
            angle = float(p.get("angle", 5.0))
            expand = bool(p.get("expand", False))
            mod_rgb, _, meta_t = lab.rotate_image(source_rgb, angle, expand)
            desc = f"Rotated by {angle}° ({'expanded' if expand else 'fixed canvas with padding'})"
            if not expand:
                warnings.append("Canvas size maintained; non-axial borders padded with black pixels.")

        elif transformation == "copy_move":
            src_x = int(p.get("src_x", 0))
            src_y = int(p.get("src_y", 0))
            src_w = int(p.get("src_w", 50))
            src_h = int(p.get("src_h", 50))
            dst_x = int(p.get("dst_x", 60))
            dst_y = int(p.get("dst_y", 60))
            mod_rgb, gt_mask, meta_t = lab.copy_move_tamper(source_rgb, src_x, src_y, src_w, src_h, dst_x, dst_y)
            desc = f"Copy-move: ({src_x},{src_y},{src_w}x{src_h}) pasted to ({dst_x},{dst_y})"
            gt_regions.append({"type": "copy_move_destination", "x": dst_x, "y": dst_y, "width": src_w, "height": src_h})
            gt_regions.append({"type": "copy_move_source", "x": src_x, "y": src_y, "width": src_w, "height": src_h})

        elif transformation == "splicing":
            if donor_file is None or not donor_file.filename:
                raise ApiError(422, "invalid_parameters", "A donor image file is required for content splicing.")
            donor_data = imgs.read_upload(donor_file, settings.max_upload_bytes, "donor image")
            donor_dec = imgs.decode_image(
                donor_data,
                max_pixels=settings.max_image_pixels,
                max_side=settings.max_image_side,
                min_side=settings.min_image_side,
                label="donor image",
            )
            d_img = donor_dec.image
            if donor_dec.has_alpha:
                flat = Image.new("RGB", d_img.size, (255, 255, 255))
                flat.paste(d_img, mask=d_img.getchannel("A"))
                d_img = flat
            donor_rgb = np.asarray(d_img.convert("RGB"))

            donor_x = int(p.get("donor_x", 0))
            donor_y = int(p.get("donor_y", 0))
            donor_w = int(p.get("donor_w", min(100, donor_rgb.shape[1])))
            donor_h = int(p.get("donor_h", min(100, donor_rgb.shape[0])))
            target_x = int(p.get("target_x", 0))
            target_y = int(p.get("target_y", 0))
            target_w = int(p.get("target_w", donor_w))
            target_h = int(p.get("target_h", donor_h))

            mod_rgb, gt_mask, meta_t = lab.splice_content(
                source_rgb, donor_rgb, donor_x, donor_y, donor_w, donor_h, target_x, target_y, target_w, target_h
            )
            desc = f"Spliced donor region ({donor_w}x{donor_h}) into target at ({target_x},{target_y},{target_w}x{target_h})"
            gt_regions.append({"type": "spliced_destination", "x": target_x, "y": target_y, "width": target_w, "height": target_h})
            warnings.append("Controlled splicing simulation: experimental noise/ELA heuristics may not detect clean splices.")

        else:
            raise ApiError(422, "invalid_parameters", f"Unsupported transformation: {transformation}")

    step_num = 1 if target == "baseline" else len(meta.get("history", [])) + 1
    step_info = TransformationStep(
        step=step_num,
        transformation=transformation,
        params=p,
        description=desc,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        output_size=[mod_rgb.shape[1], mod_rgb.shape[0]],
    )

    if target == "baseline":
        history = [step_info.model_dump()]
        existing_gt_bytes = None
    else:
        history = meta.get("history", []) + [step_info.model_dump()]
        existing_gt_bytes = store.get(experiment_id, "ground_truth.png")

    existing_gt_mask = (
        np.asarray(Image.open(io.BytesIO(existing_gt_bytes)))
        if existing_gt_bytes
        else None
    )

    if existing_gt_mask is not None:
        if gt_mask is not None:
            # Composite multiple tampered regions
            if existing_gt_mask.shape == gt_mask.shape:
                gt_mask = np.maximum(existing_gt_mask, gt_mask)
        elif transformation in ("crop", "resize", "rotation"):
            # Update ground truth mask with the exact same geometric mapping
            gt_mask = lab.transform_ground_truth_mask(existing_gt_mask, transformation, meta_t)
        elif transformation in ("blur", "jpeg"):
            gt_mask = existing_gt_mask

    new_files: dict[str, bytes] = {
        "modified.png": imgs.encode_png_array(mod_rgb),
    }

    gt_info = GroundTruthInfo(has_mask=False, regions=[])
    if gt_mask is not None and (gt_mask > 0).sum() > 0:
        new_files["ground_truth.png"] = imgs.encode_png_array(gt_mask)
        gt_info = GroundTruthInfo(
            has_mask=True,
            transformation=transformation,
            regions=gt_regions or meta.get("ground_truth", {}).get("regions", []),
            mask_artifact=f"/api/results/{experiment_id}/ground_truth.png",
            notes=f"Simulated ground truth tracked across transformations.",
        )
    else:
        # If tampered region was cropped out or reset, remove stale ground truth
        with store._lock:
            item = store._items.get(experiment_id)
            if item and "ground_truth.png" in item[1]:
                del item[1]["ground_truth.png"]

    meta["history"] = history
    meta["ground_truth"] = gt_info.model_dump()
    meta["modified_image"] = {
        "width": mod_rgb.shape[1],
        "height": mod_rgb.shape[0],
        "format": "PNG",
    }

    # Purge any stale detector artifacts and reports from previous analysis runs
    with store._lock:
        item = store._items.get(experiment_id)
        if item:
            files_dict = item[1]
            stale_keys = [
                k for k in list(files_dict.keys())
                if k.startswith(("copy_move.", "splicing.", "localization.", "experiment_report."))
            ]
            for k in stale_keys:
                files_dict.pop(k, None)

    _save_meta(experiment_id, meta, new_files)

    artifacts = {
        "original": f"/api/results/{experiment_id}/original.png",
        "baseline": f"/api/results/{experiment_id}/baseline.png",
        "modified": f"/api/results/{experiment_id}/modified.png",
    }
    if gt_info.has_mask:
        artifacts["ground_truth"] = f"/api/results/{experiment_id}/ground_truth.png"

    return ExperimentTransformResponse(
        experiment_id=experiment_id,
        transformation=transformation,
        params=p,
        image=ExperimentImageInfo(
            width=mod_rgb.shape[1],
            height=mod_rgb.shape[0],
            format="PNG",
        ),
        ground_truth=gt_info,
        artifacts=artifacts,
        history=[TransformationStep(**s) for s in history],
        warnings=warnings,
    )


@router.post("/reset", response_model=ExperimentTransformResponse)
def reset_to_baseline(experiment_id: Annotated[str, Form()]) -> ExperimentTransformResponse:
    meta = _get_meta(experiment_id)
    base_bytes = store.get(experiment_id, "baseline.png")
    if base_bytes is None:
        raise ApiError(404, "not_found", "Baseline image expired or not found.")

    base_img = Image.open(io.BytesIO(base_bytes))
    w, h = base_img.size

    meta["history"] = []
    meta["ground_truth"] = {"has_mask": False, "regions": []}
    meta["modified_image"] = {"width": w, "height": h, "format": "PNG"}
    meta.pop("analysis", None)
    meta.pop("detection_results", None)

    with store._lock:
        item = store._items.get(experiment_id)
        if item:
            files_dict = item[1]
            stale_keys = [
                k for k in list(files_dict.keys())
                if k.startswith(("copy_move.", "splicing.", "localization.", "experiment_report."))
                or k == "ground_truth.png"
            ]
            for k in stale_keys:
                files_dict.pop(k, None)

    new_files = {
        "modified.png": base_bytes,
    }
    _save_meta(experiment_id, meta, new_files)

    return ExperimentTransformResponse(
        experiment_id=experiment_id,
        transformation="reset",
        params={},
        image=ExperimentImageInfo(width=w, height=h, format="PNG"),
        ground_truth=GroundTruthInfo(has_mask=False, regions=[]),
        artifacts={
            "original": f"/api/results/{experiment_id}/original.png",
            "baseline": f"/api/results/{experiment_id}/baseline.png",
            "modified": f"/api/results/{experiment_id}/modified.png",
        },
        history=[],
        warnings=["Reset working image to protected baseline."],
    )


@router.post("/analyze", response_model=ExperimentAnalysisResponse)
def analyze_experiment(
    experiment_id: Annotated[str, Form()],
    methods: Annotated[str, Form()] = "copy_move,splicing,watermark_verify",
    splicing_threshold: Annotated[float, Form(ge=0.05, le=0.99)] = 0.5,
    localization_threshold: Annotated[float, Form(ge=0.01, le=0.99)] = 0.5,
    max_dimension: Annotated[int, Form(ge=256, le=3000)] = 1280,
    n_features: Annotated[int, Form(ge=500, le=20000)] = 5000,
    ratio: Annotated[float, Form(ge=0.5, le=0.95)] = 0.80,
    min_matches: Annotated[int, Form(ge=4, le=100)] = 6,
    min_displacement: Annotated[float, Form(ge=4, le=500)] = 24,
) -> ExperimentAnalysisResponse:
    t0 = time.perf_counter()
    meta = _get_meta(experiment_id)
    mod_bytes = store.get(experiment_id, "modified.png")
    if mod_bytes is None:
        raise ApiError(404, "not_found", "Modified image not found or expired.")

    mod_img = Image.open(io.BytesIO(mod_bytes)).convert("RGB")
    mod_rgb = np.asarray(mod_img)

    valid_methods = {"copy_move", "splicing", "localization", "watermark_verify"}
    wanted = [m.strip() for m in methods.split(",") if m.strip()]
    if not wanted:
        raise ApiError(422, "invalid_parameters", "At least one detection or verification method must be specified.")
    bad_methods = [m for m in wanted if m not in valid_methods]
    if bad_methods:
        raise ApiError(422, "invalid_parameters", f"Unknown method(s): {', '.join(bad_methods)}.")
    detector_files: dict[str, bytes] = {}
    detection_results: list[dict[str, Any]] = []
    wm_result: dict[str, Any] | None = None
    pred_masks: dict[str, np.ndarray] = {}

    with job_slot():
        # 1. Copy-Move Detection
        if "copy_move" in wanted:
            cm_params = cm.CopyMoveParams(
                max_dimension=max_dimension,
                n_features=n_features,
                ratio=ratio,
                min_matches=min_matches,
                min_displacement=min_displacement,
            )
            try:
                cm_out = cm.detect_copy_move(mod_rgb, cm_params)
                detector_files["copy_move.annotated"] = imgs.encode_png_array(cm_out.annotated)
                detector_files["copy_move.mask"] = imgs.encode_png_array(cm_out.mask)
                detector_files["copy_move.heatmap"] = imgs.encode_png_array(cm_out.heatmap)
                pred_masks["copy_move"] = cm_out.mask
                log.info(
                    "Attack Lab copy-move analysis for %s: status=%s, keypoints=%d, raw_matches=%d, filtered=%d, retained=%d, regions=%d",
                    experiment_id,
                    cm_out.status,
                    cm_out.keypoints,
                    cm_out.matches_before_filtering,
                    cm_out.matches_after_descriptor_filtering,
                    cm_out.matches_retained,
                    len(cm_out.regions),
                )
                detection_results.append({
                    "method": "copy_move",
                    "status": cm_out.status,
                    "status_reason": cm_out.status_reason,
                    "region_count": len(cm_out.regions),
                    "regions": [r.__dict__ for r in cm_out.regions],
                    "processing_ms": cm_out.processing_ms,
                    "metrics": {
                        "keypoints": cm_out.keypoints,
                        "raw_matches": cm_out.matches_before_filtering,
                        "filtered_matches": cm_out.matches_after_descriptor_filtering,
                        "matches_retained": cm_out.matches_retained,
                        "accepted_clusters": len(cm_out.regions),
                        "rejected_clusters": getattr(cm_out, "rejected_clusters", 0),
                    },
                    "artifacts": {
                        "annotated": f"/api/results/{experiment_id}/copy_move.annotated",
                        "mask": f"/api/results/{experiment_id}/copy_move.mask",
                        "heatmap": f"/api/results/{experiment_id}/copy_move.heatmap",
                    },
                    "limitations": cm.LIMITATIONS,
                })
            except Exception as e:
                log.exception("Copy-move failed")
                detection_results.append({
                    "method": "copy_move",
                    "status": "failed",
                    "status_reason": str(e),
                    "region_count": 0,
                    "artifacts": {},
                })

        # 2. Splicing Heuristic
        if "splicing" in wanted:
            try:
                # Splicing heuristic check
                sp_out = sp.detect_splicing(mod_rgb, False, sp.SplicingParams(threshold=splicing_threshold))
                names = []
                if sp_out.score is not None:
                    detector_files["splicing.heatmap"] = imgs.encode_png_array(heatmap_overlay(mod_rgb, sp_out.score))
                    detector_files["splicing.score"] = score_png16(sp_out.score)
                    names += ["heatmap", "score"]
                if sp_out.mask is not None:
                    detector_files["splicing.mask"] = imgs.encode_png_array(sp_out.mask)
                    detector_files["splicing.overlay"] = imgs.encode_png_array(mask_overlay(mod_rgb, sp_out.mask))
                    names += ["mask", "overlay"]
                    pred_masks["splicing"] = sp_out.mask

                detection_results.append({
                    "method": "splicing",
                    "status": sp_out.status,
                    "status_reason": sp_out.status_reason,
                    "threshold": sp_out.threshold,
                    "region_count": len(sp_out.regions),
                    "regions": sp_out.regions,
                    "processing_ms": sp_out.processing_ms,
                    "metrics": sp_out.metrics,
                    "artifacts": {n: f"/api/results/{experiment_id}/splicing.{n}" for n in names},
                    "limitations": sp.LIMITATIONS,
                })
            except Exception as e:
                log.exception("Splicing failed")
                detection_results.append({
                    "method": "splicing",
                    "status": "failed",
                    "status_reason": str(e),
                    "region_count": 0,
                    "artifacts": {},
                })

        # 3. Model Localization (if configured)
        if "localization" in wanted:
            try:
                loc_out = loc.localize(mod_rgb, settings, localization_threshold)
                names = []
                if loc_out.score is not None:
                    detector_files["localization.heatmap"] = imgs.encode_png_array(heatmap_overlay(mod_rgb, loc_out.score))
                    names.append("heatmap")
                if loc_out.mask is not None:
                    detector_files["localization.mask"] = imgs.encode_png_array(loc_out.mask)
                    detector_files["localization.overlay"] = imgs.encode_png_array(mask_overlay(mod_rgb, loc_out.mask))
                    names += ["mask", "overlay"]
                    pred_masks["localization"] = loc_out.mask

                detection_results.append({
                    "method": "localization",
                    "status": loc_out.status,
                    "status_reason": loc_out.status_reason,
                    "model": loc_out.metrics.get("model"),
                    "threshold": loc_out.threshold,
                    "region_count": len(loc_out.regions),
                    "processing_ms": loc_out.processing_ms,
                    "artifacts": {n: f"/api/results/{experiment_id}/localization.{n}" for n in names},
                    "limitations": loc.LIMITATIONS,
                })
            except loc.ModelUnavailable as e:
                detection_results.append({
                    "method": "localization",
                    "status": "unavailable",
                    "status_reason": str(e),
                    "region_count": 0,
                    "artifacts": {},
                    "limitations": loc.LIMITATIONS,
                })
            except Exception as e:
                log.exception("Localization failed")
                detection_results.append({
                    "method": "localization",
                    "status": "failed",
                    "status_reason": str(e),
                    "region_count": 0,
                    "artifacts": {},
                })

        # 4. Invisible Watermark Verification
        if "watermark_verify" in wanted:
            ok, why = watermark_key_status()
            if not ok:
                wm_result = {
                    "status": "unavailable",
                    "status_reason": f"Watermark verification unavailable: {why}",
                    "owner": None,
                    "integrity_verified": False,
                }
            else:
                key = settings.watermark_key.get_secret_value().encode()  # type: ignore[union-attr]
                try:
                    vr = iw.verify(mod_rgb, key)
                    reason_map = {
                        "verified": "A keyed payload with a valid HMAC integrity check was recovered.",
                        "inconclusive": "A watermark pattern was found but the HMAC integrity check failed (damaged payload).",
                        "not_detected": "No watermark matching the server key was found (unmarked or destroyed by transformation).",
                    }
                    wm_result = {
                        "status": vr.status,
                        "status_reason": reason_map.get(vr.status, "Watermark check complete."),
                        "owner": vr.owner,
                        "integrity_verified": vr.integrity_verified,
                        "metrics": {
                            "bit_strength": vr.bit_strength,
                            "delta": vr.delta,
                            "class_shift": vr.class_shift,
                        },
                        "limitations": iw.LIMITATIONS,
                    }
                except Exception as e:
                    wm_result = {
                        "status": "failed",
                        "status_reason": f"Verification failed: {e}",
                        "owner": None,
                        "integrity_verified": False,
                    }

    # Evaluate against Ground Truth if available
    eval_list: list[MethodEvaluation] = []
    gt_bytes = store.get(experiment_id, "ground_truth.png")
    gt_mask = np.asarray(Image.open(io.BytesIO(gt_bytes))) if gt_bytes else None
    hist = meta.get("history", [])
    is_baseline_only = len(hist) == 0

    if gt_mask is not None and (gt_mask > 0).sum() > 0:
        for m_name, p_mask in pred_masks.items():
            eval_metrics = lab.evaluate_detection(gt_mask, p_mask, m_name)
            if eval_metrics:
                eval_list.append(MethodEvaluation(
                    method=m_name,
                    metrics=EvaluationMetrics(**eval_metrics),
                    notes=eval_metrics.get("semantics_note", ""),
                ))
    elif is_baseline_only:
        # On a baseline-only image, ground truth has 0 tampered pixels.
        # Evaluate detector predictions against an empty mask to document false alarms on clean input.
        H, W = mod_rgb.shape[:2]
        clean_gt = np.zeros((H, W), dtype=np.uint8)
        for m_name, p_mask in pred_masks.items():
            eval_metrics = lab.evaluate_detection(clean_gt, p_mask, m_name)
            if eval_metrics:
                eval_list.append(MethodEvaluation(
                    method=m_name,
                    metrics=EvaluationMetrics(**eval_metrics),
                    notes="Baseline clean evaluation: 0 ground-truth tampered pixels. Flagged candidate pixels represent false positives on clean input.",
                ))

    # Compile Structured Interpretations (Questions A, B, C)
    if not is_baseline_only:
        steps_summary = "; ".join(f"Step {s['step']}: {s['description']}" for s in hist)
        ans_a = f"Yes. Controlled transformation(s) applied in simulation: {steps_summary}."
    else:
        ans_a = "No transformations applied. The modified image is identical to the baseline (Baseline-Only Analysis)."

    # Question B
    base_info = meta.get("baseline_image", {})
    wm_visible = base_info.get("has_visible_watermark", False)
    wm_invisible = base_info.get("has_invisible_watermark", False)
    b_parts: list[str] = []
    if wm_visible:
        b_parts.append("Visible watermark was included in the baseline.")
    if wm_invisible:
        if wm_result:
            if is_baseline_only:
                b_parts.append(f"Invisible watermark verification on unmodified baseline: '{wm_result['status']}' (Owner ID: {wm_result.get('owner') or 'N/A'}). Watermark payload is intact as expected.")
            else:
                b_parts.append(f"Invisible watermark verification returned '{wm_result['status']}': {wm_result['status_reason']}")
        else:
            b_parts.append("Invisible watermark was embedded, but verification was not requested in this analysis.")
    elif not wm_visible and not wm_invisible:
        b_parts.append("No watermarks were embedded in the baseline image.")
        if wm_result:
            b_parts.append(f"Verification scan on unmarked image: '{wm_result['status']}'.")
    ans_b = " ".join(b_parts)

    # Question C
    c_parts: list[str] = []
    has_candidates = any(d.get("region_count", 0) > 0 for d in detection_results)
    for d in detection_results:
        m = d.get("method")
        s = d.get("status")
        regs = d.get("region_count", 0)
        c_parts.append(f"[{m}] Status '{s}' with {regs} candidate region(s).")
    
    if is_baseline_only:
        if has_candidates:
            ans_c = (
                "Baseline-only findings (unmodified image): " + " ".join(c_parts) +
                " Note: Because no transformation was applied to this baseline, any candidate regions detected above "
                "represent natural image features, repeated scene structures, or heuristic detector false positives "
                "(such as ELA/noise variance)—not evidence of image tampering."
            )
        else:
            ans_c = (
                "Baseline clean: No candidate regions were detected on the unmodified baseline image. " +
                " ".join(c_parts) + " This provides a clean reference baseline for subsequent tampering tests."
            )
    else:
        ans_c = " ".join(c_parts) or "No detection methods executed."
        ans_c += " Reminder: Detector findings are indicators for human review, not proof of authenticity or forgery."

    total_ms = round((time.perf_counter() - t0) * 1000, 1)

    artifacts = {
        "original": f"/api/results/{experiment_id}/original.png",
        "baseline": f"/api/results/{experiment_id}/baseline.png",
        "modified": f"/api/results/{experiment_id}/modified.png",
        "report_json": f"/api/results/{experiment_id}/experiment_report.json",
        "report_html": f"/api/results/{experiment_id}/experiment_report.html",
    }
    if gt_bytes:
        artifacts["ground_truth"] = f"/api/results/{experiment_id}/ground_truth.png"

    # Store report artifacts
    answers_dict = {"question_a": ans_a, "question_b": ans_b, "question_c": ans_c}
    report_dict = lab.build_experiment_report({
        "experiment_id": experiment_id,
        "original_image": meta.get("original_image", {}),
        "baseline": base_info,
        "baseline_image": base_info,
        "history": hist,
        "ground_truth": meta.get("ground_truth", {}),
        "detection_results": detection_results,
        "watermark_verification": wm_result,
        "evaluation": [e.model_dump() for e in eval_list],
        "answers": answers_dict,
        "artifacts": artifacts,
        "processing_ms": total_ms,
        "is_baseline_only": is_baseline_only,
    })

    # Prepare HTML report images
    html_images: dict[str, bytes] = {
        "original.png": store.get(experiment_id, "original.png") or b"",
        "baseline.png": store.get(experiment_id, "baseline.png") or b"",
        "modified.png": mod_bytes,
    }
    if gt_bytes:
        html_images["ground_truth.png"] = gt_bytes
    if "copy_move.annotated" in detector_files:
        html_images["copy_move.annotated"] = detector_files["copy_move.annotated"]
    if "splicing.overlay" in detector_files:
        html_images["splicing.overlay"] = detector_files["splicing.overlay"]

    detector_files["experiment_report.json"] = json.dumps(report_dict, indent=2).encode("utf-8")
    detector_files["experiment_report.html"] = lab.report_html_bytes(report_dict, html_images)

    meta["detection_results"] = detection_results
    meta["watermark_verification"] = wm_result
    meta["evaluation"] = [e.model_dump() for e in eval_list]
    meta["answers"] = answers_dict
    _save_meta(experiment_id, meta, detector_files)

    return ExperimentAnalysisResponse(
        experiment_id=experiment_id,
        image=ExperimentImageInfo(width=mod_rgb.shape[1], height=mod_rgb.shape[0], format="PNG"),
        baseline=BaselineInfo(**base_info),
        history=[TransformationStep(**s) for s in hist],
        ground_truth=GroundTruthInfo(**meta.get("ground_truth", {})),
        detection_results=detection_results,
        watermark_verification=wm_result,
        evaluation=eval_list,
        answers=answers_dict,
        artifacts=artifacts,
        report_json=artifacts["report_json"],
        report_html=artifacts["report_html"],
        processing_ms=total_ms,
        warnings=[],
        disclaimer=lab.ATTACK_LAB_DISCLAIMER,
    )


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str) -> dict[str, Any]:
    meta = _get_meta(experiment_id)
    return meta


@router.get("/experiments/{experiment_id}/report")
def get_experiment_report(experiment_id: str, format: Annotated[str, Query()] = "json") -> Response:
    fmt = format.lower()
    if fmt not in ("json", "html"):
        raise ApiError(422, "invalid_parameters", "format must be 'json' or 'html'.")
    if fmt == "html":
        content = store.get(experiment_id, "experiment_report.html")
        if content is None:
            raise ApiError(404, "not_found", "HTML report not found. Run analysis first.")
        return Response(
            content=content,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="attack-lab-report-{experiment_id}.html"',
                "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'",
            },
        )
    content = store.get(experiment_id, "experiment_report.json")
    if content is None:
        raise ApiError(404, "not_found", "JSON report not found. Run analysis first.")
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="attack-lab-report-{experiment_id}.json"',
        },
    )
