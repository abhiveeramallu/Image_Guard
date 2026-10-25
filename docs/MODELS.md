# Model-based localization: model contract and weights

**Status: integrated, awaiting real weights.** No model weights are bundled, no weights were downloaded, and no real forensic model has been
run through this pipeline. The `localization` method reports `unavailable` until you configure one. It never returns a map without running a model.

## What was (not) verified
A web search found candidate research models (e.g. NGIML checkpoints on Hugging Face, MVSS-Net, CAT-Net, TruFor, PSCC-Net). For none of them did this
project verify all of: (a) a clear, permissive license for the *weights*, (b) a downloadable official checkpoint, (c) an ONNX-exportable
architecture with documented pre/post-processing. Several are research-only or have unstated licenses, and the NGIML checkpoints are PyTorch `.pt` files with no
license stated in the material found. **Check the license of the weights and of their training data before use.** Nothing here should be read as an endorsement of any specific model.

## Requirements for a model
* ONNX file with one image input `NCHW float32` (RGB) and an output tensor containing a spatial map for "manipulated".
* A JSON model card next to it (`<model>.onnx.json`, or `IMAGEGUARD_LOCALIZATION_MODEL_CONFIG`):

```json
{
  "id": "org/model-name", "name": "Human readable name", "version": "1.0",
  "source": "https://where-the-weights-came-from", "license": "SPDX id or text",
  "intended_use": "image manipulation localization",
  "input":  {"size": null, "multiple_of": 32, "scale": 255.0,
             "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225], "channel_order": "rgb"},
  "output": {"semantics": "sigmoid_logit", "index": 0}
}
```
* `input.size`: `null` (keep aspect, longest side ≤ `IMAGEGUARD_INFERENCE_MAX_SIDE`, dims rounded up to `multiple_of`), an int (square) or `[H, W]`.
* `output.semantics` – you must declare it from the model's documentation; it decides how raw outputs become a probability:
  `probability` (already 0–1), `sigmoid_logit` (single-channel logit → sigmoid), `softmax_logits` (N-class logits → softmax, take `output.foreground_channel`).
  Raw logits are never shown as probabilities. The UI states the declared semantics next to the threshold.
* Required card fields: `id`, `version`, `source`, `license`, `output.semantics`. Missing/invalid → `unavailable` with the reason.

## Installing
```bash
pip install -r backend/requirements.txt           # includes onnxruntime (CPU)
# GPU: pip install onnxruntime-gpu (replaces onnxruntime) and set IMAGEGUARD_MODEL_DEVICE=cuda (or auto)
export IMAGEGUARD_LOCALIZATION_MODEL_PATH=/models/localizer.onnx
```
Export from PyTorch (example shape, adapt to your model): `torch.onnx.export(model, torch.randn(1,3,512,512), "localizer.onnx", input_names=["input"], output_names=["output"], dynamic_axes={"input": {0:"N",2:"H",3:"W"}, "output": {0:"N",2:"H",3:"W"}}, opset_version=17)`.

The model is loaded once (lazily, cached including failures, reloaded when the file or card changes). Inference runs in a worker thread with
`IMAGEGUARD_INFERENCE_TIMEOUT_SECONDS`; on timeout the method is reported `failed` (the thread cannot be killed, so set limits conservatively).

## After installing a model
1. `curl localhost:8000/api/capabilities` → `methods.localization.available` should be `true` with your card's details.
2. `python -m evaluation.run` automatically adds the model to the synthetic evaluation. **Synthetic results are not a measure of real-world accuracy**;
   evaluate on a licensed real dataset (e.g. CASIA, Columbia, COVERAGE, CoMoFoD) before trusting it.

## What the tests prove
`backend/tests/onnx_fixtures.py` builds tiny deterministic ONNX graphs (an edge filter, a fixed 1×1 conv). Tests with them run *real onnxruntime inference* and verify loading,
card validation, preprocessing/normalisation, each output semantics, resizing back to the original size, thresholding, timeout and unavailable handling.
They are pipeline tests only: those graphs are not trained and say nothing about forensic accuracy.
