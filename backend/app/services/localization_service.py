"""Model-based pixel-level manipulation localization via ONNX Runtime.

No weights ship with this repository. A model is enabled only when
IMAGEGUARD_LOCALIZATION_MODEL_PATH points to an .onnx file *and* a JSON model card
(default: <model>.onnx.json) declares how to preprocess inputs and interpret outputs.
If either is missing or invalid the method reports `unavailable`; it never fabricates maps.

Model card (JSON):
{
  "id": "org/model", "name": "...", "version": "...", "source": "URL of weights",
  "license": "SPDX or text", "intended_use": "image manipulation localization",
  "input":  {"size": null | 512 | [H, W],   # null = keep aspect, longest side <= inference_max_side
             "multiple_of": 32,              # resize up so H and W are multiples of this
             "scale": 255.0, "mean": [0.485,0.456,0.406], "std": [0.229,0.224,0.225], "channel_order": "rgb"},
  "output": {"semantics": "probability" | "sigmoid_logit" | "softmax_logits",
             "index": 0,                     # which ONNX output tensor
             "foreground_channel": 1}        # only for softmax_logits (class index = 'manipulated')
}
Raw logits are converted only by the activation named in `semantics`, and the result is then
described as the model's per-pixel manipulation probability *as defined by its card*.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.config import Settings
from app.services.forensics_common import MapOutput, threshold_mask

METHOD_NAME = "onnx-manipulation-localization"
METHOD_VERSION = "1.0.0"
SEMANTICS = {"probability", "sigmoid_logit", "softmax_logits"}

INSTALL_HELP = (
    "No localization model is configured. Obtain an image-manipulation localization model exported to ONNX, "
    "write its JSON model card (see docs/MODELS.md), then set IMAGEGUARD_LOCALIZATION_MODEL_PATH."
)

LIMITATIONS = [
    "Model outputs reflect the training data of the specific model; they are not guaranteed to generalise to your images.",
    "Predicted maps can miss manipulations and mark benign regions (e.g. text overlays, recompression, resized content).",
    "Resizing the network input and the map loses fine detail; masks are thresholded predictions, not ground truth.",
    "Results are independent of the ORB copy-move baseline and are never combined with it into one score.",
    "No manipulated pixels found does not show an image is authentic.",
]


class ModelUnavailable(Exception):
    """Raised when the model is not configured or cannot be loaded."""


@dataclass
class LoadedModel:
    session: object
    card: dict
    provider: str
    input_name: str


def _validate_card(card: dict) -> dict:
    for key in ("id", "version", "source", "license"):
        if not isinstance(card.get(key), str) or not card[key].strip():
            raise ModelUnavailable(f"Model card is missing required field '{key}'.")
    inp, out = card.get("input", {}), card.get("output", {})
    if out.get("semantics") not in SEMANTICS:
        raise ModelUnavailable(f"Model card output.semantics must be one of {sorted(SEMANTICS)}.")
    if out["semantics"] == "softmax_logits" and not isinstance(out.get("foreground_channel"), int):
        raise ModelUnavailable("softmax_logits requires output.foreground_channel.")
    mean, std = inp.get("mean", [0, 0, 0]), inp.get("std", [1, 1, 1])
    if len(mean) != 3 or len(std) != 3 or any(s <= 0 for s in std):
        raise ModelUnavailable("Model card input.mean/std must have 3 values and std > 0.")
    return card


def _providers(device: str) -> tuple[list[str], str]:
    import onnxruntime as ort
    avail = ort.get_available_providers()
    if device == "cpu":
        return ["CPUExecutionProvider"], "CPUExecutionProvider"
    if "CUDAExecutionProvider" in avail:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"], "CUDAExecutionProvider"
    if device == "cuda":
        raise ModelUnavailable("model_device=cuda was requested but CUDAExecutionProvider is not available.")
    return ["CPUExecutionProvider"], "CPUExecutionProvider"


def load_model(model_path: str, card_path: str | None, device: str, threads: int) -> LoadedModel:
    try:
        import onnxruntime as ort
    except ImportError as e:
        raise ModelUnavailable("onnxruntime is not installed (pip install onnxruntime).") from e
    mp = Path(model_path)
    if not mp.is_file():
        raise ModelUnavailable("The configured model file does not exist.")
    cp = Path(card_path) if card_path else Path(str(mp) + ".json")
    if not cp.is_file():
        raise ModelUnavailable("The model card JSON (<model>.onnx.json) was not found.")
    try:
        card = _validate_card(json.loads(cp.read_text()))
    except json.JSONDecodeError as e:
        raise ModelUnavailable("The model card is not valid JSON.") from e
    providers, active = _providers(device)
    so = ort.SessionOptions()
    so.intra_op_num_threads = max(1, threads)
    try:
        session = ort.InferenceSession(str(mp), sess_options=so, providers=providers)
    except Exception as e:  # onnxruntime raises various types
        raise ModelUnavailable(f"The ONNX model could not be loaded ({type(e).__name__}).") from e
    return LoadedModel(session=session, card=card, provider=active, input_name=session.get_inputs()[0].name)


class ModelManager:
    """Loads the model once and caches the result (including failures) until the config changes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._model: LoadedModel | None = None
        self._error: str | None = None
        self._pool = ThreadPoolExecutor(max_workers=1)

    def _ensure(self, s: Settings) -> None:
        if not s.localization_model_path:
            self._key, self._model, self._error = None, None, INSTALL_HELP
            return
        mp = Path(s.localization_model_path)
        cp = Path(s.localization_model_config) if s.localization_model_config else Path(str(mp) + ".json")
        stamp = tuple((p.stat().st_mtime_ns if p.exists() else None) for p in (mp, cp))
        key = (str(mp), str(cp), s.model_device, s.model_threads, stamp)
        if key == self._key:
            return
        self._key = key
        try:
            self._model, self._error = load_model(str(mp), s.localization_model_config, s.model_device, s.model_threads), None
        except ModelUnavailable as e:
            self._model, self._error = None, str(e)

    def status(self, s: Settings) -> dict:
        with self._lock:
            self._ensure(s)
            if self._model:
                c = self._model.card
                return {"available": True, "reason": None, "model": _public_card(c, self._model.provider)}
            return {"available": False, "reason": self._error, "model": None}

    def get(self, s: Settings) -> LoadedModel:
        with self._lock:
            self._ensure(s)
            if not self._model:
                raise ModelUnavailable(self._error or INSTALL_HELP)
            return self._model

    def run(self, model: LoadedModel, x: np.ndarray, timeout: float):
        fut = self._pool.submit(lambda: model.session.run(None, {model.input_name: x}))
        try:
            return fut.result(timeout=timeout)
        except FutureTimeout:
            fut.cancel()
            raise TimeoutError(f"Model inference exceeded {timeout:.0f}s.")


manager = ModelManager()


def _public_card(c: dict, provider: str) -> dict:
    return {"id": c["id"], "name": c.get("name", c["id"]), "version": c["version"], "source": c["source"],
            "license": c["license"], "intended_use": c.get("intended_use"), "output_semantics": c["output"]["semantics"],
            "provider": provider}


def _preprocess(rgb: np.ndarray, card: dict, max_side: int) -> np.ndarray:
    inp = card.get("input", {})
    H, W = rgb.shape[:2]
    size = inp.get("size")
    if isinstance(size, int):
        h, w = size, size
    elif isinstance(size, list) and len(size) == 2:
        h, w = int(size[0]), int(size[1])
    else:
        s = min(1.0, max_side / max(H, W))
        h, w = round(H * s), round(W * s)
        m = int(inp.get("multiple_of", 1))
        if m > 1:
            h, w = -(-h // m) * m, -(-w // m) * m
    img = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA if (h < H or w < W) else cv2.INTER_LINEAR)
    x = img.astype(np.float32) / float(inp.get("scale", 255.0))
    x = (x - np.array(inp.get("mean", [0, 0, 0]), np.float32)) / np.array(inp.get("std", [1, 1, 1]), np.float32)
    if inp.get("channel_order", "rgb") == "bgr":
        x = x[..., ::-1]
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


def _to_probability(raw: np.ndarray, card: dict) -> np.ndarray:
    out = card["output"]
    a = np.asarray(raw, np.float32)
    sem = out["semantics"]
    if sem == "softmax_logits":
        if a.ndim != 4:
            raise ValueError("softmax_logits output must be NCHW.")
        e = np.exp(a - a.max(axis=1, keepdims=True))
        p = (e / e.sum(axis=1, keepdims=True))[0, out["foreground_channel"]]
    else:
        p = a.reshape(a.shape[-2], a.shape[-1]) if a.ndim >= 2 else None
        if p is None:
            raise ValueError("Unexpected model output rank.")
        if a.ndim == 4 and a.shape[1] != 1:
            raise ValueError("Expected a single-channel output for this semantics.")
        if sem == "sigmoid_logit":
            p = 1.0 / (1.0 + np.exp(-p))
    return np.clip(p, 0.0, 1.0).astype(np.float32)


def localize(rgb: np.ndarray, settings: Settings, threshold: float = 0.5, mgr: ModelManager | None = None) -> MapOutput:
    """Run the configured model. Raises ModelUnavailable if there is no valid model."""
    mgr = mgr or manager
    t0 = time.perf_counter()
    model = mgr.get(settings)
    H, W = rgb.shape[:2]
    x = _preprocess(rgb, model.card, settings.inference_max_side)
    t1 = time.perf_counter()
    outputs = mgr.run(model, x, settings.inference_timeout_seconds)
    infer_ms = (time.perf_counter() - t1) * 1000
    idx = model.card["output"].get("index", 0)
    prob = _to_probability(outputs[idx], model.card)
    score = cv2.resize(prob, (W, H), interpolation=cv2.INTER_LINEAR)  # bilinear upsampling of the probability map
    mask, regions = threshold_mask(score, threshold, max(32, int(0.0005 * H * W)), close_px=5)
    frac = float((mask > 0).mean())
    for r in regions:
        r["area_fraction"] = round(r["area_px"] / (H * W), 4)
    metrics = {
        "model": _public_card(model.card, model.provider),
        "model_input_shape": list(x.shape), "model_output_shape": list(np.asarray(outputs[idx]).shape),
        "inference_ms": round(infer_ms, 1), "max_probability": round(float(score.max()), 4),
        "mean_probability": round(float(score.mean()), 4), "flagged_area_fraction": round(frac, 4),
        "threshold_semantics": f"model-defined per-pixel manipulation probability (card semantics: {model.card['output']['semantics']})",
    }
    if regions:
        status, reason = "candidate_regions_found", f"The model marked {len(regions)} region(s) above probability {threshold:.2f}."
    else:
        status, reason = "no_candidate_regions_found", f"No pixels exceeded probability {threshold:.2f} under this model."
    return MapOutput(status=status, status_reason=reason, score=score, threshold=threshold, regions=regions, metrics=metrics,
                     processing_ms=round((time.perf_counter() - t0) * 1000, 1), mask=mask)
