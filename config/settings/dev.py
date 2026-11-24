"""Local development (the manage.py default). DEBUG on, dev tools installed, safe local fallbacks."""

from config.settings.base import *  # noqa: F403
from config.settings.base import CSRF_TRUSTED_ORIGINS, INSTALLED_APPS, SECRET_KEY, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key"

if "dev_tools" not in INSTALLED_APPS:
    INSTALLED_APPS.append("dev_tools")

# The React dev server, and the local demo copy
CSRF_TRUSTED_ORIGINS += [o for o in ("http://localhost:5173", "http://localhost:5174") if o not in CSRF_TRUSTED_ORIGINS]
