# ImageGuard — Image Forgery Detection & Watermarking

A web app (React + FastAPI + OpenCV) for **detecting candidate image manipulation** and **watermarking images**. Detection results are evidence for human review, never proof of forgery or authenticity.

## Feature status
| Feature | Status |
|---|---|
| Visible text/logo watermark (position, opacity, size, colour, rotation, margin, tiling, outline/shadow, live preview, PNG/JPEG) | **Implemented & tested** |
| Copy-move detection (ORB + Hamming + RANSAC; annotated image, mask, heatmap, JSON/HTML report) | **Implemented & tested** |
| Invisible watermark: embed + HMAC-checked verify (DCT-QIM), downloadable output | **Implemented & tested** (synthetic robustness results below) |
| Manual Forgery Lab (interactive canvas editing, scratches, copy-move clone stamper, ground-truth tracking, forensic benchmarking & reports) | **Implemented & tested** |
| Multi-method analysis API/UI (copy-move, splicing, localization, all supported) with independent results and threshold re-rendering | **Implemented & tested** |
| Splicing / local-inconsistency detection | **Experimental heuristic** (noise-residual + JPEG ELA). Not a trained or validated detector |
| Model-based pixel-level localization (ONNX Runtime + model card contract, probability map, mask, overlay, heatmap, adjustable threshold) | **Implemented, awaiting real weights.** Reports `unavailable` until a model is configured; pipeline verified with generated untrained ONNX graphs only. See [docs/MODELS.md](docs/MODELS.md) |
| Evaluation on real photographs / public datasets | **Not done** |
| Cryptographic proof of ownership, resize/rotation-robust invisible watermarks, AI-generated-content detection | **Not implemented** |

## Quick start
```bash
scripts/setup.sh            # venvs, deps, .env files (generates a local random IMAGEGUARD_WATERMARK_KEY)
scripts/dev-backend.sh      # http://localhost:8000  (API docs: /api/docs)
scripts/dev-frontend.sh     # http://localhost:5173
```
Manual: `cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/uvicorn app.main:app --reload`; `cd frontend && npm ci && npm run dev`.
Prerequisites: Python 3.11–3.13, Node 20+.

## Configuration (`backend/.env`, prefix `IMAGEGUARD_`)
`ENVIRONMENT`, `CORS_ORIGINS`, `MAX_UPLOAD_BYTES` (10 MB), `MAX_IMAGE_PIXELS` (16 MP), `MAX_IMAGE_SIDE`, `ARTIFACT_TTL_SECONDS` (900), `MAX_CONCURRENT_JOBS`, `RATE_LIMIT_PER_MINUTE`,
**`WATERMARK_KEY`** (secret, required for invisible watermarking; server-side only), `LOCALIZATION_MODEL_PATH` / `LOCALIZATION_MODEL_CONFIG` (optional), `MODEL_DEVICE` (`auto|cpu|cuda`), `MODEL_THREADS`, `INFERENCE_TIMEOUT_SECONDS`, `INFERENCE_MAX_SIDE`.
Frontend (`frontend/.env`): `VITE_API_URL`.

## Detection methods (kept separate, never merged into one score)
1. **Copy-move (ORB)** — finds regions duplicated within one image. `evidence_type: feature_match_regions` (approximate hulls, not pixel-level).
2. **Splicing heuristic (experimental)** — flags regions whose local noise level (and, for JPEG, error level) deviates from the rest. `heuristic_forensic_map`: a normalised score, not a probability.
3. **Model localization** — a configured ONNX model produces a per-pixel map interpreted according to its declared model card. `model_probability_map`. Unavailable without a model; never mocked.

Statuses: `candidate_regions_found`, `no_candidate_regions_found`, `inconclusive`, `unavailable`, `failed`. "No candidates" never means "authentic".

## Invisible watermark
Payload (owner string ≤ 12 ASCII chars) + version + 32-bit truncated HMAC-SHA256 made with the server key → 144 bits, spread over 8×8 luminance DCT blocks by quantization index modulation (3 mid-frequency coefficients/block, key-permuted bit layout). Verification searches block-grid offsets, quantization steps and class shifts (small crops) and accepts a payload only if its HMAC verifies.
**A valid result means someone holding the server key embedded that payload — not proof of ownership, authorship or image integrity.** Key management: generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`, keep it secret and backed up; rotating it makes old watermarks unverifiable. Use PNG output to preserve it.

Measured on 6 synthetic 640×480 images (see docs/TESTING.md): recovered after JPEG q95–q40, noise σ≤10, small crops, blur σ=1; **not** recovered after JPEG q25, resizing or rotation. Distortion: mean PSNR 44.8 dB.

## API
Summary — details and examples in [docs/API.md](docs/API.md): `GET /api/health`, `GET /api/capabilities`, `POST /api/watermark`, `POST /api/watermark/invisible/{embed,verify}`, `POST /api/detect/copy-move`, `POST /api/detect/analyze`, `GET /api/results/{id}/{artifact}`, `GET /api/results/{id}/{method}/layer?threshold=`.
```bash
curl -X POST localhost:8000/api/detect/analyze -F file=@suspect.jpg -F methods=all_supported
curl -X POST localhost:8000/api/watermark/invisible/embed -F file=@photo.png -F owner=Acme-2026 -F strength=standard
```

## Tests and evaluation
```bash
scripts/test-all.sh
cd backend && .venv/bin/python -m evaluation.run
```
Latest: backend **165 passed**, frontend **48 passed**, typecheck (`tsc -b`) 0 errors, production build cleanly bundled in <1s. Synthetic evaluation numbers and their caveats are in [docs/TESTING.md](docs/TESTING.md) and `backend/evaluation/results/summary.md` (generated by the script; not hand-written). Synthetic results do not demonstrate real-world forensic accuracy.

## Manual Forgery Lab

The **Manual Forgery Lab** provides an interactive three-panel workspace for creating manual tamperings and evaluating forensic detectors:

### 1. Panel A — Original Image
- Upload any standard JPEG or PNG image (up to 10 MB and 16 MP).
- Displays pristine image dimensions ($W \times H\text{ px}$), filename, and file size.
- Maintains an immutable original buffer in memory (`origImageRef`), ensuring pristine pixels are never modified in place.
- Offers a one-click **Reset to Original** action that purges working canvas edits and resets the ground-truth mask.

### 2. Panel B — Interactive Editing Canvas
- **Pixel-Accurate Resolution:** HTML5 `<canvas>` elements maintain the native full resolution of the original image with high-DPI and responsive coordinate projection `(clientX - rect.left) * (canvas.width / rect.width)`.
- **Brush & Scratch Tool:** Paint scratches, draw occlusions, or cover areas using customizable brush sizes (1–60 px) and preset color swatches (Red, Black, White, Blue, Yellow, Green, Custom).
- **Eraser Tool:** Reverts modified regions under the brush back to the pristine original image buffer and subtracts them from the ground-truth layer.
- **Dedicated Copy-Move Tool:**
  1. *Select Source Region:* Drag a rectangular marquee over any textured source area on the canvas.
  2. *Place Destination:* Click or drag to reposition the clone marquee to a destination location.
  3. *Stamp Clone:* Copies source pixels into destination, records modified destination pixels into the ground-truth layer, and pushes the snapshot to the undo stack.
- **History Stack:** Full Undo (`Ctrl+Z`), Redo, and Clear Edits support, keeping the working image and ground truth synchronized.
- **Real-Time Altered Pixel Counter:** Displays exact modified pixel count and percentage (e.g. `1,280 px (0.32%)`), or flags clean baseline status when unedited.

### 3. Panel C — Forensic Detection & Evidence Analysis
- **Independent Execution:** Detectors (`copy_move`, `splicing`, `localization`, `watermark_verify`) receive *only* the modified canvas image. User edit coordinates and ground-truth masks are strictly isolated and never leaked to detectors.
- **Explainable Detector Cards:** Reports status (`candidate_regions_found`, `no_candidate_regions_found`), region count, keypoint matches, and documented limitations.
- **Visualizer & Multi-View Tabs:**
  - *Modified Canvas:* Working image exported at full resolution.
  - *Original Image:* Pristine unedited baseline.
  - *Side-by-Side:* Synchronized view comparing original vs. modified.
  - *Copy-Move Matches:* Detector overlay showing ORB keypoints (yellow circles), RANSAC-verified match lines (cyan), and candidate region bounding boxes (red).
  - *Splicing Heatmap:* Error Level Analysis (ELA) and high-frequency noise residual discrepancy maps.
  - *Ground-Truth Mask:* Isolated binary mask of user edits.
- **Quantitative Evaluation Table:** Evaluates candidate detector predictions against known ground truth ($\text{TP}, \text{FP}, \text{FN}, \text{Precision}, \text{Recall}, F_1, \text{IoU}$).
- **Scientific Honesty on Baseline Images:** When an unmodified image is analyzed, detectors report actual performance on pristine pixels, highlighting natural false alarms (e.g. repeated architectural textures) without claiming proof of authenticity.
- **Downloadable Reports:** Download full-resolution modified PNG, structured JSON report, and self-contained HTML forensic report.

## Interactive Demonstration Workflow

1. **Step 1: Upload Source Image**
   - Navigate to `/forgery-lab` via the sidebar or Dashboard.
   - Upload a test photo (JPEG or PNG).
   - Inspect Panel A for image metadata (resolution, file size).
2. **Step 2: Apply Manual Modifications or Clone Tampering**
   - Select the **Brush / Scratch** tool to paint scratches or opaque coverings.
   - Or select the **Copy-Move Tool**: drag a source rectangle over textured detail, click a destination location, and click **Stamp Clone**.
   - Note the real-time pixel counter tracking modified pixels in the isolated ground-truth layer.
3. **Step 3: Execute Independent Forensic Detection**
   - In Panel C, select active detectors (*ORB Copy-Move Detector*, *Splicing Heuristic*, *Invisible Watermark Verification*).
   - Click **Run Forgery Detection**.
   - Inspect candidate regions and keypoint match visualizations.
4. **Step 4: Review Multi-View Evidence & Benchmark Metrics**
   - Switch between **Modified Canvas**, **Original Image**, **Side-by-Side**, **Copy-Move Matches**, and **Ground Truth Mask**.
   - Review quantitative detection evaluation ($\text{Precision}, \text{Recall}, F_1, \text{IoU}$) comparing detector candidate regions against the ground-truth mask.
   - Click **Download JSON Report** or **Download HTML Report** for an archival audit record.

## Verification performed
In a browser against the running backend: a synthetic forged image analysed with all supported methods (copy-move, splicing, and localization using a generated *pipeline-test* ONNX model that is not a forensic model), per-method results and the threshold slider; invisible watermark embed → real download artifact → verify (verified with payload and valid HMAC) and an unmarked image (not detected); visible watermark preview/tiling; invalid files. One integration bug found this way (CORS did not expose `X-Region-Count`) was fixed and covered by a test. Nothing has been deployed.

## Known limitations
Copy-move only finds duplication in one image and can flag repeated patterns; the splicing heuristic misses matched-noise composites and false-alarms on some clean images; no trained forensic model has been run; heuristics were tuned on synthetic data; the invisible watermark does not survive resizing/rotation/heavy compression and is removable by a determined attacker; artifact store and rate limiter are per-process (single worker); lint uses oxlint with 2 known warnings.

## Related techniques
| Technique | In this app |
|---|---|
| Copy-move detection | Implemented (ORB baseline) |
| Splicing detection | Experimental heuristic only |
| Pixel-level tampering localization | Model integration ready; no weights bundled; ORB regions and heuristic maps are *not* pixel-level |
| Visible watermarking | Implemented; can be cropped/removed; proves nothing |
| Invisible watermarking | Implemented (keyed DCT-QIM + HMAC); limited robustness |

## Deployment
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (Render via `render.yaml`, Vercel via `frontend/vercel.json`). Set `IMAGEGUARD_WATERMARK_KEY` as a secret. Not deployed or verified on those hosts.

## Next steps
Obtain and license-check a real manipulation-localization model and evaluate it on real datasets; evaluate the heuristics on real photographs; stronger invisible-watermark synchronisation (resize/rotation) and error-correcting codes; shared artifact storage for multi-worker hosting; browser E2E tests.
