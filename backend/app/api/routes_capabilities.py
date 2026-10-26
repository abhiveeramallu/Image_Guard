from fastapi import APIRouter

from app.core.config import APP_VERSION, get_settings
from app.schemas.analysis import Capabilities, MethodCapability
from app.services import localization_service as loc

router = APIRouter()
settings = get_settings()


def watermark_key_status() -> tuple[bool, str | None]:
    s = get_settings()
    if not s.watermark_key or not s.watermark_key.get_secret_value():
        return False, "IMAGEGUARD_WATERMARK_KEY is not set on the server."
    val = s.watermark_key.get_secret_value().strip()
    if not val:
        return False, "IMAGEGUARD_WATERMARK_KEY is not set on the server."
    if len(val) < 8:
        return False, "IMAGEGUARD_WATERMARK_KEY is too short (minimum 8 characters required)."
    return True, None


@router.get("/capabilities", response_model=Capabilities)
def capabilities() -> Capabilities:
    s = get_settings()
    model = loc.manager.status(s)
    ok, why = watermark_key_status()
    return Capabilities(
        version=APP_VERSION,
        methods={
            "copy_move": MethodCapability(available=True, experimental=False,
                                          description="ORB feature matching + RANSAC; finds duplicated regions within one image."),
            "splicing": MethodCapability(available=True, experimental=True,
                                         description="Noise-residual / error-level heuristic for local inconsistencies. Not a trained or validated detector."),
            "localization": MethodCapability(available=model["available"], experimental=False, reason=model["reason"], model=model["model"],
                                             description="Pixel-level manipulation probability map from a configured ONNX model."),
        },
        invisible_watermark=MethodCapability(available=ok, experimental=False, reason=why,
                                             description="DCT-domain invisible watermark with HMAC integrity check."),
        limits={"max_upload_bytes": s.max_upload_bytes, "max_image_pixels": s.max_image_pixels,
                "artifact_ttl_seconds": s.artifact_ttl_seconds},
    )
