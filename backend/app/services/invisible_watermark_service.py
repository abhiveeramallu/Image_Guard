"""Invisible watermark: DCT-domain quantization index modulation (QIM) on luminance.

Payload (144 bits): version(1B) | owner length(1B) | owner ASCII padded to 12B | MAC(4B)
where MAC = HMAC-SHA256(server key, "IGWM" + first 14 bytes)[:4].

Embedding
  * Luminance Y is split into 8x8 blocks. Each block is assigned to one of L=144 "classes"
    by (block_row * 13 + block_col) mod 144, so the layout tiles periodically; the payload
    bit carried by a class is chosen by a key-seeded permutation.
  * In every block three mid-frequency DCT coefficients, (1,2), (2,1) and (2,2), are quantized onto a
    bit-dependent lattice of step DELTA (bit 0: multiples of DELTA, bit 1: offset by DELTA/2).
  * The change in Y is added equally to R, G, B (chroma unchanged), then rounded/clipped to 8 bit.
Verification
  * For each of the 64 pixel offsets of the block grid and each supported DELTA, a soft vote
    cos(2*pi*coef/DELTA) is summed per class. Offsets with strong, consistent votes are searched
    over all 144 cyclic class shifts (this also tolerates small crops); a payload is accepted only
    if its MAC is valid.

This is robust, within limits, to PNG re-save, moderate JPEG recompression, mild noise and small crops. It is NOT robust to
resizing, rotation, heavy compression, screenshots or deliberate removal. A valid MAC shows that someone holding the
server key embedded this payload; it is not proof of ownership or of image integrity.
"""
import hashlib
import hmac
import random
from dataclasses import dataclass

import numpy as np

ALGORITHM = "dct-qim-hmac"
VERSION = 1
BLOCK = 8
L = 144
K1 = 13
COEFS = ((1, 2), (2, 1), (2, 2))
STRENGTHS = {"low": 16.0, "standard": 24.0, "high": 32.0}
OWNER_MAX = 12
MIN_COPIES = 6
ANALYSIS_SIDE = 1024
OFFSET_STRENGTH_MIN = 0.12      # minimum vote strength before searching class shifts for a valid MAC
INCONCLUSIVE_STRENGTH_MIN = 0.35  # a header-only match counts as 'damaged watermark' only with strong votes

LIMITATIONS = [
    "Detects/verifies a payload embedded by this server's key only; a valid check shows key-holder embedding, not ownership or image integrity.",
    "Survives lossless re-saving, moderate JPEG recompression, mild noise and small crops in synthetic tests (see docs/TESTING.md); it does not survive resizing, rotation or heavy compression.",
    "A determined attacker can remove or overwrite the watermark; failure to find one does not mean the image never carried one.",
    "Use PNG (lossless) output to preserve the watermark; JPEG output is re-encoded at quality 95.",
]


class WatermarkError(ValueError):
    pass


def _dct_matrix() -> np.ndarray:
    k = np.arange(BLOCK)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * BLOCK)) * np.sqrt(2.0 / BLOCK)
    m[0] /= np.sqrt(2)
    return m.astype(np.float64)


D = _dct_matrix()


# ---- payload -----------------------------------------------------------------------------
def _mac(key: bytes, head: bytes) -> bytes:
    return hmac.new(key, b"IGWM" + head, hashlib.sha256).digest()[:4]


def validate_owner(owner: str) -> str:
    if not 1 <= len(owner) <= OWNER_MAX or not all(32 <= ord(c) < 127 for c in owner):
        raise WatermarkError(f"Owner/payload must be 1-{OWNER_MAX} printable ASCII characters.")
    return owner


def build_payload(owner: str, key: bytes) -> bytes:
    owner = validate_owner(owner)
    head = bytes([VERSION, len(owner)]) + owner.encode().ljust(OWNER_MAX, b"\0")
    return head + _mac(key, head)


def parse_payload(data: bytes, key: bytes) -> tuple[bool, str | None, bool]:
    """Return (header_ok, owner, mac_ok)."""
    if len(data) != 18 or data[0] != VERSION or not 1 <= data[1] <= OWNER_MAX:
        return False, None, False
    head = data[:14]
    body = data[2:2 + data[1]]
    if not all(32 <= b < 127 for b in body) or any(data[2 + data[1]:14]):
        return False, None, False
    return True, body.decode(), hmac.compare_digest(_mac(key, head), data[14:])


def _perm(key: bytes) -> list[int]:
    seed = int.from_bytes(hashlib.sha256(b"IGWM-perm" + key).digest()[:8], "big")
    p = list(range(L))
    random.Random(seed).shuffle(p)
    return p


def _bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, np.uint8))


# ---- block transforms ------------------------------------------------------------------------
def _blocks(y: np.ndarray, oy: int = 0, ox: int = 0, max_side: int | None = None) -> np.ndarray:
    h = (y.shape[0] - oy) // BLOCK * BLOCK
    w = (y.shape[1] - ox) // BLOCK * BLOCK
    if max_side:
        h, w = min(h, max_side // BLOCK * BLOCK), min(w, max_side // BLOCK * BLOCK)
    v = y[oy:oy + h, ox:ox + w]
    return v.reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).transpose(0, 2, 1, 3)  # (br, bc, 8, 8)


def _classes(nbr: int, nbc: int) -> np.ndarray:
    return (np.arange(nbr)[:, None] * K1 + np.arange(nbc)[None, :]) % L


def _luma(rgb: np.ndarray) -> np.ndarray:
    f = rgb.astype(np.float64)
    return 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]


# ---- embed ----------------------------------------------------------------------------------------
@dataclass
class EmbedResult:
    image: np.ndarray
    psnr_db: float
    blocks: int
    copies_per_bit: float
    delta: float


def embed(rgb: np.ndarray, owner: str, key: bytes, strength: str = "standard") -> EmbedResult:
    if strength not in STRENGTHS:
        raise WatermarkError(f"strength must be one of {sorted(STRENGTHS)}.")
    delta = STRENGTHS[strength]
    H, W = rgb.shape[:2]
    nbr, nbc = H // BLOCK, W // BLOCK
    if nbr * nbc < L * MIN_COPIES:
        raise WatermarkError("Image is too small to carry the watermark reliably (needs about 256x256 pixels).")
    payload = _bits(build_payload(owner, key))
    perm = _perm(key)
    bit_of_class = np.zeros(L, np.uint8)
    for j in range(L):
        bit_of_class[perm[j]] = payload[j]

    y = _luma(rgb)
    blk = _blocks(y)
    coef = np.einsum("ij,rcjk,lk->rcil", D, blk, D, optimize=True)
    bits = bit_of_class[_classes(nbr, nbc)]
    for (u, v) in COEFS:
        c = coef[:, :, u, v]
        off = bits * (delta / 2.0)
        coef[:, :, u, v] = np.round((c - off) / delta) * delta + off
    new_blk = np.einsum("ji,rcjk,kl->rcil", D, coef, D, optimize=True)
    dy = np.zeros_like(y)
    dy[:nbr * BLOCK, :nbc * BLOCK] = (new_blk - blk).transpose(0, 2, 1, 3).reshape(nbr * BLOCK, nbc * BLOCK)
    out = np.clip(np.round(rgb.astype(np.float64) + dy[..., None]), 0, 255).astype(np.uint8)
    mse = float(np.mean((out.astype(np.float64) - rgb.astype(np.float64)) ** 2))
    psnr = 99.0 if mse == 0 else float(10 * np.log10(255.0 ** 2 / mse))
    return EmbedResult(out, round(psnr, 2), nbr * nbc, round(nbr * nbc / L, 1), delta)


# ---- verify ---------------------------------------------------------------------------------------
@dataclass
class VerifyResult:
    status: str  # verified | inconclusive | not_detected
    owner: str | None
    integrity_verified: bool
    bit_strength: float
    grid_offset: tuple[int, int] | None
    class_shift: int | None
    delta: float | None
    offsets_searched: int


def verify(rgb: np.ndarray, key: bytes) -> VerifyResult:
    H, W = rgb.shape[:2]
    if (H // BLOCK) * (W // BLOCK) < L * MIN_COPIES // 2:
        raise WatermarkError("Image is too small to verify reliably.")
    y = _luma(rgb)
    perm = np.array(_perm(key))
    best_strength, best = 0.0, None
    inconclusive: tuple | None = None
    searched = 0
    for oy in range(BLOCK):
        for ox in range(BLOCK):
            blk = _blocks(y, oy, ox, ANALYSIS_SIDE)
            if blk.shape[0] * blk.shape[1] < L * 2:
                continue
            searched += 1
            coef = np.stack([np.einsum("j,rcjk,k->rc", D[u], blk, D[v]) for (u, v) in COEFS], axis=-1)  # (br, bc, 3)
            cls = _classes(blk.shape[0], blk.shape[1]).reshape(-1)
            counts = np.bincount(cls, minlength=L) * len(COEFS)
            flat = coef.reshape(-1, len(COEFS))
            for delta in STRENGTHS.values():
                s = np.cos(2 * np.pi * flat / delta).sum(axis=1)
                S = np.bincount(cls, weights=s, minlength=L) / np.maximum(counts, 1)
                strength = float(np.mean(np.abs(S)))
                best_strength = max(best_strength, strength)
                if strength < OFFSET_STRENGTH_MIN:
                    continue
                bits_pre = (S < 0).astype(np.uint8)
                for k in range(L):
                    bits = bits_pre[(perm + k) % L]
                    hdr_ok, owner, mac_ok = parse_payload(np.packbits(bits).tobytes(), key)
                    if mac_ok:
                        return VerifyResult("verified", owner, True, round(strength, 3), (oy, ox), k, delta, searched)
                    if hdr_ok and strength >= INCONCLUSIVE_STRENGTH_MIN and (inconclusive is None or strength > inconclusive[0]):
                        inconclusive = (strength, (oy, ox), k, delta)
    if inconclusive:
        st, off, k, d = inconclusive
        return VerifyResult("inconclusive", None, False, round(st, 3), off, k, d, searched)
    return VerifyResult("not_detected", None, False, round(best_strength, 3), None, None, None, searched)
