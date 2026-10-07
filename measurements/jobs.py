"""Optional background processing (GEO_ASYNC=1).

A small in-process thread pool: no broker to run, which keeps the project easy to start.
Limitation: queued jobs are lost if the server restarts, and it does not scale beyond one
process. For that, replace ``submit`` with a Celery/RQ task that calls ``run``.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections

from .models import UploadedFile
from .services.processor import process_file

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=settings.ASYNC_WORKERS, thread_name_prefix="geo-worker")


def run(record_id, path: Path) -> None:
    """Process one uploaded file. Safe to call directly (used by tests and other runners)."""
    try:
        record = UploadedFile.objects.get(pk=record_id)
    except UploadedFile.DoesNotExist:
        log.warning("File %s was deleted before processing started", record_id)
        return
    process_file(record, path)


def _thread_target(record_id, path: Path) -> None:
    try:
        run(record_id, path)
    except Exception:
        log.exception("Background processing crashed for %s", record_id)
    finally:
        close_old_connections()  # worker threads own their DB connections


def submit(record_id, path: Path) -> None:
    _executor().submit(_thread_target, record_id, path)
