from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.api.deps import job_slot
from app.core.config import get_settings
from app.core.errors import ApiError
from app.services import image_service as imgs
from app.services.watermark_service import WatermarkOptions, apply_watermark, validate_options

router = APIRouter()
settings = get_settings()


@router.post("/watermark", responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}})
def watermark(
    file: Annotated[UploadFile, File(description="JPEG or PNG image to watermark")],
    watermark_type: Annotated[str, Form()] = "text",
    text: Annotated[str, Form()] = "",
    logo: Annotated[UploadFile | None, File(description="Logo (JPEG/PNG), required when watermark_type=logo")] = None,
    position: Annotated[str, Form()] = "bottom-right",
    opacity: Annotated[float, Form(ge=0, le=1)] = 0.5,
    font_size: Annotated[int, Form(ge=8, le=400)] = 36,
    color: Annotated[str, Form()] = "#FFFFFF",
    rotation: Annotated[float, Form(ge=-180, le=180)] = 0,
    margin: Annotated[int, Form(ge=0, le=500)] = 24,
    layout: Annotated[str, Form()] = "single",
    output_format: Annotated[str, Form()] = "png",
    outline: Annotated[bool, Form()] = True,
    shadow: Annotated[bool, Form()] = False,
    logo_scale: Annotated[float, Form(ge=2, le=100)] = 20,
    tile_spacing: Annotated[int, Form(ge=0, le=500)] = 60,
) -> Response:
    fmt = output_format.lower().replace("jpg", "jpeg")
    if fmt not in ("png", "jpeg"):
        raise ApiError(422, "invalid_parameters", "output_format must be 'png' or 'jpeg'.")
    opts = WatermarkOptions(
        watermark_type=watermark_type, text=text, position=position, opacity=opacity, font_size=font_size,
        color=color, rotation=rotation, margin=margin, layout=layout, outline=outline, shadow=shadow,
        logo_scale=logo_scale, tile_spacing=tile_spacing,
    )
    validate_options(opts)

    data = imgs.read_upload(file, settings.max_upload_bytes, "image")
    base = imgs.decode_image(data, max_pixels=settings.max_image_pixels, max_side=settings.max_image_side,
                             min_side=settings.min_image_side, label="image")
    logo_img = None
    if watermark_type == "logo":
        if logo is None or not logo.filename:
            raise ApiError(422, "invalid_parameters", "A logo file is required for logo watermarks.")
        logo_data = imgs.read_upload(logo, settings.max_logo_bytes, "logo")
        logo_img = imgs.decode_image(logo_data, max_pixels=settings.max_logo_pixels, max_side=4000, label="logo")

    with job_slot():
        result = apply_watermark(base, opts, logo_img)
        body, media, ext = imgs.encode_image(result, fmt)

    name = f"{imgs.sanitize_stem(file.filename)}_watermarked.{ext}"
    return Response(content=body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
