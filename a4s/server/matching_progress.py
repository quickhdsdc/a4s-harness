"""In-memory progress for the current matching run; derived files stay on disk."""
from __future__ import annotations

import threading
import time
import uuid

_LOCK = threading.Lock()
_jobs: dict[tuple[str, str], dict] = {}


def start(filename: str, aas: str) -> None:
    with _LOCK:
        _jobs.clear()  # One matching worker; do not accumulate old run records.
        now = time.time()
        _jobs[(filename, aas)] = {"id": uuid.uuid4().hex, "status": "running", "stage": "Preparing", "detail": "Reading extracted properties and target submodels",
            "completed": 0, "total": None, "percent": None, "properties_completed": 0, "properties_total": None,
            "started_at": now, "updated_at": now}


def update(filename: str, aas: str, *, stage: str, detail: str = "", advance: int = 0, **fields) -> None:
    with _LOCK:
        job = _jobs[(filename, aas)]
        job.update(fields, stage=stage, detail=detail, updated_at=time.time())
        job["completed"] += advance
        if job["total"]:
            job["percent"] = min(99, int(100 * job["completed"] / job["total"]))
        if job["status"] == "completed":
            job["percent"] = 100


def read(filename: str, aas: str) -> dict:
    with _LOCK:
        job = _jobs.get((filename, aas))
        if not job:
            return {"status": "idle", "percent": None, "stage": "Waiting", "detail": ""}
        return {**job, "elapsed_seconds": round((time.time() if job["status"] == "running" else job["updated_at"]) - job["started_at"], 1)}


def clear(filename: str, aas: str) -> None:
    with _LOCK:
        _jobs.pop((filename, aas), None)
