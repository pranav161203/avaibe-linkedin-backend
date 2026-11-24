# Production image for the Django API. Build: docker build -t avaibe-linkedin-backend .
# Run:  docker run --env-file .env.production -p 8000:8000 avaibe-linkedin-backend
# Needs DJANGO_SECRET_KEY, DATABASE_URL and ALLOWED_HOSTS (config/settings/prod.py stops at start-up without them).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Static files (the admin's CSS/JS) are collected at build time; WhiteNoise serves them
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=sqlite:////tmp/build.db ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput \
 && useradd --create-home --uid 1000 app \
 && mkdir -p /app/uploads && chown -R app /app/uploads
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
# Migrations run before the server starts (safe to repeat). For several instances, run them as a release step instead.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-2} --timeout 60 --access-logfile -"]
