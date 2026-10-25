from typing import Literal

from pydantic import BaseModel


class InvisibleEmbedResponse(BaseModel):
    watermark_id: str
    algorithm: dict
    owner: str
    integrity: str
    metrics: dict
    output_format: Literal["png", "jpeg"]
    artifact: str
    warnings: list[str]
    limitations: list[str]


class InvisibleVerifyResponse(BaseModel):
    status: Literal["verified", "inconclusive", "not_detected"]
    status_reason: str
    owner: str | None
    integrity_verified: bool
    algorithm: dict
    metrics: dict
    processing_ms: float
    warnings: list[str]
    limitations: list[str]
