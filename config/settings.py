import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
if not DEBUG and SECRET_KEY.startswith("dev-only"):
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "fuel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
    }
}

# Routes and plans are cached so repeats skip OSRM entirely. Memory is fastest for a single
# process (runserver); set CACHE_DIR to share a file cache between gunicorn workers, or
# REDIS_URL to share it across hosts.
if REDIS_URL := os.environ.get("REDIS_URL"):
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
    }
elif CACHE_DIR := os.environ.get("CACHE_DIR"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": CACHE_DIR,
            "OPTIONS": {"MAX_ENTRIES": 5000},
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fuel-route-api",
            "OPTIONS": {"MAX_ENTRIES": 5000},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("API_ANON_THROTTLE", "120/min")},
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Fuel Route Optimizer API",
    "DESCRIPTION": (
        "Plans a driving route between two US locations and picks the cheapest "
        "fuel stops for a vehicle with a 500 mile range at 10 MPG."
    ),
    "VERSION": "1.0.0",
    "PREPROCESSING_HOOKS": ["fuel.schema.hide_slashless_aliases"],
    # Highlighting a 40 KB response (route geometry) freezes Swagger UI on slower machines.
    "SWAGGER_UI_SETTINGS": {
        "syntaxHighlight": False,
        "displayRequestDuration": True,
        "defaultModelsExpandDepth": -1,
    },
}

FUEL = {
    "VEHICLE_RANGE_MILES": float(os.environ.get("VEHICLE_RANGE_MILES", 500)),
    "VEHICLE_MPG": float(os.environ.get("VEHICLE_MPG", 10)),
    "CORRIDOR_MILES": float(os.environ.get("FUEL_CORRIDOR_MILES", 10)),
    "STOP_COST_USD": float(os.environ.get("FUEL_STOP_COST_USD", 15)),
    "ORIGIN_RADIUS_MILES": float(os.environ.get("FUEL_ORIGIN_RADIUS_MILES", 25)),
    "ROUTE_SAMPLE_MILES": 0.5,
    "PLAN_CACHE_SECONDS": int(os.environ.get("PLAN_CACHE_SECONDS", 60 * 60 * 24)),
    "OSRM_BASE_URL": os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org"),
    "NOMINATIM_BASE_URL": os.environ.get(
        "NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"
    ),
    "HTTP_USER_AGENT": os.environ.get("HTTP_USER_AGENT", "fuel-route-api/1.0"),
    "HTTP_TIMEOUT_SECONDS": float(os.environ.get("HTTP_TIMEOUT_SECONDS", 15)),
    "PLACES_FILE": BASE_DIR / "data" / "us_places.csv.gz",
    "FUEL_PRICES_FILE": BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv",
    "STATION_GEOCODES_FILE": BASE_DIR / "data" / "station_geocodes.csv",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "loggers": {"fuel": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")}},
}
