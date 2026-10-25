from typing import Literal

from pydantic import BaseModel


class BBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class RegionSide(BaseModel):
    bbox: BBox
    polygon: list[list[int]]


class Transform(BaseModel):
    type: Literal["similarity"]
    translation_x: float
    translation_y: float
    rotation_degrees: float
    scale: float


class CandidateRegion(BaseModel):
    id: int
    matches: int
    mean_hamming_distance: float
    transform: Transform
    region_a: RegionSide
    region_b: RegionSide


class Method(BaseModel):
    name: str
    version: str


class ImageInfo(BaseModel):
    width: int
    height: int
    analysis_width: int
    analysis_height: int
    analysis_scale: float


class Artifacts(BaseModel):
    annotated: str
    mask: str
    heatmap: str
    report_json: str
    report_html: str


class DetectionResponse(BaseModel):
    analysis_id: str
    status: Literal["candidate_regions_found", "no_candidate_regions_found", "inconclusive"]
    status_reason: str
    method: Method
    image: ImageInfo
    keypoints: int
    matches_before_filtering: int
    matches_after_descriptor_filtering: int
    matches_retained: int
    candidate_region_count: int
    regions: list[CandidateRegion]
    processing_ms: float
    settings: dict
    artifacts: Artifacts
    artifact_ttl_seconds: int
    warnings: list[str]
    limitations: list[str]
