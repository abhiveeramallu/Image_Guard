from fastapi import APIRouter

from app.core.config import APP_VERSION, get_settings
from app.schemas.analysis import Capabilities, MethodCapability
from app.services import localization_service as loc

router = APIRouter()
settings = get_settings()


def watermark_key_status() -> tuple[bool, str | None]:
    if settings.watermark_key and settings.watermark_key.get_secret_value():
        return True, None
    return False, "IMAGEGUARD_WATERMARK_KEY is not set on the server."


@router.get("/capabilities", response_model=Capabilities)
def capabilities() -> Capabilities:
    model = loc.manager.status(settings)
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
        limits={"max_upload_bytes": settings.max_upload_bytes, "max_image_pixels": settings.max_image_pixels,
                "artifact_ttl_seconds": settings.artifact_ttl_seconds},
    )
