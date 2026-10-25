import type { DetectionResult } from '../types/api'

export const png = (name = 'photo.png', size = 2048) => new File([new Uint8Array(size)], name, { type: 'image/png' })

export function detectionResult(over: Partial<DetectionResult> = {}): DetectionResult {
  return {
    analysis_id: 'abc',
    status: 'candidate_regions_found',
    status_reason: '1 cluster(s) of mutually consistent ORB matches were found (37 retained matches).',
    method: { name: 'orb-hamming-ransac', version: '1.0.0' },
    image: { width: 800, height: 600, analysis_width: 800, analysis_height: 600, analysis_scale: 1 },
    keypoints: 5000,
    matches_before_filtering: 4999,
    matches_after_descriptor_filtering: 51,
    matches_retained: 37,
    candidate_region_count: 1,
    regions: [{
      id: 1, matches: 37, mean_hamming_distance: 20,
      transform: { type: 'similarity', translation_x: 351, translation_y: 200, rotation_degrees: 0.1, scale: 1 },
      region_a: { bbox: { x: 92, y: 92, width: 129, height: 112 }, polygon: [[92, 92]] },
      region_b: { bbox: { x: 442, y: 292, width: 129, height: 111 }, polygon: [[442, 292]] },
    }],
    processing_ms: 199,
    settings: {},
    artifacts: { annotated: '/a', mask: '/m', heatmap: '/h', report_json: '/r.json', report_html: '/r.html' },
    artifact_ttl_seconds: 900,
    warnings: [],
    limitations: ['Only copy-move is analysed.'],
    ...over,
  }
}

import type { AnalysisResult, Capabilities, MethodResult } from '../types/api'

export function capabilities(over: Partial<Capabilities> = {}): Capabilities {
  return {
    version: '1.1.0',
    methods: {
      copy_move: { available: true, experimental: false, reason: null, model: null, description: 'ORB' },
      splicing: { available: true, experimental: true, reason: null, model: null, description: 'heuristic' },
      localization: { available: false, experimental: false, reason: 'No localization model is configured.', model: null, description: 'model' },
    },
    invisible_watermark: { available: true, experimental: false, reason: null, model: null, description: 'dct' },
    limits: {},
    ...over,
  }
}

export function methodResult(over: Partial<MethodResult> = {}): MethodResult {
  return {
    method: 'splicing', category: 'splicing', evidence_type: 'heuristic_forensic_map', status: 'candidate_regions_found',
    status_reason: '1 region(s) have noise statistics that differ.', method_name: 'noise-ela-heuristic', method_version: '0.1.0-experimental',
    experimental: true, model: null, threshold: 0.5, threshold_semantics: 'normalised heuristic score (not a probability)',
    region_count: 1, regions: [{ id: 1, area_px: 5000, bbox: { x: 10, y: 20, width: 50, height: 60 } }],
    metrics: { max_score: 1, flagged_area_fraction: 0.02 }, processing_ms: 42,
    artifacts: { heatmap: '/h', mask: '/m', overlay: '/o', score: '/s' }, warnings: [], limitations: ['Experimental heuristic.'], ...over,
  }
}

export function analysisResult(results: MethodResult[], over: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    analysis_id: 'an1', image: { width: 800, height: 600, source_format: 'PNG' }, requested_methods: results.map((r) => r.method),
    results, artifact_ttl_seconds: 900, report_json: '/api/results/an1/analysis.json',
    disclaimer: 'Each method below is independent.', ...over,
  }
}
