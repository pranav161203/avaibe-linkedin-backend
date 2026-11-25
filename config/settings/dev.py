"""Local development (the manage.py default). DEBUG on, dev tools installed, safe local fallbacks."""

from config.settings.base import *  # noqa: F403
from config.settings.base import CSRF_TRUSTED_ORIGINS, INSTALLED_APPS, SECRET_KEY, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key"

if "dev_tools" not in INSTALLED_APPS:
    INSTALLED_APPS.append("dev_tools")

# The React dev servers on this machine (main copy, demo copy, Test2 copy), by name and by address
_LOCAL = [f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (5173, 5174, 5175)]
CSRF_TRUSTED_ORIGINS += [o for o in _LOCAL if o not in CSRF_TRUSTED_ORIGINS]
