"""Visible text / logo watermarking with Pillow.

Pipeline: decode -> build a transparent RGBA "stamp" (text or logo, with opacity applied to
the alpha channel only) -> rotate the stamp -> alpha-composite it onto the image at one or
many positions (clipped to the image bounds) -> encode.
"""
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core.errors import ApiError
from app.services.image_service import DecodedImage

POSITIONS = (
    "top-left", "top-center", "top-right",
    "middle-left", "center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
)
MAX_STAMP_PIXELS = 16_000_000
MAX_TILES = 1500
MAX_TEXT_LENGTH = 200


@dataclass
class WatermarkOptions:
    watermark_type: str = "text"  # "text" | "logo"
    text: str = ""
    position: str = "bottom-right"
    opacity: float = 0.5  # 0..1
    font_size: int = 36  # pixels
    color: str = "#FFFFFF"
    rotation: float = 0.0  # degrees, counter-clockwise
    margin: int = 24
    layout: str = "single"  # "single" | "tiled"
    outline: bool = True
    shadow: bool = False
    logo_scale: float = 20.0  # logo width as % of image width
    tile_spacing: int = 60  # px between tiles


def parse_color(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        raise ApiError(422, "invalid_parameters", "color must be a hex value such as #FFFFFF.")
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        raise ApiError(422, "invalid_parameters", "color must be a hex value such as #FFFFFF.")


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)  # bundled font in Pillow >= 10.1


def _contrast_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return (0, 0, 0) if lum > 140 else (255, 255, 255)


def _text_stamp(opts: WatermarkOptions) -> Image.Image:
    rgb = parse_color(opts.color)
    font = _font(opts.font_size)
    stroke = max(1, opts.font_size // 14) if opts.outline else 0
    shadow_off = max(1, opts.font_size // 14) if opts.shadow else 0
    pad = stroke + shadow_off + 2

    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = probe.multiline_textbbox((0, 0), opts.text, font=font, stroke_width=stroke, align="center")
    w, h = int(r - l) + 2 * pad + shadow_off, int(b - t) + 2 * pad + shadow_off
    if w * h > MAX_STAMP_PIXELS:
        raise ApiError(422, "watermark_too_large", "The watermark text is too large. Reduce the text length or font size.")

    stamp = Image.new("RGBA", (w, h), rgb + (0,))  # same RGB everywhere avoids dark fringes when rotating
    d = ImageDraw.Draw(stamp)
    origin = (pad - l, pad - t)
    if opts.shadow:
        d.multiline_text((origin[0] + shadow_off, origin[1] + shadow_off), opts.text, font=font,
                         fill=(0, 0, 0, 150), stroke_width=stroke, stroke_fill=(0, 0, 0, 150), align="center")
    d.multiline_text(origin, opts.text, font=font, fill=rgb + (255,), stroke_width=stroke,
                     stroke_fill=_contrast_color(rgb) + (255,), align="center")
    return stamp


def _logo_stamp(logo: DecodedImage, base_size: tuple[int, int], opts: WatermarkOptions) -> Image.Image:
    img = logo.image.convert("RGBA")
    target_w = max(1, round(base_size[0] * opts.logo_scale / 100.0))
    target_h = max(1, round(img.height * target_w / img.width))
    if target_w * target_h > MAX_STAMP_PIXELS:
        raise ApiError(422, "watermark_too_large", "The scaled logo is too large. Reduce logo_scale.")
    # Premultiplied resize prevents dark/colored halos around transparent edges.
    arr = np.asarray(img).astype(np.float32)
    a = arr[..., 3:4] / 255.0
    pm = np.concatenate([arr[..., :3] * a, arr[..., 3:4]], axis=2)
    pm_img = [Image.fromarray(np.clip(pm[..., i], 0, 255).astype(np.uint8)).resize((target_w, target_h), Image.LANCZOS)
              for i in range(4)]
    out = np.stack([np.asarray(c).astype(np.float32) for c in pm_img], axis=2)
    alpha = out[..., 3:4]
    rgb = np.where(alpha > 0, out[..., :3] / np.maximum(alpha / 255.0, 1e-6), 0)
    res = np.concatenate([np.clip(rgb, 0, 255), alpha], axis=2).astype(np.uint8)
    return Image.fromarray(res, "RGBA")


def _apply_opacity(stamp: Image.Image, opacity: float) -> Image.Image:
    r, g, b, a = stamp.split()
    a = a.point(lambda v: int(round(v * opacity)))
    return Image.merge("RGBA", (r, g, b, a))


def _rotate(stamp: Image.Image, degrees: float) -> Image.Image:
    if abs(degrees) < 1e-6:
        return stamp
    rad = math.radians(degrees)
    nw = abs(stamp.width * math.cos(rad)) + abs(stamp.height * math.sin(rad))
    nh = abs(stamp.width * math.sin(rad)) + abs(stamp.height * math.cos(rad))
    if nw * nh > MAX_STAMP_PIXELS:
        raise ApiError(422, "watermark_too_large", "The rotated watermark is too large. Reduce size or rotation.")
    px = stamp.getpixel((0, 0))
    return stamp.rotate(degrees, expand=True, resample=Image.BICUBIC, fillcolor=(px[0], px[1], px[2], 0))


def _paste_clipped(base: Image.Image, stamp: Image.Image, x: int, y: int) -> None:
    """Alpha-composite stamp onto base in place, clipping to base bounds."""
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + stamp.width, base.width), min(y + stamp.height, base.height)
    if x0 >= x1 or y0 >= y1:
        return
    region = stamp.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    base.alpha_composite(region, dest=(x0, y0))


def _anchor(position: str, base: tuple[int, int], stamp: tuple[int, int], margin: int) -> tuple[int, int]:
    (bw, bh), (sw, sh) = base, stamp
    col, row = {
        "top-left": (0, 0), "top-center": (1, 0), "top-right": (2, 0),
        "middle-left": (0, 1), "center": (1, 1), "middle-right": (2, 1),
        "bottom-left": (0, 2), "bottom-center": (1, 2), "bottom-right": (2, 2),
    }[position]
    x = margin if col == 0 else (bw - sw) // 2 if col == 1 else bw - sw - margin
    y = margin if row == 0 else (bh - sh) // 2 if row == 1 else bh - sh - margin
    return x, y


def validate_options(opts: WatermarkOptions) -> None:
    def bad(msg: str):
        raise ApiError(422, "invalid_parameters", msg)

    if opts.watermark_type not in ("text", "logo"):
        bad("watermark_type must be 'text' or 'logo'.")
    if opts.position not in POSITIONS:
        bad(f"position must be one of: {', '.join(POSITIONS)}.")
    if opts.layout not in ("single", "tiled"):
        bad("layout must be 'single' or 'tiled'.")
    if not 0.0 <= opts.opacity <= 1.0:
        bad("opacity must be between 0 and 1.")
    if not 8 <= opts.font_size <= 400:
        bad("font_size must be between 8 and 400.")
    if not -180 <= opts.rotation <= 180:
        bad("rotation must be between -180 and 180 degrees.")
    if not 0 <= opts.margin <= 500:
        bad("margin must be between 0 and 500.")
    if not 2 <= opts.logo_scale <= 100:
        bad("logo_scale must be between 2 and 100 (percent of image width).")
    if not 0 <= opts.tile_spacing <= 500:
        bad("tile_spacing must be between 0 and 500.")
    if opts.watermark_type == "text":
        if not opts.text.strip():
            bad("text is required for text watermarks.")
        if len(opts.text) > MAX_TEXT_LENGTH:
            bad(f"text must be at most {MAX_TEXT_LENGTH} characters.")
        parse_color(opts.color)


def apply_watermark(base: DecodedImage, opts: WatermarkOptions, logo: DecodedImage | None = None) -> Image.Image:
    """Return a new RGBA image of identical dimensions with the watermark applied."""
    validate_options(opts)
    if opts.watermark_type == "logo":
        if logo is None:
            raise ApiError(422, "invalid_parameters", "A logo file is required for logo watermarks.")
        stamp = _logo_stamp(logo, base.image.size, opts)
    else:
        stamp = _text_stamp(opts)
    stamp = _rotate(_apply_opacity(stamp, opts.opacity), opts.rotation)

    canvas = base.image.convert("RGBA")  # convert() returns a copy; the input is untouched
    size = canvas.size
    if opts.layout == "single":
        x, y = _anchor(opts.position, size, stamp.size, opts.margin)
        _paste_clipped(canvas, stamp, x, y)
        return canvas

    sx, sy = stamp.width + opts.tile_spacing, stamp.height + opts.tile_spacing
    cols = math.ceil((size[0] + stamp.width) / sx) + 1
    rows = math.ceil((size[1] + stamp.height) / sy)
    if cols * rows > MAX_TILES:
        raise ApiError(422, "too_many_tiles",
                       f"This would create {cols * rows} tiles (limit {MAX_TILES}). Increase tile spacing or watermark size.")
    for r in range(rows):
        stagger = (sx // 2) if r % 2 else 0
        for c in range(cols):
            _paste_clipped(canvas, stamp, c * sx - stamp.width + stagger, r * sy - stamp.height // 2)
    return canvas
