# Architecture

```
React (Vite, TS, Tailwind) ──HTTP/multipart──▶ FastAPI ──▶ services/
   pages/ components/ hooks/                     api/         image_service      decode + validate + encode
   services/api.ts (typed axios client)          schemas/     watermark_service  Pillow compositing
                                                 core/        copy_move_service  OpenCV ORB baseline
                                                              artifact_store     in-memory TTL store
                                                              report_service     JSON / HTML report
```

## Request flow
**Watermark**: upload → size cap while streaming → decode by content (Pillow) with pixel/side limits and decompression-bomb guard → EXIF orientation → build RGBA stamp → opacity on alpha only → rotate → alpha-composite (clipped) → encode PNG/JPEG → binary response. Nothing is persisted.

**Detection**: upload → decode → RGB array → `detect_copy_move` → PNG-encode annotated/mask/heatmap → build reports → put in `ArtifactStore` (RAM, TTL, entry and byte caps) → JSON with artifact URLs. The frontend fetches artifacts as blobs and renders them via object URLs (revoked on change/unmount).

## Detector (`copy_move_service.py`)
ORB → self-kNN Hamming matching (skip self and neighbours < `min_displacement`) → ratio + absolute distance filter → unordered de-dup → sequential RANSAC (`estimateAffinePartial2D`: shift/rotation/uniform scale) → cluster filters (min matches, hull area, overlap, scale 0.5–2) → padded convex-hull localization → artifacts. Repetitive structure (≥ 6 distinct clusters) ⇒ `inconclusive`. Few keypoints ⇒ `inconclusive`.

Hull padding is 16 px ≈ ORB patch radius. Localization is approximate (see IoU in TESTING.md).

## Extending
New methods (e.g., a PyTorch segmentation model) should expose a function returning the same `DetectionOutput`/response schema; add a route or a `method` selector in `routes_detect.py`. The frontend only consumes the response contract (`types/api.ts`), so it needs no rewrite.

## Safety controls
Upload/pixel/side limits, content-based format checks, bounded stamp/tile sizes, concurrency semaphore (503 when saturated), per-IP rate limit, strict CORS, no filesystem writes, sanitized download filenames, allow-listed artifact names, CSP on the HTML report, generic 500 errors without internals. Docs/OpenAPI are disabled when `IMAGEGUARD_ENVIRONMENT=production`.

## Known design constraints
The artifact store and rate limiter are per-process. Run a single worker (as in `render.yaml`) or move them to shared storage (Redis/S3) to scale horizontally.


---
# 1.1 additions

```
services/
  copy_move_service      ORB baseline (feature_match_regions)             -> MethodResult
  splicing_service       EXPERIMENTAL noise/ELA heuristic (score map)     -> MapOutput -> MethodResult
  localization_service   ONNX Runtime model manager + card contract      -> MapOutput -> MethodResult | unavailable
  forensics_common       thresholding, regions, overlays, 16-bit score PNG, threshold layer
  invisible_watermark_service  DCT-QIM embed / HMAC-checked verify
api/ routes_analyze (multi-method), routes_capabilities, routes_invisible
```
Evidence types are kept apart end-to-end: ORB boxes/hulls, heuristic maps and model probability maps have different `evidence_type`, artifacts and threshold semantics and are never merged.
`/api/detect/analyze` runs requested methods sequentially inside one job slot; each method is isolated (an exception becomes `status: failed`, an absent model `status: unavailable`).

**Splicing heuristic**: residual = image − 3×3 median; local mean residual energy over a window (≥32 px) → log → robust z (median/MAD, MAD floored) → score = clip((z−4)/(8−4)); for JPEG inputs a second ELA-based map (re-save at q90, z thresholds 7–11) and the maximum is taken; Gaussian smoothing; threshold; morphology; regions ≥0.2 % of the image. >50 % flagged ⇒ inconclusive.

**Localization**: card-driven preprocessing → ONNX session (one per process, thread pool with timeout) → declared activation → bilinear resize to original → threshold → mask/overlay/heatmap.

**Invisible watermark**: payload = version | length | owner[12] | HMAC-SHA256(key)[:4] (144 bits). 8×8 luminance DCT blocks; class = (row·13 + col) mod 144, key-permuted payload bit per class; QIM (step 16/24/32) on coefficients (1,2),(2,1),(2,2); ΔY added to R,G,B. Verify: 64 grid offsets × 3 steps soft votes → cyclic shift search (tolerates small crops) → accept only when HMAC validates.
The key comes from `IMAGEGUARD_WATERMARK_KEY` (never returned by any endpoint).
