"""Tests, one module per area (test_<area>.py). Shared builders live in factories.py.

Run all:      .venv\Scripts\python manage.py test
Run one area: .venv\Scripts\python manage.py test core.tests.test_planner
Tests use config/settings/test.py automatically: SQLite unless TEST_DATABASE_URL is set; never your .env database.
"""
