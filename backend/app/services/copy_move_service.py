"""Copy-move candidate detection: ORB + Hamming matching + RANSAC similarity clustering.

This is an explainable baseline. Pipeline:
  1. grayscale analysis copy, optionally downscaled (scale tracked for coordinate mapping)
  2. ORB keypoints + 256-bit binary descriptors
  3. self-matching with Hamming distance: for every keypoint, find nearest neighbours,
     discarding itself and any neighbour closer than `min_displacement` pixels, then
     apply Lowe's ratio test and an absolute Hamming-distance cap
  4. unordered de-duplication of symmetric pairs (a<->b)
  5. sequential RANSAC: repeatedly fit a similarity transform (translation, rotation,
     uniform scale) to the remaining matches; its inliers form one candidate cluster
  6. clusters are filtered by support, spatial extent and overlap, then localized by the
     (padded) convex hull of the matched keypoints on each side

The algorithm cannot tell which side is the original and which is the copy, so regions
are reported symmetrically as region_a / region_b. Localization is approximate (hulls
of sparse keypoints), not pixel-accurate. No probability/confidence is produced.
"""
import logging
import time
from dataclasses import asdict, dataclass

import cv2
import numpy as np

log = logging.getLogger("imageguard.copy_move")

METHOD_NAME = "orb-hamming-ransac"
METHOD_VERSION = "1.0.0"

LIMITATIONS = [
    "Only copy-move (duplication within the same image) is analysed; splicing from other images, retouching, and AI-generated edits are not detected.",
    "ORB needs texture: smooth or low-contrast copied areas (sky, walls, skin) yield few or no keypoints and can be missed.",
    "Strong rescaling, rotation, blur, noise or recompression of the copied area can break descriptor matching.",
    "Repeated natural or man-made patterns (windows, tiles, foliage) can produce false positives; many distinct consistent transforms are reported as inconclusive.",
    "Regions are approximate hulls of matched keypoints, not pixel-accurate manipulation masks.",
    "A result of 'no candidate regions' only means this method found nothing; it does not show the image is authentic.",
]


@dataclass
class CopyMoveParams:
    max_dimension: int = 1280      # longest side of the analysis copy
    n_features: int = 5000         # ORB keypoint budget
    ratio: float = 0.80            # Lowe ratio threshold (best / second best)
    max_hamming: int = 64          # absolute descriptor distance cap (of 256 bits)
    min_displacement: float = 24.0  # min pixel distance (analysis scale) between a matched pair
    min_matches: int = 6           # min inlier pairs for a cluster to count
    ransac_threshold: float = 3.0  # px reprojection tolerance (analysis scale)
    max_regions: int = 5           # max clusters returned
    min_keypoints: int = 50        # fewer keypoints => inconclusive (insufficient texture)
    min_region_area: float = 200.0  # min hull area (analysis px^2) per side
    repeat_limit: int = 6          # >= this many distinct clusters => repetitive pattern, inconclusive


@dataclass
class Region:
    id: int
    matches: int
    mean_hamming_distance: float
    transform: dict
    region_a: dict
    region_b: dict


@dataclass
class DetectionOutput:
    status: str
    status_reason: str
    original_size: tuple[int, int]  # (width, height)
    analysis_size: tuple[int, int]
    scale: float
    keypoints: int
    matches_before_filtering: int
    matches_after_descriptor_filtering: int
    matches_retained: int
    regions: list[Region]
    warnings: list[str]
    processing_ms: float
    settings: dict
    annotated: np.ndarray  # RGB uint8
    mask: np.ndarray       # HxW uint8 0/255
    heatmap: np.ndarray    # RGB uint8
    accepted_clusters: int = 0
    rejected_clusters: int = 0


# ----------------------------------------------------------------------------------------
def _match(des: np.ndarray, pts: np.ndarray, p: CopyMoveParams):
    """Return (pairs [(i, j, dist)], n_candidates). Pairs are unordered-unique."""
    n = len(des)
    k = min(30, n)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = bf.knnMatch(des, des, k=k)
    candidates = 0
    seen: dict[tuple[int, int], float] = {}
    min_d2 = p.min_displacement ** 2
    for i, row in enumerate(knn):
        valid = []
        for m in row:
            j = m.trainIdx
            if j == i:
                continue
            d = pts[i] - pts[j]
            if d[0] * d[0] + d[1] * d[1] < min_d2:
                continue  # self, same-location duplicate, or too close to be a meaningful copy
            valid.append(m)
            if len(valid) == 2:
                break
        if not valid:
            continue
        candidates += 1
        if len(valid) < 2:
            continue
        best, second = valid
        if best.distance > p.max_hamming:
            continue
        # Lowe ratio test: filter out ambiguous matches unless best match is an exact/near-exact clone (<= 16 bits difference)
        if best.distance > 16 and best.distance >= p.ratio * second.distance:
            continue
        key = (min(i, best.trainIdx), max(i, best.trainIdx))
        if key not in seen or best.distance < seen[key]:
            seen[key] = best.distance
    pairs = [(a, b, d) for (a, b), d in seen.items()]
    return pairs, candidates


def _hull_polygon(points: np.ndarray, pad: float, shape: tuple[int, int]) -> tuple[np.ndarray, dict]:
    """Padded hull polygon (Nx2 int) and bbox dict for keypoints, clamped to image shape (h, w)."""
    h, w = shape
    hull = cv2.convexHull(points.astype(np.float32)).reshape(-1, 2)
    m = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(m, np.round(hull).astype(np.int32), 255)
    r = max(1, int(round(pad)))
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnt = max(cnts, key=cv2.contourArea)
    poly = cv2.approxPolyDP(cnt, max(1.0, 0.01 * cv2.arcLength(cnt, True)), True).reshape(-1, 2)
    x, y, bw, bh = cv2.boundingRect(cnt)
    return poly, {"x": int(x), "y": int(y), "width": int(bw), "height": int(bh)}


def _bbox_overlap(a: dict, b: dict) -> float:
    ix = max(0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]))
    iy = max(0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
    smaller = max(1, min(a["width"] * a["height"], b["width"] * b["height"]))
    return ix * iy / smaller


def _cluster(pairs, pts, p: CopyMoveParams, rng_seed: int = 0):
    """Sequential RANSAC over directed copies of the unordered pairs."""
    remaining = list(range(len(pairs)))
    clusters = []
    cv2.setRNGSeed(rng_seed)
    for _ in range(p.max_regions + p.repeat_limit):
        if len(remaining) < p.min_matches:
            break
        src, dst = [], []
        for idx in remaining:
            a, b, _d = pairs[idx]
            src += [pts[a], pts[b]]
            dst += [pts[b], pts[a]]
        src = np.asarray(src, np.float32)
        dst = np.asarray(dst, np.float32)
        M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                             ransacReprojThreshold=p.ransac_threshold,
                                             maxIters=3000, confidence=0.995)
        if M is None or inl is None:
            break
        inl = inl.reshape(-1).astype(bool)
        # row 2r is a->b, row 2r+1 is b->a for remaining[r]; a pair is an inlier if either direction fits
        pair_in = inl[0::2] | inl[1::2]
        members = [remaining[r] for r in np.flatnonzero(pair_in)]
        if len(members) < p.min_matches:
            break
        clusters.append((M, members))
        keep = set(members)
        remaining = [i for i in remaining if i not in keep]
    return clusters


def _transform_summary(M: np.ndarray) -> dict:
    a, b = M[0, 0], M[1, 0]
    scale = float(np.hypot(a, b))
    return {
        "type": "similarity",
        "translation_x": float(M[0, 2]),
        "translation_y": float(M[1, 2]),
        "rotation_degrees": float(np.degrees(np.arctan2(b, a))),
        "scale": scale,
    }


def detect_copy_move(rgb: np.ndarray, params: CopyMoveParams | None = None) -> DetectionOutput:
    """Run the detector on an HxWx3 uint8 RGB array."""
    p = params or CopyMoveParams()
    t0 = time.perf_counter()
    H, W = rgb.shape[:2]
    warnings: list[str] = []

    scale = min(1.0, p.max_dimension / max(H, W))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if scale < 1.0:
        gray = cv2.resize(gray, (max(1, round(W * scale)), max(1, round(H * scale))), interpolation=cv2.INTER_AREA)
        warnings.append(f"Analysis was run on a copy downscaled by {scale:.3f}; coordinates are mapped back to the original size.")
    ah, aw = gray.shape

    orb = cv2.ORB_create(nfeatures=p.n_features, scaleFactor=1.2, nlevels=8, edgeThreshold=15,
                         patchSize=31, fastThreshold=10)
    kps, des = orb.detectAndCompute(gray, None)
    n_kp = len(kps) if kps else 0

    def finish(status, reason, regions, retained, before, after, pts_a, pts_b, mask, accepted=0, rejected=0):
        annotated = _annotate(rgb, regions, pts_a, pts_b)
        heat = _heatmap(rgb, pts_a + pts_b)
        log.info(
            "Copy-move finished: status=%s, keypoints=%d, raw_matches=%d, filtered_matches=%d, "
            "retained=%d, accepted_regions=%d, rejected=%d (reason: %s)",
            status, n_kp, before, after, retained, len(regions), rejected, reason
        )
        return DetectionOutput(
            status=status, status_reason=reason, original_size=(W, H), analysis_size=(aw, ah), scale=scale,
            keypoints=n_kp, matches_before_filtering=before, matches_after_descriptor_filtering=after,
            matches_retained=retained, regions=regions, warnings=warnings,
            processing_ms=round((time.perf_counter() - t0) * 1000, 1), settings=asdict(p),
            annotated=annotated, mask=mask, heatmap=heat,
            accepted_clusters=accepted, rejected_clusters=rejected)

    empty_mask = np.zeros((H, W), np.uint8)
    if des is None or n_kp < p.min_keypoints:
        return finish("inconclusive",
                      f"Only {n_kp} ORB keypoints were found (minimum {p.min_keypoints}); the image has too little texture for this method.",
                      [], 0, 0, 0, [], [], empty_mask)

    pts = np.array([k.pt for k in kps], np.float32)
    pairs, candidates = _match(des, pts, p)
    after = len(pairs)
    log.debug("ORB matching: keypoints=%d, candidates=%d, pairs_after_filtering=%d", n_kp, candidates, after)
    if after < p.min_matches:
        return finish("no_candidate_regions_found",
                      f"Only {after} descriptor matches survived filtering (minimum {p.min_matches} needed to form a cluster).",
                      [], 0, candidates, after, [], [], empty_mask)

    raw_clusters = _cluster(pairs, pts, p)
    regions: list[Region] = []
    mask = np.zeros((H, W), np.uint8)
    all_a: list[np.ndarray] = []
    all_b: list[np.ndarray] = []
    retained = 0
    rejected = 0
    inv = 1.0 / scale
    pad = 16.0 * inv  # ~ORB patch radius (patchSize 31 / 2)
    for M, members in raw_clusters:
        # Orient each pair so "a" points are on one consistent side under the fitted transform.
        pa, pb, dists = [], [], []
        for idx in members:
            i, j, d = pairs[idx]
            fwd = np.linalg.norm(M[:, :2] @ pts[i] + M[:, 2] - pts[j])
            bwd = np.linalg.norm(M[:, :2] @ pts[j] + M[:, 2] - pts[i])
            if fwd <= bwd:
                pa.append(pts[i]); pb.append(pts[j])
            else:
                pa.append(pts[j]); pb.append(pts[i])
            dists.append(d)
        pa = np.asarray(pa, np.float32) * inv
        pb = np.asarray(pb, np.float32) * inv

        # Prune distant spatial outliers if cluster has sufficient points,
        # ensuring bounding box and convex hull tightly conform to the duplicated object.
        if len(pa) >= 6:
            med_a = np.median(pa, axis=0)
            dists_a = np.linalg.norm(pa - med_a, axis=1)
            mad_a = np.median(np.abs(dists_a - np.median(dists_a)))
            thresh_a = max(40.0 * inv, np.median(dists_a) + 3.0 * (mad_a * 1.4826 + 1e-6))

            med_b = np.median(pb, axis=0)
            dists_b = np.linalg.norm(pb - med_b, axis=1)
            mad_b = np.median(np.abs(dists_b - np.median(dists_b)))
            thresh_b = max(40.0 * inv, np.median(dists_b) + 3.0 * (mad_b * 1.4826 + 1e-6))

            sp_inliers = (dists_a <= thresh_a) & (dists_b <= thresh_b)
            if sp_inliers.sum() >= 4:
                pa = pa[sp_inliers]
                pb = pb[sp_inliers]
                dists = [dists[idx_d] for idx_d, keep in enumerate(sp_inliers) if keep]

        if len(pa) < 3:
            rejected += 1
            continue
        area_a = cv2.contourArea(cv2.convexHull(pa)) * scale ** 2
        area_b = cv2.contourArea(cv2.convexHull(pb)) * scale ** 2
        if min(area_a, area_b) < p.min_region_area:
            rejected += 1
            continue
        poly_a, box_a = _hull_polygon(pa, pad, (H, W))
        poly_b, box_b = _hull_polygon(pb, pad, (H, W))
        tr = _transform_summary(M)
        trans_dist = float(np.hypot(tr["translation_x"], tr["translation_y"]))
        ov = _bbox_overlap(box_a, box_b)
        # Discard trivial self-matches or extreme bounding-box overlaps
        if ov > 0.75 or (ov > 0.5 and trans_dist < p.min_displacement):
            rejected += 1
            continue
        if not 0.5 <= tr["scale"] <= 2.0:
            rejected += 1
            continue
        if len(regions) >= p.max_regions:
            warnings.append(f"More than {p.max_regions} clusters were found; only the first {p.max_regions} are reported.")
            break
        rid = len(regions) + 1
        for poly in (poly_a, poly_b):
            cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
        regions.append(Region(
            id=rid, matches=len(pa), mean_hamming_distance=round(float(np.mean(dists)), 2),
            transform=tr,
            region_a={"bbox": box_a, "polygon": poly_a.tolist()},
            region_b={"bbox": box_b, "polygon": poly_b.tolist()},
        ))
        all_a.append(pa); all_b.append(pb)
        retained += len(pa)
    if rejected:
        warnings.append(f"{rejected} candidate cluster(s) were discarded as too small, overlapping, or implausible.")

    if not regions:
        return finish("no_candidate_regions_found",
                      "Descriptor matches were found but none formed a geometrically consistent, sufficiently large cluster.",
                      [], 0, candidates, after, [], [], empty_mask, accepted=0, rejected=rejected)

    if len(raw_clusters) >= p.repeat_limit:
        warnings.append(f"{len(raw_clusters)} distinct consistent transforms were found, which usually indicates a repetitive pattern rather than a single duplicated region.")
        status = "inconclusive"
        reason = "Many distinct duplicated-looking structures were found; the image likely contains repeated patterns, so this method cannot separate natural repetition from manipulation."
    else:
        status = "candidate_regions_found"
        reason = (f"{len(regions)} cluster(s) of mutually consistent ORB matches were found "
                  f"({retained} retained matches). These are candidates only and need visual review.")
    return finish(status, reason, regions, retained, candidates, after, all_a, all_b, mask, accepted=len(regions), rejected=rejected)


# ----------------------------------------------------------------------------------------
_PALETTE = [(0, 200, 255), (255, 140, 0), (80, 220, 100), (255, 70, 160), (170, 120, 255)]  # RGB


def _annotate(rgb: np.ndarray, regions: list[Region], pts_a: list, pts_b: list) -> np.ndarray:
    """Original with region polygons/boxes: solid = region A, dashed-style thin = region B, plus match lines."""
    out = rgb.copy()
    H, W = out.shape[:2]
    t = max(2, round(max(H, W) / 450))
    for r in regions:
        color = _PALETTE[(r.id - 1) % len(_PALETTE)]
        for side, label, thick in ((r.region_a, "A", t), (r.region_b, "B", max(1, t - 1))):
            poly = np.asarray(side["polygon"], np.int32)
            cv2.polylines(out, [poly], True, color, thick, cv2.LINE_AA)
            b = side["bbox"]
            _dashed_rect(out, b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"], color, max(1, t - 1))
            _label(out, f"{r.id}{label}", b["x"], b["y"], color, t)
    lt = max(1, t - 1)
    for r, arr_a, arr_b in zip(regions, pts_a, pts_b):
        color = _PALETTE[(r.id - 1) % len(_PALETTE)]
        for a, b in zip(arr_a, arr_b):
            cv2.line(out, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), color, lt, cv2.LINE_AA)
            cv2.circle(out, (int(a[0]), int(a[1])), t + 1, color, -1, cv2.LINE_AA)
            cv2.circle(out, (int(b[0]), int(b[1])), t + 1, color, -1, cv2.LINE_AA)
    return out


def _dashed_rect(img, x0, y0, x1, y1, color, thick, dash=14):
    for (xa, ya, xb, yb) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        length = int(np.hypot(xb - xa, yb - ya))
        for s in range(0, length, dash * 2):
            e = min(s + dash, length)
            p1 = (int(xa + (xb - xa) * s / max(length, 1)), int(ya + (yb - ya) * s / max(length, 1)))
            p2 = (int(xa + (xb - xa) * e / max(length, 1)), int(ya + (yb - ya) * e / max(length, 1)))
            cv2.line(img, p1, p2, color, thick, cv2.LINE_AA)


def _label(img, text, x, y, color, t):
    fs = 0.5 + 0.12 * t
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, max(1, t - 1))
    y0 = max(th + base + 2, y)
    cv2.rectangle(img, (x, y0 - th - base - 2), (x + tw + 6, y0 + 2), color, -1)
    cv2.putText(img, text, (x + 3, y0 - base // 2), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), max(1, t - 1), cv2.LINE_AA)


def _heatmap(rgb: np.ndarray, point_sets: list) -> np.ndarray:
    """Overlay of retained-match keypoint density (Gaussian-smoothed). Not a probability map.

    Density is computed on a reduced-resolution grid and the blend is done in row chunks so
    peak memory stays close to a few copies of the image even for tens of megapixels.
    """
    H, W = rgb.shape[:2]
    if not point_sets:
        return rgb.copy()
    s = min(1.0, 1024 / max(H, W))
    h, w = max(1, round(H * s)), max(1, round(W * s))
    acc = np.zeros((h, w), np.float32)
    for pts in point_sets:
        xs = np.clip(np.round(pts[:, 0] * s).astype(int), 0, w - 1)
        ys = np.clip(np.round(pts[:, 1] * s).astype(int), 0, h - 1)
        np.add.at(acc, (ys, xs), 1.0)
    acc = cv2.GaussianBlur(acc, (0, 0), max(4.0, 0.025 * max(h, w)))
    if acc.max() <= 0:
        return rgb.copy()
    norm = acc / acc.max()
    if s < 1.0:
        norm = cv2.resize(norm, (W, H), interpolation=cv2.INTER_LINEAR)
    out = np.empty_like(rgb)
    for y in range(0, H, 256):
        n = norm[y:y + 256]
        color = cv2.cvtColor(cv2.applyColorMap((n * 255).astype(np.uint8), cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)
        a = (0.7 * np.clip(n * 1.5, 0, 1))[..., None]
        out[y:y + 256] = (rgb[y:y + 256] * (1 - a) + color * a).astype(np.uint8)
    return out
