import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
if not DEBUG and SECRET_KEY == "dev-only-insecure-key":
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):  # set automatically by Render
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

# Behind Render's proxy, trust its header so absolute URLs (map_url) use https.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "django.contrib.contenttypes",
    "rest_framework",
    "stations",
    "routing",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

# OpenStreetMap tile servers reject requests that carry no Referer header.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

ROOT_URLCONF = "fuelroute.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

WSGI_APPLICATION = "fuelroute.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis cache. IGNORE_EXCEPTIONS keeps the API working (uncached) if Redis is down.
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,
            "SOCKET_CONNECT_TIMEOUT": 1,
            "SOCKET_TIMEOUT": 1,
        },
    }
}
DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

# Routing provider
ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
ORS_BASE_URL = "https://api.openrouteservice.org"
ORS_TIMEOUT_SECONDS = 10

# Vehicle and planning constants
VEHICLE_RANGE_MILES = 500
VEHICLE_MPG = 10
RANGE_SAFETY_MARGIN_MILES = 25  # plans leave this much reserve, since station positions are approximate
CORRIDOR_MILES = 15
ORIGIN_FILL_WINDOW_MILES = 50
FUEL_STOP_PENALTY = 5.0  # dollars: an extra stop must save at least this much
ROUTE_CACHE_SECONDS = 60 * 60 * 24
