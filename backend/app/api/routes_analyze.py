import logging
from typing import Annotated

import numpy as np
from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from PIL import Image

from app.api.deps import job_slot, store
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.analysis import AnalysisResponse, MethodResult
from app.services import copy_move_service as cm
from app.services import image_service as imgs
from app.services import localization_service as loc
from app.services import report_service
from app.services import splicing_service as sp
from app.services.artifact_store import ArtifactStore
from app.services.forensics_common import heatmap_overlay, mask_overlay, red_layer_png, score_png16

router = APIRouter()
settings = get_settings()
log = logging.getLogger("imageguard")
METHODS = ("copy_move", "splicing", "localization")
MIN_AREA_FRACTION = {"splicing": 0.002, "localization": 0.0005}


def parse_methods(raw: str) -> list[str]:
    items = [m.strip() for m in raw.split(",") if m.strip()] or ["copy_move"]
    if "all_supported" in items:
        return list(METHODS)
    bad = [m for m in items if m not in METHODS]
    if bad:
        raise ApiError(422, "invalid_parameters", f"methods must be from: {', '.join(METHODS)}, all_supported (got {bad[0]!r}).")
    return [m for m in METHODS if m in items]


def _urls(aid: str, method: str, names: list[str]) -> dict[str, str]:
    return {n: f"/api/results/{aid}/{method}.{n}" for n in names}


def _run_copy_move(rgb, aid, params, files) -> MethodResult:
    out = cm.detect_copy_move(rgb, params)
    files["copy_move.annotated"] = imgs.encode_png_array(out.annotated)
    files["copy_move.mask"] = imgs.encode_png_array(out.mask)
    files["copy_move.heatmap"] = imgs.encode_png_array(out.heatmap)
    return MethodResult(
        method="copy_move", category="copy_move", evidence_type="feature_match_regions", status=out.status,
        status_reason=out.status_reason, method_name=cm.METHOD_NAME, method_version=cm.METHOD_VERSION, experimental=False,
        region_count=len(out.regions), regions=[r.__dict__ for r in out.regions], processing_ms=out.processing_ms,
        metrics={"keypoints": out.keypoints, "matches_before_filtering": out.matches_before_filtering,
                 "matches_after_descriptor_filtering": out.matches_after_descriptor_filtering,
                 "matches_retained": out.matches_retained, "analysis_scale": round(out.scale, 4), "settings": out.settings},
        artifacts=_urls(aid, "copy_move", ["annotated", "mask", "heatmap"]), warnings=out.warnings, limitations=cm.LIMITATIONS)


def _map_result(method, out, rgb, aid, files, *, name, version, experimental, evidence, category, limitations, model=None) -> MethodResult:
    names = []
    if out.score is not None:
        files[f"{method}.heatmap"] = imgs.encode_png_array(heatmap_overlay(rgb, out.score))
        files[f"{method}.score"] = score_png16(out.score)
        names += ["heatmap", "score"]
    if out.mask is not None:
        files[f"{method}.mask"] = imgs.encode_png_array(out.mask)
        files[f"{method}.overlay"] = imgs.encode_png_array(mask_overlay(rgb, out.mask))
        names += ["mask", "overlay"]
    metrics = dict(out.metrics)
    return MethodResult(
        method=method, category=category, evidence_type=evidence, status=out.status, status_reason=out.status_reason,
        method_name=name, method_version=version, experimental=experimental, model=model or metrics.pop("model", None),
        threshold=out.threshold, threshold_semantics=metrics.pop("threshold_semantics", None), region_count=len(out.regions),
        regions=out.regions, metrics=metrics, processing_ms=out.processing_ms, artifacts=_urls(aid, method, names),
        warnings=out.warnings, limitations=limitations)


def _unavailable(reason: str) -> MethodResult:
    return MethodResult(
        method="localization", category="local_manipulation", evidence_type="model_probability_map", status="unavailable",
        status_reason=reason, method_name=loc.METHOD_NAME, method_version=loc.METHOD_VERSION, experimental=False,
        limitations=loc.LIMITATIONS)


@router.post("/detect/analyze", response_model=AnalysisResponse)
def analyze(
    file: Annotated[UploadFile, File(description="JPEG or PNG image to analyse")],
    methods: Annotated[str, Form(description="Comma list: copy_move, splicing, localization, all_supported")] = "copy_move",
    splicing_threshold: Annotated[float, Form(ge=0.05, le=0.99)] = 0.5,
    localization_threshold: Annotated[float, Form(ge=0.01, le=0.99)] = 0.5,
    max_dimension: Annotated[int, Form(ge=256, le=3000)] = 1280,
    n_features: Annotated[int, Form(ge=500, le=20000)] = 5000,
    ratio: Annotated[float, Form(ge=0.5, le=0.95)] = 0.75,
    min_matches: Annotated[int, Form(ge=4, le=100)] = 8,
    min_displacement: Annotated[float, Form(ge=4, le=500)] = 24,
) -> AnalysisResponse:
    wanted = parse_methods(methods)
    data = imgs.read_upload(file, settings.max_upload_bytes, "image")
    dec = imgs.decode_image(data, max_pixels=settings.max_image_pixels, max_side=settings.max_image_side,
                            min_side=settings.min_image_side, label="image")
    del data
    img = dec.image
    if dec.has_alpha:
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    rgb = np.asarray(img.convert("RGB"))
    aid = ArtifactStore.new_id()
    files: dict[str, bytes] = {}
    results: list[MethodResult] = []
    cm_params = cm.CopyMoveParams(max_dimension=max_dimension, n_features=n_features, ratio=ratio, min_matches=min_matches,
                                  min_displacement=min_displacement)
    with job_slot():
        for m in wanted:
            try:
                if m == "copy_move":
                    results.append(_run_copy_move(rgb, aid, cm_params, files))
                elif m == "splicing":
                    out = sp.detect_splicing(rgb, dec.source_format == "JPEG", sp.SplicingParams(threshold=splicing_threshold))
                    results.append(_map_result("splicing", out, rgb, aid, files, name=sp.METHOD_NAME, version=sp.METHOD_VERSION,
                                               experimental=True, evidence="heuristic_forensic_map", category="splicing",
                                               limitations=sp.LIMITATIONS))
                else:
                    try:
                        out = loc.localize(rgb, settings, localization_threshold)
                    except loc.ModelUnavailable as e:
                        results.append(_unavailable(str(e)))
                        continue
                    results.append(_map_result("localization", out, rgb, aid, files, name=loc.METHOD_NAME, version=loc.METHOD_VERSION,
                                               experimental=False, evidence="model_probability_map", category="local_manipulation",
                                               limitations=loc.LIMITATIONS))
            except TimeoutError as e:
                results.append(MethodResult(method=m, category="local_manipulation", evidence_type="model_probability_map", status="failed",
                                            status_reason=str(e), method_name=loc.METHOD_NAME, method_version=loc.METHOD_VERSION,
                                            experimental=False))
            except Exception:  # isolate failures per method; never substitute mock output
                log.exception("method %s failed", m)
                cat = {"copy_move": "copy_move", "splicing": "splicing"}.get(m, "local_manipulation")
                ev = {"copy_move": "feature_match_regions", "splicing": "heuristic_forensic_map"}.get(m, "model_probability_map")
                results.append(MethodResult(method=m, category=cat, evidence_type=ev, status="failed",
                                            status_reason="The method failed while processing this image.", method_name=m,
                                            method_version="-", experimental=m == "splicing"))
    resp = {
        "analysis_id": aid, "image": {"width": rgb.shape[1], "height": rgb.shape[0], "source_format": dec.source_format},
        "requested_methods": wanted, "results": [r.model_dump() for r in results],
        "artifact_ttl_seconds": settings.artifact_ttl_seconds, "report_json": f"/api/results/{aid}/analysis.json",
    }
    report = report_service.build_analysis_report(resp, imgs.sanitize_stem(file.filename) if file.filename else None)
    files["analysis.json"] = report_service.report_json_bytes(report)
    store.put(aid, files)
    return AnalysisResponse(**resp, disclaimer=report["disclaimer"])


@router.get("/results/{analysis_id}/{method}/layer")
def threshold_layer(analysis_id: str, method: str, threshold: Annotated[float, Query(ge=0.01, le=0.99)] = 0.5) -> Response:
    """Re-apply a threshold to a stored score map; returns a transparent red PNG layer to draw over the original."""
    if method not in MIN_AREA_FRACTION:
        raise ApiError(404, "not_found", "Result not found or expired. Re-run the analysis.")
    score = store.get(analysis_id, f"{method}.score")
    if score is None:
        raise ApiError(404, "not_found", "Result not found or expired. Re-run the analysis.")
    h, w = np.asarray(Image.open(__import__("io").BytesIO(score))).shape[:2]
    png, n = red_layer_png(score, threshold, max(32, int(MIN_AREA_FRACTION[method] * h * w)))
    return Response(content=png, media_type="image/png",
                    headers={"X-Region-Count": str(n), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
