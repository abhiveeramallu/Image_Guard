# API reference

Base URL (local): `http://localhost:8000`. Interactive docs (development only): `/api/docs`.
All errors use `{"error": {"code": "...", "message": "..."}}`.

| Status | Codes |
|---|---|
| 400 | `invalid_image`, `empty_file` |
| 404 | `not_found` (unknown/expired artifact) |
| 413 | `file_too_large`, `image_too_large` |
| 415 | `unsupported_format` |
| 422 | `invalid_parameters`, `image_too_small`, `watermark_too_large`, `too_many_tiles` |
| 429 | `rate_limited` |
| 503 | `server_busy`, `watermark_unavailable` (no server key) |

## `GET /api/health`
`{"status": "ok", "version": "1.0.0"}`

## `POST /api/watermark` (multipart/form-data)
Returns the image (`image/png` or `image/jpeg`) with `Content-Disposition: attachment; filename="<stem>_watermarked.<ext>"`.

| Field | Type | Default | Constraint |
|---|---|---|---|
| `file` | file | required | JPEG/PNG, ≤ 10 MB, ≤ 16 MP, ≤ 8000 px/side |
| `watermark_type` | `text`\|`logo` | `text` | |
| `text` | string | `""` | required & non-blank for text; ≤ 200 chars |
| `logo` | file | – | required for logo; JPEG/PNG ≤ 2 MB |
| `position` | `top-left` … `bottom-right` (9 values, incl. `center`) | `bottom-right` | single layout |
| `opacity` | float | 0.5 | 0–1 |
| `font_size` | int px | 36 | 8–400 |
| `color` | hex | `#FFFFFF` | `#RGB` or `#RRGGBB` |
| `rotation` | float deg | 0 | −180…180 |
| `margin` | int px | 24 | 0–500 |
| `layout` | `single`\|`tiled` | `single` | tiled capped at 1500 tiles |
| `output_format` | `png`\|`jpeg` | `png` | |
| `outline`, `shadow` | bool | `true`, `false` | |
| `logo_scale` | float % of image width | 20 | 2–100 |
| `tile_spacing` | int px | 60 | 0–500 |

```bash
curl -X POST http://localhost:8000/api/watermark -F file=@photo.jpg -F text="© Me" \
  -F position=center -F opacity=0.4 -F layout=tiled -F rotation=30 -o out.png
```

## `POST /api/detect/copy-move` (multipart/form-data)
Fields: `file` plus optional `max_dimension` (256–3000, 1280), `n_features` (500–20000, 5000), `ratio` (0.5–0.95, 0.75),
`max_hamming` (10–128, 64), `min_displacement` (4–500 px, 24), `min_matches` (4–100, 8), `ransac_threshold` (1–10, 3.0), `max_regions` (1–10, 5).
Distances/thresholds in pixels apply to the (possibly downscaled) analysis image.

```bash
curl -X POST http://localhost:8000/api/detect/copy-move -F file=@suspect.png
```

Response (abridged; schema in `/api/docs`):
```json
{
  "analysis_id": "…", "status": "candidate_regions_found",
  "status_reason": "1 cluster(s) of mutually consistent ORB matches were found (37 retained matches). …",
  "method": {"name": "orb-hamming-ransac", "version": "1.0.0"},
  "image": {"width": 800, "height": 600, "analysis_width": 800, "analysis_height": 600, "analysis_scale": 1.0},
  "keypoints": 5000, "matches_before_filtering": 5000,
  "matches_after_descriptor_filtering": 51, "matches_retained": 37, "candidate_region_count": 1,
  "regions": [{"id": 1, "matches": 37, "mean_hamming_distance": 23.4,
    "transform": {"type": "similarity", "translation_x": 351.1, "translation_y": 200.0, "rotation_degrees": 0.1, "scale": 1.0},
    "region_a": {"bbox": {"x": 92, "y": 92, "width": 129, "height": 112}, "polygon": [[…]]},
    "region_b": {"bbox": {"x": 442, "y": 292, "width": 129, "height": 111}, "polygon": [[…]]}}],
  "processing_ms": 199.0, "settings": {…},
  "artifacts": {"annotated": "/api/results/<id>/annotated", "mask": "…/mask", "heatmap": "…/heatmap",
                "report_json": "…/report.json", "report_html": "…/report.html"},
  "artifact_ttl_seconds": 900, "warnings": [], "limitations": ["…"]
}
```
`status` ∈ `candidate_regions_found` | `no_candidate_regions_found` | `inconclusive`. "Analysis failed" is an HTTP error.
There is deliberately **no confidence or probability field**. `region_a`/`region_b` are symmetric: the method cannot tell original from copy.

## `GET /api/results/{analysis_id}/{artifact_name}`
`artifact_name` ∈ `annotated`, `mask`, `heatmap` (PNG), `report.json`, `report.html`. IDs are random (128-bit); names are allow-listed;
nothing touches the filesystem. Artifacts live in server memory and expire after `IMAGEGUARD_ARTIFACT_TTL_SECONDS` (default 900) → 404 afterwards.


---
# Added in 1.1

## `GET /api/capabilities`
What this server can do right now: `methods.{copy_move,splicing,localization}` (`available`, `experimental`, `reason`, `model`) and `invisible_watermark`.
Localization is unavailable until a model is configured (docs/MODELS.md); invisible watermarking is unavailable until `IMAGEGUARD_WATERMARK_KEY` is set.

## `POST /api/detect/analyze` (multipart/form-data)
`file`, `methods` (comma list of `copy_move`, `splicing`, `localization`, or `all_supported`; default `copy_move`), `splicing_threshold` (0.05–0.99, 0.5),
`localization_threshold` (0.01–0.99, 0.5), and the copy-move settings `max_dimension`, `n_features`, `ratio`, `min_matches`, `min_displacement`.
`POST /api/detect/copy-move` is unchanged.

```bash
curl -X POST localhost:8000/api/detect/analyze -F file=@suspect.jpg -F methods=all_supported
```
Response: `{analysis_id, image, requested_methods, results: [MethodResult], artifact_ttl_seconds, report_json, disclaimer}`. Each `MethodResult`:

| field | meaning |
|---|---|
| `method`, `category` | `copy_move`/`splicing`/`localization`; `copy_move`/`splicing`/`local_manipulation` |
| `evidence_type` | `feature_match_regions` (approximate hulls), `heuristic_forensic_map` (normalised score, not a probability), `model_probability_map` |
| `status` | `candidate_regions_found`, `no_candidate_regions_found`, `inconclusive`, **`unavailable`** (e.g. no model), **`failed`** |
| `experimental`, `model` | `true` for the splicing heuristic; model card details for localization |
| `threshold`, `threshold_semantics`, `region_count`, `regions`, `metrics`, `processing_ms` | computed values only |
| `artifacts` | URLs such as `/api/results/{id}/splicing.mask` (`annotated`/`overlay`/`mask`/`heatmap`/`score`); empty when unavailable/failed |

Methods are independent: there is no combined score, and a missing finding is never reported as "genuine". Failures/unavailability of one method do not affect the others.

## `GET /api/results/{analysis_id}/{method}/layer?threshold=0.5`
`method` ∈ `splicing`, `localization`. Re-applies a threshold to the stored 16-bit score map and returns a transparent red RGBA PNG (+ header `X-Region-Count`).

Artifact names: `{method}.{annotated|overlay|mask|heatmap|score}`, `analysis.json`, `watermarked.png|jpg` (plus the 1.0 names).

## `POST /api/watermark/invisible/embed` (multipart/form-data)
`file`, `owner` (1–12 printable ASCII chars; the payload), `strength` (`low`|`standard`|`high`), `output_format` (`png`|`jpeg`). Returns
`{watermark_id, algorithm, owner, integrity, metrics{psnr_db, blocks, copies_per_bit, quantization_step}, output_format, artifact, warnings, limitations}`;
download the image from `artifact`. 503 `watermark_unavailable` if no key is configured.

## `POST /api/watermark/invisible/verify` (multipart/form-data)
`file` → `{status: verified|inconclusive|not_detected, status_reason, owner, integrity_verified, algorithm, metrics, processing_ms, warnings, limitations}`.
`verified` = a payload whose HMAC (made with the server key) is valid was recovered. `inconclusive` = watermark-like signal with a valid header but failed check.
Neither status proves ownership or image integrity.

---
# Manual Forgery Lab API

## `POST /api/forgery-lab/analyze` (multipart/form-data)
Primary endpoint for the interactive Manual Forgery Lab canvas workspace. Runs requested forensic detectors on client-modified pixels and compares results against user edit ground-truth masks.

- `file`: Modified image exported from canvas (PNG/JPEG, required).
- `original_file`: Pristine unmodified original image (optional).
- `ground_truth_file`: Binary edit mask exported from canvas (white = modified pixels, optional).
- `methods`: Comma-separated list from `copy_move`, `splicing`, `localization`, `watermark_verify` (default: `copy_move,splicing,watermark_verify`).
- `splicing_threshold`: ELA/noise residual sensitivity (0.05–0.99, default 0.5).
- `localization_threshold`: ONNX localization threshold (0.01–0.99, default 0.5).
- `max_dimension`: Longest side of analysis copy (256–3000 px, default 1280).
- `n_features`: ORB keypoint budget (500–20000, default 5000).
- `ratio`: Lowe's ratio test (0.5–0.95, default 0.80).
- `min_matches`: Minimum verified match count per cluster (4–100, default 6).
- `min_displacement`: Minimum pixel separation for keypoint pairs (4–500 px, default 24).

**Response:**
Returns `ExperimentAnalysisResponse` containing:
- `experiment_id`: Unique 128-bit analysis identifier.
- `image`: Image metadata (width, height, format).
- `detection_results`: Per-method candidate regions, status, keypoint matches, and visual overlays.
- `watermark_verification`: Keyed DCT-QIM watermark verification result and HMAC status.
- `evaluation`: Objective pixel-level metrics ($\text{TP}, \text{FP}, \text{FN}, \text{Precision}, \text{Recall}, F_1, \text{IoU}$) calculated against ground-truth mask.
- `answers`: Structured answers addressing modification, watermark damage, and forensic candidate regions.
- `artifacts`: Links to downloadable modified image, ground-truth mask, overlays, and reports.
- `report_json` & `report_html`: Direct download URLs for reports.
- `processing_ms`: Total execution time.
- `disclaimer`: Forensic evidence review notice.

## `GET /api/forgery-lab/reports/{analysis_id}?format=json|html`
Downloads formatted forensic analysis reports:
- `format=json`: Machine-readable evaluation report (`application/json`).
- `format=html`: Standalone self-contained HTML report with embedded base64 artifacts (`text/html`).

## `GET /api/forgery-lab/artifacts/{analysis_id}/{filename}`
Serves forensic visual artifacts:
- `modified.png`, `ground_truth.png`
- `copy_move.overlay.png`, `copy_move.annotated.png`
- `splicing.overlay.png`, `localization.overlay.png`

---
# Legacy Attack Lab API (Backward-Compatible)

## `POST /api/attack-lab/prepare` (multipart/form-data)
Prepares an image session for Attack Lab experiments and optionally adds visible/invisible watermark baseline protection.
- `file`: JPEG or PNG image
- `visible_watermark`: bool (optional)
- `watermark_text`, `watermark_position`, `watermark_opacity`, `watermark_font_size`, `watermark_color`: visible watermark configuration
- `invisible_watermark`: bool (optional)
- `invisible_owner`: 1–12 chars owner identifier
- `invisible_strength`: `standard` | `high`

Returns `{experiment_id, original_image, baseline_image, artifacts, history, warnings}`.

## `POST /api/attack-lab/transform` (multipart/form-data)
Applies a controlled transformation to either `baseline` or `current` working image.
- `experiment_id`: active session ID
- `transformation`: `occlusion` | `crop` | `blur` | `jpeg` | `resize` | `rotation` | `copy_move` | `splicing`
- `target`: `current` | `baseline`
- `params`: JSON string with transformation parameters
- `donor_file`: optional file for `splicing`

Returns `{experiment_id, transformation, params, image, ground_truth, artifacts, history, warnings}`.
Ground truth mask artifact is stored at `/api/results/{id}/ground_truth.png`.

## `POST /api/attack-lab/reset` (multipart/form-data)
Resets working image back to the protected baseline and clears transformation history.
- `experiment_id`: active session ID

## `POST /api/attack-lab/analyze` (multipart/form-data)
Runs forensic detectors on the modified image independently without providing ground-truth coordinates.
- `experiment_id`: active session ID
- `methods`: comma-separated list from `copy_move`, `splicing`, `localization`, `watermark_verify`
- `splicing_threshold`, `localization_threshold`: detection thresholds

Returns `{experiment_id, image, baseline, history, ground_truth, detection_results, watermark_verification, evaluation, answers, artifacts, report_json, report_html, processing_ms, disclaimer}`.

## `GET /api/attack-lab/experiments/{id}`
Returns full session metadata, history, detector findings, and ground-truth records.

## `GET /api/attack-lab/experiments/{id}/report?format=json|html`
Downloads formatted experiment report in JSON or HTML.

