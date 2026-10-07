try:  # Celery is an optional dependency (only needed when GEO_ASYNC=celery)
    from .celery import app as celery_app
except ModuleNotFoundError:
    celery_app = None

__all__ = ("celery_app",)
