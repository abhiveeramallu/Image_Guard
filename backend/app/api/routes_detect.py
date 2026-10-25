from typing import Annotated

import numpy as np
from fastapi import APIRouter, File, Form, Response, UploadFile

from app.api.deps import job_slot, store
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.detection import DetectionResponse
from app.services import image_service as imgs
from app.services import report_service
from app.services.artifact_store import artifact_media
from app.services.copy_move_service import (
    LIMITATIONS, METHOD_NAME, METHOD_VERSION, CopyMoveParams, detect_copy_move,
)

router = APIRouter()
settings = get_settings()


@router.post("/detect/copy-move", response_model=DetectionResponse)
def detect(
    file: Annotated[UploadFile, File(description="JPEG or PNG image to analyse")],
    max_dimension: Annotated[int, Form(ge=256, le=3000)] = 1280,
    n_features: Annotated[int, Form(ge=500, le=20000)] = 5000,
    ratio: Annotated[float, Form(ge=0.5, le=0.95)] = 0.75,
    max_hamming: Annotated[int, Form(ge=10, le=128)] = 64,
    min_displacement: Annotated[float, Form(ge=4, le=500)] = 24,
    min_matches: Annotated[int, Form(ge=4, le=100)] = 8,
    ransac_threshold: Annotated[float, Form(ge=1, le=10)] = 3.0,
    max_regions: Annotated[int, Form(ge=1, le=10)] = 5,
) -> DetectionResponse:
    data = imgs.read_upload(file, settings.max_upload_bytes, "image")
    decoded = imgs.decode_image(data, max_pixels=settings.max_image_pixels, max_side=settings.max_image_side,
                                min_side=settings.min_image_side, label="image")
    img = decoded.image
    if decoded.has_alpha:  # flatten transparency on white for analysis
        from PIL import Image
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    rgb = np.asarray(img.convert("RGB"))
    del data

    params = CopyMoveParams(
        max_dimension=max_dimension, n_features=n_features, ratio=ratio, max_hamming=max_hamming,
        min_displacement=min_displacement, min_matches=min_matches, ransac_threshold=ransac_threshold,
        max_regions=max_regions,
    )
    with job_slot():
        out = detect_copy_move(rgb, params)
        encoded = {
            "annotated": imgs.encode_png_array(out.annotated),
            "mask": imgs.encode_png_array(out.mask),
            "heatmap": imgs.encode_png_array(out.heatmap),
        }

    aid = store.new_id()
    base_url = f"/api/results/{aid}"
    warnings = list(out.warnings)
    if decoded.has_alpha:
        warnings.append("The image has transparency; it was flattened on a white background for analysis.")
    result = {
        "analysis_id": aid,
        "status": out.status,
        "status_reason": out.status_reason,
        "method": {"name": METHOD_NAME, "version": METHOD_VERSION},
        "image": {
            "width": out.original_size[0], "height": out.original_size[1],
            "analysis_width": out.analysis_size[0], "analysis_height": out.analysis_size[1],
            "analysis_scale": round(out.scale, 4),
        },
        "keypoints": out.keypoints,
        "matches_before_filtering": out.matches_before_filtering,
        "matches_after_descriptor_filtering": out.matches_after_descriptor_filtering,
        "matches_retained": out.matches_retained,
        "candidate_region_count": len(out.regions),
        "regions": [r.__dict__ for r in out.regions],
        "processing_ms": out.processing_ms,
        "settings": out.settings,
        "artifacts": {
            "annotated": f"{base_url}/annotated", "mask": f"{base_url}/mask", "heatmap": f"{base_url}/heatmap",
            "report_json": f"{base_url}/report.json", "report_html": f"{base_url}/report.html",
        },
        "artifact_ttl_seconds": settings.artifact_ttl_seconds,
        "warnings": warnings,
        "limitations": LIMITATIONS,
    }
    report = report_service.build_report(result, imgs.sanitize_stem(file.filename) if file.filename else None)
    encoded["report.json"] = report_service.report_json_bytes(report)
    encoded["report.html"] = report_service.report_html_bytes(report, encoded)
    store.put(aid, encoded)
    return DetectionResponse(**result)


@router.get("/results/{analysis_id}/{artifact_name}")
def get_artifact(analysis_id: str, artifact_name: str) -> Response:
    body = store.get(analysis_id, artifact_name)
    if body is None:
        raise ApiError(404, "not_found", "Result not found or expired. Re-run the analysis.")
    media, ext = artifact_media(artifact_name)  # type: ignore[misc]  # store.get() returned data, so the name is allow-listed
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if artifact_name.startswith("watermarked"):
        headers["Content-Disposition"] = f'attachment; filename="imageguard-watermarked.{ext}"'
    elif artifact_name.startswith("experiment_report"):
        headers["Content-Disposition"] = f'attachment; filename="imageguard-experiment-report.{ext}"'
    elif ext in ("json", "html"):
        headers["Content-Disposition"] = f'attachment; filename="imageguard-report.{ext}"'
    if ext == "html":
        headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    return Response(content=body, media_type=media, headers=headers)
