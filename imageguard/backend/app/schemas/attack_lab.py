from typing import Any
from pydantic import BaseModel, Field


class ExperimentImageInfo(BaseModel):
    width: int
    height: int
    format: str
    size_bytes: int | None = None


class BaselineInfo(BaseModel):
    width: int
    height: int
    format: str
    has_visible_watermark: bool = False
    visible_watermark_text: str | None = None
    has_invisible_watermark: bool = False
    invisible_owner: str | None = None


class TransformationStep(BaseModel):
    step: int
    transformation: str
    params: dict[str, Any]
    description: str
    timestamp: str
    output_size: list[int]  # [width, height]


class GroundTruthInfo(BaseModel):
    has_mask: bool = False
    transformation: str | None = None
    regions: list[dict[str, Any]] = Field(default_factory=list)
    mask_artifact: str | None = None
    notes: str | None = None


class ExperimentPrepareResponse(BaseModel):
    experiment_id: str
    original_image: ExperimentImageInfo
    baseline_image: BaselineInfo
    artifacts: dict[str, str]
    history: list[TransformationStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExperimentTransformResponse(BaseModel):
    experiment_id: str
    transformation: str
    params: dict[str, Any]
    image: ExperimentImageInfo
    ground_truth: GroundTruthInfo
    artifacts: dict[str, str]
    history: list[TransformationStep]
    warnings: list[str] = Field(default_factory=list)


class EvaluationMetrics(BaseModel):
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    iou: float | None = None
    semantics_note: str


class MethodEvaluation(BaseModel):
    method: str
    metrics: EvaluationMetrics | None = None
    notes: str


class ExperimentAnalysisResponse(BaseModel):
    experiment_id: str
    image: ExperimentImageInfo
    baseline: BaselineInfo
    history: list[TransformationStep]
    ground_truth: GroundTruthInfo
    detection_results: list[dict[str, Any]]
    watermark_verification: dict[str, Any] | None = None
    evaluation: list[MethodEvaluation] = Field(default_factory=list)
    answers: dict[str, str]
    artifacts: dict[str, str]
    report_json: str
    report_html: str
    processing_ms: float
    is_baseline_only: bool = False
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str
