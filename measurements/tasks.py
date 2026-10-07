from pathlib import Path

from celery import shared_task


@shared_task(name="measurements.process_uploaded_file", acks_late=True)
def process_uploaded_file(record_id: str, path: str) -> None:
    """Celery entry point; the real work lives in jobs.run so every backend shares it."""
    from . import jobs

    jobs.run(record_id, Path(path))
