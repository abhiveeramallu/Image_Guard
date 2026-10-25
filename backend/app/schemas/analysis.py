from typing import Literal

from pydantic import BaseModel

MethodId = Literal["copy_move", "splicing", "localization"]
MethodStatus = Literal[
    "candidate_regions_found", "no_candidate_regions_found", "inconclusive", "unavailable", "failed"
]


class MethodResult(BaseModel):
    method: MethodId
    category: Literal["copy_move", "splicing", "local_manipulation"]
    evidence_type: Literal["feature_match_regions", "heuristic_forensic_map", "model_probability_map"]
    status: MethodStatus
    status_reason: str
    method_name: str
    method_version: str
    experimental: bool
    model: dict | None = None
    threshold: float | None = None
    threshold_semantics: str | None = None
    region_count: int = 0
    regions: list[dict] = []
    metrics: dict = {}
    processing_ms: float = 0.0
    artifacts: dict[str, str] = {}
    warnings: list[str] = []
    limitations: list[str] = []


class AnalysisResponse(BaseModel):
    analysis_id: str
    image: dict
    requested_methods: list[MethodId]
    results: list[MethodResult]
    artifact_ttl_seconds: int
    report_json: str
    disclaimer: str


class MethodCapability(BaseModel):
    available: bool
    experimental: bool
    reason: str | None = None
    model: dict | None = None
    description: str


class Capabilities(BaseModel):
    version: str
    methods: dict[str, MethodCapability]
    invisible_watermark: MethodCapability
    limits: dict
