from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import BoundedSemaphore, RLock
from uuid import uuid4


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


class JobQueueFullError(RuntimeError):
    """La coda non può accettare altri lavori."""


class AnalysisJobManager:
    """
    Coda in-process con stato interrogabile.

    Il default di un worker serializza il motore e le scritture JSON, mentre
    Uvicorn continua a servire richieste di stato e file statici.
    """

    def __init__(self, worker_count=1, queue_capacity=16):
        if worker_count != 1:
            raise ValueError(
                "L'archivio JSON supporta per ora un solo worker di analisi."
            )
        if queue_capacity < 1:
            raise ValueError("queue_capacity deve essere almeno 1.")

        self.worker_count = worker_count
        self.queue_capacity = queue_capacity
        self._executor = ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="sudoku-analysis",
        )
        self._capacity = BoundedSemaphore(queue_capacity)
        self._lock = RLock()
        self._jobs = {}

    def submit(self, operation):
        if not self._capacity.acquire(blocking=False):
            raise JobQueueFullError(
                "La coda delle analisi è piena; riprova più tardi."
            )

        job_id = uuid4().hex
        record = {
            "job_id": job_id,
            "status": "queued",
            "created_at": _timestamp(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
        }

        with self._lock:
            self._jobs[job_id] = record

        try:
            self._executor.submit(self._run, job_id, operation)
        except Exception:
            with self._lock:
                self._jobs.pop(job_id, None)
            self._capacity.release()
            raise

        return self.get(job_id)

    def _run(self, job_id, operation):
        with self._lock:
            record = self._jobs[job_id]
            record["status"] = "running"
            record["started_at"] = _timestamp()

        try:
            result = operation()
        except Exception as error:
            with self._lock:
                record = self._jobs[job_id]
                record["status"] = "failed"
                record["error"] = str(error)
                record["completed_at"] = _timestamp()
        else:
            with self._lock:
                record = self._jobs[job_id]
                record["status"] = "completed"
                record["result"] = result
                record["completed_at"] = _timestamp()
        finally:
            self._capacity.release()

    def get(self, job_id):
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)

            return dict(self._jobs[job_id])

    def shutdown(self, wait=True):
        self._executor.shutdown(wait=wait, cancel_futures=False)

