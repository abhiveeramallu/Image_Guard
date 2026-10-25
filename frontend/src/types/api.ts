export type DetectionStatus = 'candidate_regions_found' | 'no_candidate_regions_found' | 'inconclusive'

export interface BBox { x: number; y: number; width: number; height: number }
export interface RegionSide { bbox: BBox; polygon: number[][] }
export interface Transform {
  type: 'similarity'
  translation_x: number
  translation_y: number
  rotation_degrees: number
  scale: number
}
export interface CandidateRegion {
  id: number
  matches: number
  mean_hamming_distance: number
  transform: Transform
  region_a: RegionSide
  region_b: RegionSide
}

export interface DetectionResult {
  analysis_id: string
  status: DetectionStatus
  status_reason: string
  method: { name: string; version: string }
  image: { width: number; height: number; analysis_width: number; analysis_height: number; analysis_scale: number }
  keypoints: number
  matches_before_filtering: number
  matches_after_descriptor_filtering: number
  matches_retained: number
  candidate_region_count: number
  regions: CandidateRegion[]
  processing_ms: number
  settings: Record<string, number>
  artifacts: { annotated: string; mask: string; heatmap: string; report_json: string; report_html: string }
  artifact_ttl_seconds: number
  warnings: string[]
  limitations: string[]
}

export interface DetectionSettings {
  max_dimension: number
  n_features: number
  ratio: number
  min_matches: number
  min_displacement: number
}

export const DEFAULT_DETECTION_SETTINGS: DetectionSettings = {
  max_dimension: 1280,
  n_features: 5000,
  ratio: 0.75,
  min_matches: 8,
  min_displacement: 24,
}

export type WatermarkPosition =
  | 'top-left' | 'top-center' | 'top-right'
  | 'middle-left' | 'center' | 'middle-right'
  | 'bottom-left' | 'bottom-center' | 'bottom-right'

export interface WatermarkSettings {
  watermark_type: 'text' | 'logo'
  text: string
  position: WatermarkPosition
  opacity: number
  font_size: number
  color: string
  rotation: number
  margin: number
  layout: 'single' | 'tiled'
  output_format: 'png' | 'jpeg'
  outline: boolean
  shadow: boolean
  logo_scale: number
  tile_spacing: number
}

export const DEFAULT_WATERMARK_SETTINGS: WatermarkSettings = {
  watermark_type: 'text',
  text: 'ImageGuard',
  position: 'bottom-right',
  opacity: 0.6,
  font_size: 36,
  color: '#ffffff',
  rotation: 0,
  margin: 24,
  layout: 'single',
  output_format: 'png',
  outline: true,
  shadow: false,
  logo_scale: 20,
  tile_spacing: 60,
}

export interface WatermarkResult { blob: Blob; filename: string }

// ---- multi-method analysis -------------------------------------------------------------
export type MethodId = 'copy_move' | 'splicing' | 'localization'
export type MethodStatus =
  | 'candidate_regions_found' | 'no_candidate_regions_found' | 'inconclusive' | 'unavailable' | 'failed'

export interface MethodResult {
  method: MethodId
  category: 'copy_move' | 'splicing' | 'local_manipulation'
  evidence_type: 'feature_match_regions' | 'heuristic_forensic_map' | 'model_probability_map'
  status: MethodStatus
  status_reason: string
  method_name: string
  method_version: string
  experimental: boolean
  model: ModelInfo | null
  threshold: number | null
  threshold_semantics: string | null
  region_count: number
  regions: Record<string, unknown>[]
  metrics: Record<string, unknown>
  processing_ms: number
  artifacts: Record<string, string>
  warnings: string[]
  limitations: string[]
}

export interface ModelInfo {
  id: string
  name: string
  version: string
  source: string
  license: string
  intended_use: string | null
  output_semantics: string
  provider: string
}

export interface AnalysisResult {
  analysis_id: string
  image: { width: number; height: number; source_format: string }
  requested_methods: MethodId[]
  results: MethodResult[]
  artifact_ttl_seconds: number
  report_json: string
  disclaimer: string
}

export interface MethodCapability {
  available: boolean
  experimental: boolean
  reason: string | null
  model: ModelInfo | null
  description: string
}

export interface Capabilities {
  version: string
  methods: Record<MethodId, MethodCapability>
  invisible_watermark: MethodCapability
  limits: Record<string, number>
}

export interface AnalyzeSettings extends DetectionSettings {
  splicing_threshold: number
  localization_threshold?: number
}

// ---- invisible watermark -----------------------------------------------------------------
export type InvisibleStrength = 'low' | 'standard' | 'high'

export interface InvisibleEmbedResult {
  watermark_id: string
  algorithm: { name: string; version: string }
  owner: string
  integrity: string
  metrics: { psnr_db: number; blocks: number; copies_per_bit: number; quantization_step: number }
  output_format: 'png' | 'jpeg'
  artifact: string
  warnings: string[]
  limitations: string[]
}

export interface InvisibleVerifyResult {
  status: 'verified' | 'inconclusive' | 'not_detected'
  status_reason: string
  owner: string | null
  integrity_verified: boolean
  algorithm: { name: string; version: string }
  metrics: Record<string, unknown>
  processing_ms: number
  warnings: string[]
  limitations: string[]
}

