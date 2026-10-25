import hashlib

import numpy as np

from evaluation import dataset, metrics


def test_pixel_metrics_hand_computed():
    gt = np.zeros((4, 4), np.uint8); gt[:2, :2] = 255        # 4 positives
    pred = np.zeros((4, 4), np.uint8); pred[:2, :3] = 255     # 6 predicted: 4 TP, 2 FP
    c = metrics.pixel_counts(pred, gt)
    assert c == {"tp": 4, "fp": 2, "tn": 10, "fn": 0}
    m = metrics.prf(c)
    assert m["precision"] == 4 / 6 and m["recall"] == 1.0 and abs(m["f1"] - 0.8) < 1e-9 and abs(m["iou"] - 4 / 6) < 1e-9


def test_metrics_undefined_cases_are_none():
    # Both empty (Pred=0, GT=0)
    m_both_empty = metrics.prf({"tp": 0, "fp": 0, "fn": 0, "tn": 16})
    assert m_both_empty["precision"] is None
    assert m_both_empty["recall"] is None
    assert m_both_empty["f1"] is None
    assert m_both_empty["iou"] is None

    # All-background ground truth with false alarms (GT=0, Pred>0)
    m_gt_zero_pred_pos = metrics.prf({"tp": 0, "fp": 5, "fn": 0, "tn": 11})
    assert m_gt_zero_pred_pos["precision"] == 0.0
    assert m_gt_zero_pred_pos["recall"] is None
    assert m_gt_zero_pred_pos["f1"] is None
    assert m_gt_zero_pred_pos["iou"] is None

    # Empty prediction on manipulated image (GT>0, Pred=0)
    m_pred_zero_gt_pos = metrics.prf({"tp": 0, "fp": 0, "fn": 7, "tn": 9})
    assert m_pred_zero_gt_pos["precision"] is None
    assert m_pred_zero_gt_pos["recall"] == 0.0
    assert m_pred_zero_gt_pos["f1"] == 0.0
    assert m_pred_zero_gt_pos["iou"] == 0.0


def test_evaluate_detection_shape_mismatch_and_empty():
    from app.services.attack_lab_service import evaluate_detection

    # Mismatched shapes: pred (2, 2), gt (4, 4)
    gt = np.zeros((4, 4), dtype=np.uint8)
    gt[:2, :2] = 255
    pred = np.zeros((2, 2), dtype=np.uint8)
    pred[0, 0] = 255  # after resize to (4, 4), top-left (2, 2) becomes 255

    res = evaluate_detection(gt, pred, "copy_move")
    assert res is not None
    assert res["tp"] == 4
    assert res["fp"] == 0
    assert res["fn"] == 0
    assert res["precision"] == 1.0
    assert res["recall"] == 1.0
    assert res["iou"] == 1.0

    # Neither exists
    assert evaluate_detection(None, pred, "copy_move") is None
    assert evaluate_detection(gt, None, "copy_move") is None


def test_image_level_metrics():
    r = metrics.image_level([(True, True), (True, False), (False, False), (False, True), (False, False)])
    assert (r["tp"], r["fn"], r["tn"], r["fp"]) == (1, 1, 2, 1)
    assert r["recall"] == 0.5 and r["precision"] == 0.5 and abs(r["false_positive_rate"] - 1 / 3) < 1e-9


def test_dataset_is_deterministic_and_has_ground_truth(tmp_path):
    a = dataset.build(tmp_path / "a")
    b = dataset.build(tmp_path / "b")
    assert [c["id"] for c in a] == [c["id"] for c in b]
    for c in a[:30]:
        assert hashlib.sha256((tmp_path / "a" / c["file"]).read_bytes()).hexdigest() == hashlib.sha256((tmp_path / "b" / c["file"]).read_bytes()).hexdigest()
    cats = {c["category"] for c in a}
    assert {"clean", "copy_move_translation", "copy_move_rotation", "splice_different_noise", "repeated_pattern", "low_texture"} <= cats
    assert all((c["gt"] is not None) == c["manipulated"] for c in a)
