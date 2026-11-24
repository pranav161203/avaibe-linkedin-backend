"""Production (gunicorn on Render, or the Docker image). Fails at start-up if a required value is missing,
rather than running with an unsafe default."""

import os

import dj_database_url

from config.settings.base import *  # noqa: F403
from config.settings.base import env_bool, env_list, env_required

DEBUG = False
SECRET_KEY = env_required("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS") or [env_required("ALLOWED_HOSTS")]
DATABASES = {"default": dj_database_url.parse(env_required("DATABASE_URL").replace("postgresql+psycopg://", "postgresql://"), conn_max_age=60, conn_health_checks=True)}

# HTTPS: the host (Render) terminates TLS. Cookies are HTTPS-only unless COOKIE_SECURE=false is set on purpose.
COOKIE_SECURE = env_bool("COOKIE_SECURE", True)
SESSION_COOKIE_SECURE = COOKIE_SECURE
CSRF_COOKIE_SECURE = COOKIE_SECURE
# Opt-in once the final domain is settled (browsers remember it): e.g. SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)

# Render (and any load balancer in front) redirects HTTP to HTTPS before requests reach Django
SILENCED_SYSTEM_CHECKS = ["security.W008"]
