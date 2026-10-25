import threading
from contextlib import contextmanager

from app.core.config import get_settings
from app.core.errors import ApiError
from app.services.artifact_store import ArtifactStore

_settings = get_settings()
store = ArtifactStore(_settings.artifact_ttl_seconds, _settings.artifact_max_entries, _settings.artifact_max_bytes)
_slots = threading.BoundedSemaphore(_settings.max_concurrent_jobs)


@contextmanager
def job_slot():
    """Bound concurrent CPU-heavy jobs; fail fast with 503 instead of queueing without limit."""
    if not _slots.acquire(timeout=_settings.job_wait_seconds):
        raise ApiError(503, "server_busy", "The server is busy. Please retry in a few seconds.")
    try:
        yield
    finally:
        _slots.release()
