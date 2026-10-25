import time
from typing import Annotated

import numpy as np
from fastapi import APIRouter, File, Form, UploadFile
from PIL import Image

from app.api.deps import job_slot, store
from app.api.routes_capabilities import watermark_key_status
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.invisible import InvisibleEmbedResponse, InvisibleVerifyResponse
from app.services import image_service as imgs
from app.services import invisible_watermark_service as iw
from app.services.artifact_store import ArtifactStore

router = APIRouter(prefix="/watermark/invisible")
settings = get_settings()
ALGO = {"name": iw.ALGORITHM, "version": str(iw.VERSION)}


def _key() -> bytes:
    ok, why = watermark_key_status()
    if not ok:
        raise ApiError(503, "watermark_unavailable", f"Invisible watermarking is unavailable: {why}")
    return settings.watermark_key.get_secret_value().encode()  # type: ignore[union-attr]


def _load(file: UploadFile) -> tuple[np.ndarray, imgs.DecodedImage]:
    data = imgs.read_upload(file, settings.max_upload_bytes, "image")
    dec = imgs.decode_image(data, max_pixels=settings.max_image_pixels, max_side=settings.max_image_side,
                            min_side=settings.min_image_side, label="image")
    img = dec.image
    if dec.has_alpha:
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    return np.asarray(img.convert("RGB")), dec


@router.post("/embed", response_model=InvisibleEmbedResponse)
def embed(
    file: Annotated[UploadFile, File()],
    owner: Annotated[str, Form(min_length=1, max_length=12, description="Owner/identifier, 1-12 printable ASCII chars")],
    strength: Annotated[str, Form()] = "standard",
    output_format: Annotated[str, Form()] = "png",
) -> InvisibleEmbedResponse:
    key = _key()
    fmt = output_format.lower().replace("jpg", "jpeg")
    if fmt not in ("png", "jpeg"):
        raise ApiError(422, "invalid_parameters", "output_format must be 'png' or 'jpeg'.")
    rgb, dec = _load(file)
    if rgb.shape[0] * rgb.shape[1] < settings.watermark_min_pixels:
        raise ApiError(422, "image_too_small", "Image is too small for a reliable invisible watermark (about 256x256 pixels minimum).")
    try:
        with job_slot():
            res = iw.embed(rgb, owner, key, strength)
            body, _media, ext = imgs.encode_image(Image.fromarray(res.image), fmt)
    except iw.WatermarkError as e:
        raise ApiError(422, "invalid_parameters", str(e))
    wid = ArtifactStore.new_id()
    name = f"watermarked.{ext}"
    store.put(wid, {name: body})
    warnings = []
    if dec.has_alpha:
        warnings.append("Transparency was flattened on white.")
    if fmt == "jpeg":
        warnings.append("JPEG output is lossy; verify the downloaded file to confirm the watermark survived.")
    return InvisibleEmbedResponse(
        watermark_id=wid, algorithm=ALGO, owner=owner, integrity="HMAC-SHA256 truncated to 32 bits (server key)",
        metrics={"psnr_db": res.psnr_db, "blocks": res.blocks, "copies_per_bit": res.copies_per_bit, "quantization_step": res.delta},
        output_format=fmt, artifact=f"/api/results/{wid}/{name}", warnings=warnings, limitations=iw.LIMITATIONS)


@router.post("/verify", response_model=InvisibleVerifyResponse)
def verify(file: Annotated[UploadFile, File()]) -> InvisibleVerifyResponse:
    key = _key()
    rgb, dec = _load(file)
    t0 = time.perf_counter()
    try:
        with job_slot():
            r = iw.verify(rgb, key)
    except iw.WatermarkError as e:
        raise ApiError(422, "image_too_small", str(e))
    reason = {
        "verified": "A payload with a valid integrity check (HMAC) made with this server's key was recovered.",
        "inconclusive": "A watermark-like signal with a valid header was found, but its integrity check failed: it may be damaged, or made with a different key.",
        "not_detected": "No payload matching this server's key was found. The image may be unmarked, marked with another key, or the watermark may have been destroyed (e.g. by resizing).",
    }[r.status]
    warnings = []
    if dec.source_format == "JPEG":
        warnings.append("JPEG input: the watermark may be weakened by compression.")
    return InvisibleVerifyResponse(
        status=r.status, status_reason=reason, owner=r.owner, integrity_verified=r.integrity_verified, algorithm=ALGO,
        metrics={"bit_strength": r.bit_strength, "grid_offset": list(r.grid_offset) if r.grid_offset else None,
                 "class_shift": r.class_shift, "quantization_step": r.delta, "offsets_searched": r.offsets_searched},
        processing_ms=round((time.perf_counter() - t0) * 1000, 1), warnings=warnings, limitations=iw.LIMITATIONS)
