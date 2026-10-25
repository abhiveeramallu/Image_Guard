# Testing and evaluation

```bash
scripts/test-all.sh                                   # backend pytest + frontend typecheck, tests, build
cd backend && .venv/bin/python -m evaluation.run      # synthetic evaluation -> evaluation/results/
```

## Automated tests (latest run on the development machine)
| Suite | Result |
|---|---|
| Backend `pytest` | **117 passed** |
| Frontend `vitest` | **42 passed** (5 files) |
| `tsc -b` | passes |
| `npm run build` | succeeds |
| `npm run lint` (oxlint — the project's linter, not ESLint) | 0 errors, 2 warnings (`set-state-in-effect` in `useBlobUrls.ts` and `WatermarkPage.tsx`; left as-is) |
| `npm ci` from a clean `node_modules` | succeeds; `npm audit --omit=dev`: 0 vulnerabilities |

### What the backend tests cover
* **1.0 suites (unchanged, 59 tests):** watermark behaviour, copy-move on translation/rotation/scale, clean images, blank/low-texture, repeated patterns, API contract, artifacts, expiry, CORS.
* **Splicing heuristic (experimental):** localizes synthetic different-noise splices (mean IoU > 0.4), no candidates on clean PNGs, inconclusive on flat/tiny images, threshold changes the mask, JPEG inputs use the ELA component.
* **Model localization:** unavailable when unconfigured / missing file / missing or invalid card / corrupt ONNX / CUDA requested but absent; **real onnxruntime inference** on generated ONNX graphs for each output semantics (`probability`, `sigmoid_logit`, `softmax_logits`) checking output shape, [0,1] range, hand-computed values, card normalisation, fixed-size resize-back, load-once caching, inference timeout. *These graphs are not trained models; the tests prove the pipeline, not forensic accuracy.* No mocking is used for the model boundary — real onnxruntime runs.
* **Invisible watermark:** invisibility (PSNR > 40 dB), exact payload recovery, unmarked image not verified, wrong key not verified, JPEG q95/85/75/60, mild noise, small crop recovered; resize reported as *not* verified (documented limitation); invalid owner/too-small image rejected; payload/MAC unit tests.
* **API:** capabilities with/without model and key; multi-method analyze (independence, unavailable, failed isolation, artifacts, report, allow-listing, expiry); threshold layer; invisible embed → download → verify round-trip, JPEG round-trip, key rotation, validation errors, 503 without key; CORS exposes the headers the frontend reads; rate limiter returns 429.
* **Evaluation code:** metrics against hand-computed values; dataset generation is deterministic.

### Frontend tests (API layer mocked, so these prove UI behaviour, not backend correctness)
Method selector (experimental badge, unavailable localization with reason, server unreachable), multi-method run via `analyze`, independent result panels, unavailable/failed states with no images, copy-move fallback, model info, threshold re-render calls, report download, errors + retry; invisible watermark unavailable state, owner validation, embed/download/verify results (verified / inconclusive / not detected), errors + retry; visible vs invisible tab separation; all 1.0 tests.
The real HTTP path was exercised manually in a browser (see README "Verification performed").

## Synthetic evaluation (`backend/evaluation/`)
Generates 83 deterministic synthetic images with ground-truth masks into `evaluation/data/synthetic/` (git-ignored; regenerate any time) and writes `evaluation/results/{summary.md,summary.json,detection_rows.csv,detection_rows.json}`.
Seeds 500+ are used for evaluation; the splicing heuristic's thresholds were tuned on seeds 200–211 only.

**These are synthetic images produced by the same generator family used during development. They show that the pipelines run and how they behave on controlled inputs. They are not accuracy on real photographs.**

Results from the last run (full tables in `evaluation/results/summary.md`):

| Method | Image-level (relevant cases) | Pixel-level, manipulated images (micro-avg) |
|---|---|---|
| Copy-move (ORB) | n=59: TP 30, FP 0, TN 29, FN 0 | P 0.966, R 0.697, F1 0.810, IoU 0.681 |
| Splicing heuristic (experimental) | n=53: TP 14, FP 3, TN 26, FN 10 → recall 0.583, precision 0.824, FPR 0.103 | P 0.929, R 0.439, F1 0.596, IoU 0.425 |
| Model localization | **not evaluated: no model available.** Real inference performance has not been measured. | — |

Notable per-category findings (from the same run):
* Copy-move: all translation / rotation 25° / scale 0.8 / JPEG q75 / 0.75 resize cases flagged; all clean, clean-JPEG cases unflagged; periodic textures and flat/gradient images were reported `inconclusive` (not flagged).
* Splicing: different-noise splices detected in all cases (IoU 0.60 PNG, 0.89 JPEG q90); **splices with matched noise were not detected** (0/6 PNG, 2/6 flagged after JPEG q90 with pixel IoU 0 — i.e. the flagged areas missed the splice); false-alarm rate on clean images: 1/12 PNG, 2/12 JPEG. The heuristic mostly detects noise-level mismatch, which is an easy synthetic case.
* Invisible watermark (6 images, 640×480, mean PSNR 44.77 dB): exact payload + integrity verified 6/6 after no change, JPEG q95/85/75/60/40, Gaussian noise σ=2/5/10, 13×7 px crop, 5 % crop per side, blur σ=1; **0/6 after JPEG q25, resizing (0.9, 0.75, 1.25×) and 2° rotation.** 0/6 unmarked images and 0/6 wrong-key checks verified.

Not covered: real photographs or public benchmarks (CASIA, Columbia, CoMoFoD, …), anti-forensic attacks, AI-generated edits, any trained forensic model, browser end-to-end automation, load testing, real deployments.
