"""Settings shared by every environment. Environment files (dev.py, prod.py, test.py) import this and change
only what differs. Pick one with DJANGO_SETTINGS_MODULE:

    config.settings.dev    manage.py default: DEBUG on, dev tools, local fallbacks
    config.settings.prod   wsgi/asgi default (gunicorn, Render, Docker): fails fast on missing secrets
    config.settings.test   used automatically by `manage.py test`

All secrets and environment-specific values come from the environment or .env (see .env.example). Never put a
secret in these files.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set (see .env.example)")
    return value


DEBUG = False
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CORS_ORIGINS = env_list("CORS_ORIGINS", "http://localhost:5173")
# Browser origins allowed to send changes (the React app). In development, also the local demo copy.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", ",".join(CORS_ORIGINS))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
]

# The mock LinkedIn API and demo-data commands (dev_tools/). Dev and test settings always add them;
# elsewhere only when MOCK_LINKEDIN=1. Never set it in production.
MOCK_LINKEDIN = os.getenv("MOCK_LINKEDIN") == "1"
if MOCK_LINKEDIN:
    INSTALLED_APPS.append("dev_tools")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.common.middleware.RequestIDMiddleware",  # X-Request-ID on every response and log line
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.auth.middleware.SettingsCompanyMiddleware",  # which company's Settings apply, reset per request
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
# The React app calls /api/accounts (no trailing slash): don't redirect
APPEND_SLASH = False

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

# DATABASE_URL e.g. postgresql://user:pass@localhost:5432/avaibe_django  (or sqlite:///path for tests)
_db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/avaibe_django")
_db_url = _db_url.replace("postgresql+psycopg://", "postgresql://")  # accept the old SQLAlchemy-style URL too
DATABASES = {"default": dj_database_url.parse(_db_url, conn_max_age=60)}

AUTH_USER_MODEL = "core.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

# Passwords are hashed, never encrypted: a one-way Argon2id hash with a random salt per password, so nobody (us
# included) can turn a stored value back into the password. Signing in hashes what was typed and compares.
# The other hashers only read older hashes; Django re-hashes those with Argon2id at the person's next sign-in.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Sessions: httpOnly cookie, Lax (sent on the Microsoft redirect back, not on cross-site requests)
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "7"))
SESSION_COOKIE_AGE = SESSION_DAYS * 86400
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
COOKIE_SECURE = env_bool("COOKIE_SECURE", False)  # true when served over HTTPS
# Hosting (Render) terminates HTTPS in front of Django and says so in this header
if env_bool("BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = COOKIE_SECURE
CSRF_COOKIE_SECURE = COOKIE_SECURE
CSRF_COOKIE_SAMESITE = "Lax"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # everything is stored in UTC; UAE time is applied when displaying/analysing
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.auth.authentication.AppAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["core.auth.authentication.IsSignedIn"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "EXCEPTION_HANDLER": "core.api.errors.exception_handler",
    # The API uses ?format= for the post format (image, video…); don't let DRF treat it as a renderer choice
    "URL_FORMAT_OVERRIDE": None,
    "UNAUTHENTICATED_USER": None,
}

# Logs go to stdout (the host collects them). Every line carries the request ID, so one request's lines can be
# found together; core.request logs one line per API call (method, path, status, duration).
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "core.common.middleware.RequestIDLogFilter"}},
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard", "filters": ["request_id"]},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.server": {"level": "WARNING"},  # runserver's own access lines: core.request already logs them
    },
}

# Outgoing email (invitations), over SMTP: Microsoft 365, Google Workspace or any provider. Off until EMAIL_HOST
# and DEFAULT_FROM_EMAIL are set; until then the app shows the invitation link to copy instead.
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)  # STARTTLS on 587
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)  # implicit TLS on 465 (use one or the other)
EMAIL_TIMEOUT = 10  # seconds: a slow mail server must not hold up the request for long
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "")
