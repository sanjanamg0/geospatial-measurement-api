import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
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

DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": DATA_DIR / "db.sqlite3"}
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"

MAX_UPLOAD_MB = int(os.environ.get("GEO_MAX_UPLOAD_MB", "50"))

# Background processing: upload returns 202 immediately and a worker thread processes the file.
ASYNC_PROCESSING = os.environ.get("GEO_ASYNC", "0") == "1"
ASYNC_WORKERS = int(os.environ.get("GEO_ASYNC_WORKERS", "2"))

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.JSONParser",
    ],
    "UNAUTHENTICATED_USER": None,
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
