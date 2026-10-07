import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "measurements",
]

MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

ROOT_URLCONF = "geoproject.urls"
WSGI_APPLICATION = "geoproject.wsgi.application"

# Runtime data (SQLite DB + uploaded files) lives outside the source tree.
DATA_DIR = Path(os.environ.get("GEO_DATA_DIR", BASE_DIR / "data"))
UPLOADS_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _database_from_url(url: str) -> dict:
    """Parse GEO_DATABASE_URL, e.g. postgres://user:pass@host:5432/dbname (PostgreSQL only)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql", "postgis"):
        raise ValueError("GEO_DATABASE_URL must start with postgres:// or postgresql://")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": parsed.port or "",
    }


DATABASE_URL = os.environ.get("GEO_DATABASE_URL", "")
DATABASES = {
    "default": _database_from_url(DATABASE_URL)
    if DATABASE_URL
    else {"ENGINE": "django.db.backends.sqlite3", "NAME": DATA_DIR / "db.sqlite3"}
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"

MAX_UPLOAD_MB = int(os.environ.get("GEO_MAX_UPLOAD_MB", "50"))

# Background processing (upload returns 202 and a worker processes the file):
#   GEO_ASYNC=1 or thread -> in-process thread pool;  GEO_ASYNC=celery -> Celery + broker.
ASYNC_BACKEND = {"1": "thread", "thread": "thread", "celery": "celery"}.get(
    os.environ.get("GEO_ASYNC", "0").lower(), "none"
)
ASYNC_PROCESSING = ASYNC_BACKEND != "none"
ASYNC_WORKERS = int(os.environ.get("GEO_ASYNC_WORKERS", "2"))
CELERY_BROKER_URL = os.environ.get("GEO_CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_TASK_IGNORE_RESULT = True

# Authentication: with GEO_REQUIRE_AUTH=1 every endpoint needs a token and users only see
# their own files. Off by default so the API can be tried with plain curl.
REQUIRE_AUTH = os.environ.get("GEO_REQUIRE_AUTH", "0") == "1"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",  # curl -d "key=value"
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["measurements.permissions.AuthIfRequired"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Geospatial File Measurement API",
    "DESCRIPTION": (
        "Upload a zipped Shapefile or KML and get per-feature area and length in metres."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
