import os

os.environ.setdefault("IMAGEGUARD_RATE_LIMIT_PER_MINUTE", "0")  # tests post far more than 60 requests/min
os.environ["IMAGEGUARD_WATERMARK_KEY"] = ""  # tests assume no watermark key unless wm_key fixture is used
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from tests import synth


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


def to_bytes(arr_or_img, fmt="PNG", mode=None) -> bytes:
    img = arr_or_img if isinstance(arr_or_img, Image.Image) else Image.fromarray(arr_or_img)
    if mode:
        img = img.convert(mode)
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


@pytest.fixture
def photo():
    return synth.textured(640, 480, seed=3)


@pytest.fixture
def photo_png(photo):
    return to_bytes(photo, "PNG")


@pytest.fixture
def photo_jpg(photo):
    return to_bytes(photo, "JPEG")


def decode(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b))
