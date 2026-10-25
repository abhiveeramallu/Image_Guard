# Implementation checklist (phase 2 work)

Baseline before changes: backend 59 tests pass; frontend 24 tests, typecheck, build pass. Existing endpoints are kept unchanged.

- [x] P1 Inspect + baseline
- [x] P2 Splicing (experimental forensic baseline) + `/api/detect/analyze` multi-method endpoint + `/api/capabilities`
- [x] P3 Model-based localization (ONNX Runtime loader, config contract, threshold re-render) — real weights NOT verified/available
- [x] P4 Invisible watermark (DCT-QIM + HMAC) embed/verify endpoints
- [x] P5 Evaluation scripts (synthetic) + generated results
- [x] P6 Frontend clean install (`npm ci`), typecheck, lint, tests, build
- [x] P7 UI integration (method selector, multi-result view, invisible watermark tab)
- [x] P8 Security review of new endpoints
- [x] P9 Tests (backend + frontend)
- [x] P10 Docs

## Outcomes / still blocked
* P3: ONNX pipeline done and tested with generated untrained graphs. **Blocked:** no pretrained localization model with verified license/weights/ONNX interface was available; real inference unverified (docs/MODELS.md).
* P5: synthetic evaluation only; real-dataset evaluation not done (no datasets downloaded by design).
* P6: lint tool is oxlint (no ESLint in the project); 2 warnings remain.
* Deployment: not performed.
