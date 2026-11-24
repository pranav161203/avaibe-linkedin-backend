"""Tests (`manage.py test` picks this automatically). SQLite unless TEST_DATABASE_URL is set (CI uses PostgreSQL),
so a developer's .env never points the tests at a real database."""

import os

import dj_database_url

from config.settings.base import *  # noqa: F403
from config.settings.base import INSTALLED_APPS, LOGGING

DEBUG = False
SECRET_KEY = "test-only-key"
if "dev_tools" not in INSTALLED_APPS:
    INSTALLED_APPS.append("dev_tools")

DATABASES = {"default": dj_database_url.parse(os.getenv("TEST_DATABASE_URL", "sqlite:///test.sqlite3"))}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast; tests only
LOGGING = {**LOGGING, "root": {"handlers": ["console"], "level": "WARNING"}}
