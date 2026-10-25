"""Safe image decoding, validation and encoding."""
import io
import re
import warnings
from dataclasses import dataclass

import numpy as np
from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import ApiError

ALLOWED_FORMATS = {"JPEG", "PNG"}
CHUNK = 1024 * 1024


@dataclass
class DecodedImage:
    image: Image.Image  # RGB or RGBA, EXIF-oriented
    has_alpha: bool
    source_format: str


def read_upload(upload: UploadFile, max_bytes: int, label: str = "image") -> bytes:
    """Read an upload in chunks, refusing anything larger than max_bytes."""
    buf = bytearray()
    while True:
        chunk = upload.file.read(CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise ApiError(413, "file_too_large", f"The {label} exceeds the {max_bytes // (1024 * 1024)} MB upload limit.")
    if not buf:
        raise ApiError(400, "empty_file", f"The {label} file is empty.")
    return bytes(buf)


def _to_8bit(img: Image.Image) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    top = 65535.0 if img.mode == "I;16" else max(float(arr.max()), 1.0)
    return Image.fromarray(np.clip(arr / top * 255.0, 0, 255).astype(np.uint8), "L")


def sanitize_stem(filename: str | None, default: str = "image") -> str:
    """Reduce a client filename to a safe ASCII stem (no path components, no extension)."""
    name = (filename or "").replace("\\", "/").split("/")[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")[:60]
    return stem or default


def decode_image(
    data: bytes,
    *,
    max_pixels: int,
    max_side: int,
    min_side: int = 1,
    label: str = "image",
) -> DecodedImage:
    """Decode JPEG/PNG bytes by content (not extension), with size and bomb guards."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            fmt = img.format
            if fmt not in ALLOWED_FORMATS:
                raise ApiError(415, "unsupported_format", f"The {label} must be a JPEG or PNG file.")
            w, h = img.size
            if w < min_side or h < min_side:
                raise ApiError(422, "image_too_small", f"The {label} must be at least {min_side}x{min_side} pixels.")
            if max(w, h) > max_side or w * h > max_pixels:
                raise ApiError(
                    413, "image_too_large",
                    f"The {label} is {w}x{h}; the limit is {max_side}px per side and {max_pixels / 1e6:.0f} megapixels.",
                )
            img.load()
    except ApiError:
        raise
    except Image.DecompressionBombError:
        raise ApiError(413, "image_too_large", f"The {label} is too large to process safely.")
    except Image.DecompressionBombWarning:
        raise ApiError(413, "image_too_large", f"The {label} is too large to process safely.")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
        raise ApiError(400, "invalid_image", f"The {label} could not be decoded. It may be corrupted or not a real JPEG/PNG.")

    try:
        img = ImageOps.exif_transpose(img)
        if img.mode in ("I", "I;16", "F"):
            img = _to_8bit(img)
        has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha else "RGB")
    except Exception:
        raise ApiError(400, "invalid_image", f"The {label} uses an unsupported color layout.")
    return DecodedImage(image=img, has_alpha=has_alpha, source_format=fmt)


def decode_to_rgb(
    data: bytes,
    *,
    max_pixels: int,
    max_side: int,
    min_side: int = 1,
    label: str = "image",
) -> tuple[np.ndarray, DecodedImage]:
    """Decode an upload, flatten alpha to white, and return (RGB uint8 ndarray, DecodedImage)."""
    dec = decode_image(data, max_pixels=max_pixels, max_side=max_side, min_side=min_side, label=label)
    img = dec.image
    if dec.has_alpha:
        flat = Image.new("RGB", img.size, (255, 255, 255))
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    rgb = np.asarray(img.convert("RGB"))
    return rgb, dec


def encode_image(img: Image.Image, fmt: str) -> tuple[bytes, str, str]:
    """Encode to PNG or JPEG. Returns (bytes, media_type, extension)."""
    buf = io.BytesIO()
    if fmt == "jpeg":
        if img.mode == "RGBA":
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.getchannel("A"))
            img = flat
        img.convert("RGB").save(buf, "JPEG", quality=92, optimize=True)
        return buf.getvalue(), "image/jpeg", "jpg"
    img.save(buf, "PNG", optimize=False, compress_level=6)
    return buf.getvalue(), "image/png", "png"


def encode_png_array(arr: np.ndarray) -> bytes:
    """Encode an HxW (gray) or HxWx3 (RGB) uint8 array as PNG."""
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG", compress_level=6)
    return buf.getvalue()
