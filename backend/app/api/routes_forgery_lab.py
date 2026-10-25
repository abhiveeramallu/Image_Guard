"""Manual Forgery Lab API: Interactive image editing and independent forensic detection.

Workflow:
1. Receives client-edited image (with optional original image and optional ground-truth mask).
2. Runs requested detectors independently on the modified pixels without leaking ground truth.
3. If ground-truth mask is provided, evaluates detection metrics (TP, FP, FN, precision, recall, F1, IoU).
4. Stores artifacts in the ephemeral store and returns structured results and downloadable reports.
"""
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
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.attack_lab import (
    BaselineInfo,
    EvaluationMetrics,
    ExperimentAnalysisResponse,
    ExperimentImageInfo,
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
from app.services.forensics_common import heatmap_overlay, mask_overlay, score_png16
from app.api.routes_capabilities import watermark_key_status

router = APIRouter(prefix="/forgery-lab", tags=["forgery-lab"])
settings = get_settings()
log = logging.getLogger("imageguard.forgery_lab")


@router.post("/analyze", response_model=ExperimentAnalysisResponse)
def analyze_manual_forgery(
    file: Annotated[UploadFile, File(description="Edited / working image from canvas")],
    original_file: Annotated[UploadFile | None, File(description="Optional unedited original image")] = None,
    ground_truth_file: Annotated[UploadFile | None, File(description="Optional ground truth manipulation mask")] = None,
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

    # 1. Decode edited image
    mod_data = imgs.read_upload(file, settings.max_upload_bytes, "modified image")
    mod_rgb, mod_dec = imgs.decode_to_rgb(
        mod_data,
        max_pixels=settings.max_image_pixels,
        max_side=settings.max_image_side,
        min_side=settings.min_image_side,
        label="modified image",
    )
    H, W = mod_rgb.shape[:2]

    # 2. Decode original image if provided
    orig_rgb: np.ndarray | None = None
    orig_bytes: bytes | None = None
    if original_file and original_file.filename:
        orig_data = imgs.read_upload(original_file, settings.max_upload_bytes, "original image")
        orig_rgb, _ = imgs.decode_to_rgb(
            orig_data,
            max_pixels=settings.max_image_pixels,
            max_side=settings.max_image_side,
            min_side=settings.min_image_side,
            label="original image",
        )
        orig_bytes = imgs.encode_png_array(orig_rgb)

    # 3. Decode ground truth mask if provided
    gt_mask: np.ndarray | None = None
    gt_bytes: bytes | None = None
    if ground_truth_file and ground_truth_file.filename:
        try:
            gt_data = imgs.read_upload(ground_truth_file, settings.max_upload_bytes, "ground truth mask")
            pil_gt = Image.open(io.BytesIO(gt_data)).convert("L")
            gt_mask = np.asarray(pil_gt)
            if gt_mask.shape != (H, W):
                raise ApiError(400, "dimension_mismatch", f"Ground-truth mask dimensions {gt_mask.shape} do not match image dimensions {(H, W)}.")
            # Threshold to clean binary
            gt_mask = np.where(gt_mask > 127, 255, 0).astype(np.uint8)
            if (gt_mask > 0).sum() > 0:
                gt_bytes = imgs.encode_png_array(gt_mask)
        except ApiError:
            raise
        except Exception as e:
            log.warning("Failed to decode ground truth mask: %s", e)

    # Validate methods
    valid_methods = {"copy_move", "splicing", "localization", "watermark_verify"}
    wanted = [m.strip() for m in methods.split(",") if m.strip()]
    if not wanted:
        raise ApiError(422, "invalid_parameters", "At least one detection or verification method must be specified.")
    bad_methods = [m for m in wanted if m not in valid_methods]
    if bad_methods:
        raise ApiError(422, "invalid_parameters", f"Unknown method(s): {', '.join(bad_methods)}.")

    analysis_id = store.new_id()
    detector_files: dict[str, bytes] = {
        "modified.png": imgs.encode_png_array(mod_rgb),
    }
    if orig_bytes is not None:
        detector_files["original.png"] = orig_bytes
        detector_files["baseline.png"] = orig_bytes
    else:
        detector_files["original.png"] = detector_files["modified.png"]
        detector_files["baseline.png"] = detector_files["modified.png"]

    if gt_bytes is not None:
        detector_files["ground_truth.png"] = gt_bytes

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
                    "Manual Forgery Lab copy-move: aid=%s, status=%s, keypoints=%d, retained=%d, regions=%d",
                    analysis_id, cm_out.status, cm_out.keypoints, cm_out.matches_retained, len(cm_out.regions)
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
                        "retained_matches": cm_out.matches_retained,
                        "accepted_clusters": len(cm_out.regions),
                        "rejected_clusters": getattr(cm_out, "rejected_clusters", 0),
                    },
                    "artifacts": {
                        "annotated": f"/api/results/{analysis_id}/copy_move.annotated",
                        "mask": f"/api/results/{analysis_id}/copy_move.mask",
                        "heatmap": f"/api/results/{analysis_id}/copy_move.heatmap",
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
                sp_out = sp.detect_splicing(mod_rgb, mod_dec.source_format == "JPEG", sp.SplicingParams(threshold=splicing_threshold))
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
                    "artifacts": {n: f"/api/results/{analysis_id}/splicing.{n}" for n in names},
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

        # 3. Model Localization
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
                    "artifacts": {n: f"/api/results/{analysis_id}/localization.{n}" for n in names},
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
                        "inconclusive": "A watermark pattern was found but HMAC integrity check failed.",
                        "not_detected": "No watermark matching the server key was found.",
                    }
                    wm_result = {
                        "status": vr.status,
                        "status_reason": reason_map.get(vr.status, "Watermark scan completed."),
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

    # Evaluate against Ground Truth if provided
    eval_list: list[MethodEvaluation] = []
    tampered_pixels = int((gt_mask > 0).sum()) if gt_mask is not None else 0
    is_unmodified = (tampered_pixels == 0) and (orig_rgb is not None and np.array_equal(orig_rgb, mod_rgb))

    if gt_mask is not None and tampered_pixels > 0:
        for m_name, p_mask in pred_masks.items():
            eval_metrics = lab.evaluate_detection(gt_mask, p_mask, m_name)
            if eval_metrics:
                eval_list.append(MethodEvaluation(
                    method=m_name,
                    metrics=EvaluationMetrics(**eval_metrics),
                    notes=eval_metrics.get("semantics_note", ""),
                ))
    elif is_unmodified:
        clean_gt = np.zeros((H, W), dtype=np.uint8)
        for m_name, p_mask in pred_masks.items():
            eval_metrics = lab.evaluate_detection(clean_gt, p_mask, m_name)
            if eval_metrics:
                eval_list.append(MethodEvaluation(
                    method=m_name,
                    metrics=EvaluationMetrics(**eval_metrics),
                    notes="Unmodified input evaluation: 0 ground-truth edited pixels. Flagged candidate pixels represent false positives on clean input.",
                ))

    # Answers (A, B, C)
    if tampered_pixels > 0:
        ans_a = f"Yes. User applied manual edits to the image ({tampered_pixels:,} pixels tracked in ground truth)."
    elif is_unmodified:
        ans_a = "No modifications detected. The analyzed image is identical to the original."
    else:
        ans_a = "Manual edit status: Image submitted for independent forensic review."

    # Question B
    b_parts: list[str] = []
    if wm_result:
        if wm_result["status"] == "verified":
            b_parts.append(f"Watermark verified: owner '{wm_result.get('owner') or 'N/A'}' payload recovered.")
        elif wm_result["status"] == "inconclusive":
            b_parts.append("Watermark pattern detected but HMAC integrity check failed (damaged or altered payload).")
        else:
            b_parts.append(f"Watermark status: '{wm_result['status']}'. {wm_result.get('status_reason', '')}")
    else:
        b_parts.append("Watermark verification was not requested in this analysis.")
    ans_b = " ".join(b_parts)

    # Question C
    c_parts: list[str] = []
    has_candidates = any(d.get("region_count", 0) > 0 for d in detection_results)
    for d in detection_results:
        m = d.get("method")
        s = d.get("status")
        regs = d.get("region_count", 0)
        c_parts.append(f"[{m}] Status '{s}' with {regs} candidate region(s).")

    if is_unmodified:
        if has_candidates:
            ans_c = (
                "Unmodified input findings: " + " ".join(c_parts) +
                " Note: Because no edits were made, any candidate regions detected above represent natural image features, "
                "repeated scene structures, or heuristic false positives—not tampering."
            )
        else:
            ans_c = "Clean input: No candidate regions were detected on the unmodified image. " + " ".join(c_parts)
    else:
        ans_c = " ".join(c_parts) or "No detection methods executed."
        ans_c += " Reminder: Detector findings are indicators for human review, not proof of authenticity or forgery."

    total_ms = round((time.perf_counter() - t0) * 1000, 1)

    artifacts = {
        "original": f"/api/results/{analysis_id}/original.png",
        "baseline": f"/api/results/{analysis_id}/baseline.png",
        "modified": f"/api/results/{analysis_id}/modified.png",
        "report_json": f"/api/results/{analysis_id}/experiment_report.json",
        "report_html": f"/api/results/{analysis_id}/experiment_report.html",
    }
    if gt_bytes:
        artifacts["ground_truth"] = f"/api/results/{analysis_id}/ground_truth.png"

    answers_dict = {"question_a": ans_a, "question_b": ans_b, "question_c": ans_c}

    # Build report dict
    report_dict = lab.build_experiment_report({
        "experiment_id": analysis_id,
        "title": "Manual Forgery Lab Analysis Report",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "original_image": {"width": orig_rgb.shape[1] if orig_rgb is not None else W, "height": orig_rgb.shape[0] if orig_rgb is not None else H, "format": "PNG"},
        "baseline": {"width": W, "height": H, "format": "PNG", "has_visible_watermark": False, "has_invisible_watermark": bool(wm_result and wm_result.get("status") == "verified")},
        "history": [{"step": 1, "transformation": "manual_edits", "description": f"Manual editing on canvas ({tampered_pixels:,} px)", "output_size": [W, H]}] if tampered_pixels > 0 else [],
        "ground_truth": {"has_mask": bool(gt_bytes), "tampered_pixels": tampered_pixels, "regions": [{"type": "manual_edit", "pixels": tampered_pixels}] if tampered_pixels > 0 else []},
        "detection_results": detection_results,
        "watermark_verification": wm_result,
        "evaluation": [e.model_dump() for e in eval_list],
        "answers": answers_dict,
        "artifacts": artifacts,
        "processing_ms": total_ms,
        "is_baseline_only": is_unmodified,
    })

    # Prepare HTML images
    html_images: dict[str, bytes] = {
        "original.png": detector_files["original.png"],
        "baseline.png": detector_files["baseline.png"],
        "modified.png": detector_files["modified.png"],
    }
    if gt_bytes:
        html_images["ground_truth.png"] = gt_bytes
    if "copy_move.annotated" in detector_files:
        html_images["copy_move.annotated"] = detector_files["copy_move.annotated"]
    if "splicing.overlay" in detector_files:
        html_images["splicing.overlay"] = detector_files["splicing.overlay"]
    if "localization.overlay" in detector_files:
        html_images["localization.overlay"] = detector_files["localization.overlay"]

    detector_files["experiment_report.json"] = json.dumps(report_dict, indent=2).encode("utf-8")
    detector_files["experiment_report.html"] = lab.report_html_bytes(report_dict, html_images)
    detector_files["analysis.json"] = json.dumps(report_dict, indent=2).encode("utf-8")

    # Save to store
    store.put(analysis_id, detector_files)

    return ExperimentAnalysisResponse(
        experiment_id=analysis_id,
        image=ExperimentImageInfo(width=W, height=H, format="PNG"),
        baseline=BaselineInfo(width=W, height=H, format="PNG", has_visible_watermark=False, has_invisible_watermark=bool(wm_result and wm_result.get("status") == "verified")),
        history=[TransformationStep(step=1, transformation="manual_edits", params={}, description=f"Manual canvas edits ({tampered_pixels} px)", timestamp=datetime.now(timezone.utc).isoformat(), output_size=[W, H])] if tampered_pixels > 0 else [],
        ground_truth=GroundTruthInfo(has_mask=bool(gt_bytes), regions=[], notes="Manual canvas ground truth."),
        detection_results=detection_results,
        watermark_verification=wm_result,
        evaluation=eval_list,
        answers=answers_dict,
        artifacts=artifacts,
        report_json=artifacts["report_json"],
        report_html=artifacts["report_html"],
        processing_ms=total_ms,
        is_baseline_only=is_unmodified,
        warnings=[],
        disclaimer=lab.ATTACK_LAB_DISCLAIMER,
    )


@router.get("/reports/{analysis_id}")
def get_forgery_lab_report(analysis_id: str, format: Annotated[str, Query()] = "json") -> Response:
    fmt = format.lower()
    if fmt not in ("json", "html"):
        raise ApiError(422, "invalid_parameters", "format must be 'json' or 'html'.")
    if fmt == "html":
        content = store.get(analysis_id, "experiment_report.html")
        if content is None:
            raise ApiError(404, "not_found", "HTML report not found. Run analysis first.")
        return Response(
            content=content,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="forgery-lab-report-{analysis_id}.html"',
                "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'",
            },
        )
    content = store.get(analysis_id, "experiment_report.json")
    if content is None:
        raise ApiError(404, "not_found", "JSON report not found. Run analysis first.")
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="forgery-lab-report-{analysis_id}.json"',
        },
    )


@router.get("/artifacts/{analysis_id}/{filename}")
def get_forgery_lab_artifact(analysis_id: str, filename: str) -> Response:
    content = store.get(analysis_id, filename)
    if content is None and filename.endswith(".png"):
        content = store.get(analysis_id, filename[:-4])
    if content is None:
        content = store.get(analysis_id, filename + ".png")
    if content is None:
        raise ApiError(404, "not_found", f"Artifact '{filename}' not found for analysis '{analysis_id}'.")
    media_type = "image/png"
    if filename.endswith(".json"):
        media_type = "application/json"
    elif filename.endswith(".html"):
        media_type = "text/html; charset=utf-8"
    return Response(content=content, media_type=media_type)
