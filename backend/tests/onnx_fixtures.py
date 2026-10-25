"""Build tiny *real* ONNX models for pipeline tests.

These are NOT trained forensic models. They are deterministic graphs (e.g. a Sobel-like edge
response) whose purpose is to exercise model loading, preprocessing, inference, activation
handling and resizing end-to-end with onnxruntime. They say nothing about forensic accuracy.
"""
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


def _save(nodes, inits, in_shape, out_shape, path: Path):
    g = helper.make_graph(
        nodes, "g", [helper.make_tensor_value_info("input", TensorProto.FLOAT, in_shape)],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, out_shape)], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
    m.ir_version = 8
    onnx.checker.check_model(m)
    onnx.save(m, str(path))


def edge_model(path: Path, activation: str = "sigmoid_logit") -> None:
    """Conv (grayscale-ish edge kernel, stride 1, same padding) -> 1-channel output map (logit or probability)."""
    k = np.zeros((1, 3, 3, 3), np.float32)
    lap = np.array([[0, -1, 0], [-1, 4, -1], [0, -1, 0]], np.float32)
    k[0, :, :, :] = lap[None] / 3.0
    nodes = [helper.make_node("Conv", ["input", "W"], ["conv"], pads=[1, 1, 1, 1])]
    inits = [numpy_helper.from_array(k, "W")]
    if activation == "probability":
        nodes += [helper.make_node("Abs", ["conv"], ["a"]), helper.make_node("Sigmoid", ["a"], ["output"])]
    else:
        nodes += [helper.make_node("Identity", ["conv"], ["output"])]
    _save(nodes, inits, ["N", 3, "H", "W"], ["N", 1, "H", "W"], path)


def softmax_model(path: Path) -> None:
    """Two-channel logits (background, manipulated) from fixed 1x1 convs on the red channel."""
    w = np.zeros((2, 3, 1, 1), np.float32)
    w[0, 0] = -4.0
    w[1, 0] = 4.0
    _save([helper.make_node("Conv", ["input", "W"], ["output"])], [numpy_helper.from_array(w, "W")],
          ["N", 3, "H", "W"], ["N", 2, "H", "W"], path)


def write_card(model_path: Path, semantics: str, **over) -> Path:
    card = {
        "id": "test/synthetic-pipeline-model", "name": "Pipeline test model (NOT a forensic model)", "version": "0",
        "source": "generated in tests", "license": "n/a", "intended_use": "pipeline testing only",
        "input": {"size": None, "multiple_of": 8, "scale": 255.0, "mean": [0.0, 0.0, 0.0], "std": [1.0, 1.0, 1.0]},
        "output": {"semantics": semantics, "index": 0},
    }
    if semantics == "softmax_logits":
        card["output"]["foreground_channel"] = 1
    for k, v in over.items():
        card[k] = v
    p = Path(str(model_path) + ".json")
    p.write_text(json.dumps(card))
    return p
