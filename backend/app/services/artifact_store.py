"""In-memory, TTL-bounded store for detection artifacts. Nothing is written to disk."""
import re
import secrets
import threading
import time

ALLOWED_ARTIFACTS = {
    "annotated": ("image/png", "png"),
    "mask": ("image/png", "png"),
    "heatmap": ("image/png", "png"),
    "report.json": ("application/json", "json"),
    "report.html": ("text/html; charset=utf-8", "html"),
}
_METHOD_ARTIFACT = re.compile(r"^(copy_move|splicing|localization)\.(annotated|mask|heatmap|overlay|score)(\.png)?$")
EXTRA_ARTIFACTS = {"analysis.json": ("application/json", "json"),
                   "watermarked.png": ("image/png", "png"), "watermarked.jpg": ("image/jpeg", "jpg")}
ATTACK_LAB_ARTIFACTS = {
    "original.png": ("image/png", "png"),
    "original.jpg": ("image/jpeg", "jpg"),
    "baseline.png": ("image/png", "png"),
    "baseline.jpg": ("image/jpeg", "jpg"),
    "modified.png": ("image/png", "png"),
    "modified.jpg": ("image/jpeg", "jpg"),
    "modified_image.png": ("image/png", "png"),
    "ground_truth.png": ("image/png", "png"),
    "ground_truth_mask.png": ("image/png", "png"),
    "experiment_report.json": ("application/json", "json"),
    "experiment_report.html": ("text/html; charset=utf-8", "html"),
}


def artifact_media(name: str) -> tuple[str, str] | None:
    """Media type and extension for an allow-listed artifact name, else None."""
    if name in ALLOWED_ARTIFACTS:
        return ALLOWED_ARTIFACTS[name]
    if name in EXTRA_ARTIFACTS:
        return EXTRA_ARTIFACTS[name]
    if name in ATTACK_LAB_ARTIFACTS:
        return ATTACK_LAB_ARTIFACTS[name]
    if _METHOD_ARTIFACT.match(name):
        return "image/png", "png"
    return None


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class ArtifactStore:
    def __init__(self, ttl_seconds: int, max_entries: int, max_bytes: int):
        self.ttl, self.max_entries, self.max_bytes = ttl_seconds, max_entries, max_bytes
        self._items: dict[str, tuple[float, dict[str, bytes], int]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(16)

    def _purge(self, now: float) -> None:
        for k in [k for k, (exp, _, _) in self._items.items() if exp <= now]:
            del self._items[k]
        total = sum(sz for _, _, sz in self._items.values())
        while self._items and (len(self._items) > self.max_entries or total > self.max_bytes):
            oldest = min(self._items, key=lambda k: self._items[k][0])
            total -= self._items[oldest][2]
            del self._items[oldest]

    def put(self, analysis_id: str, files: dict[str, bytes]) -> None:
        size = sum(len(v) for v in files.values())
        with self._lock:
            now = time.time()
            self._items[analysis_id] = (now + self.ttl, files, size)
            self._purge(now)

    def get(self, analysis_id: str, name: str) -> bytes | None:
        if not _ID_RE.match(analysis_id) or artifact_media(name) is None:
            return None
        with self._lock:
            self._purge(time.time())
            item = self._items.get(analysis_id)
            return item[1].get(name) if item else None
