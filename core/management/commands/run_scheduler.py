"""Publishes approved, scheduled posts on time.

Run alongside the web server:  python manage.py run_scheduler
Posts found more than PUBLISH_GRACE_MINUTES late are marked 'missed' instead of published late.
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.services import publishing as publisher

log = logging.getLogger("scheduler")


class Command(BaseCommand):
    help = "Publish approved, scheduled LinkedIn posts when they are due (runs until stopped)."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=30, help="Seconds between checks (default 30)")
        parser.add_argument("--once", action="store_true", help="Check once and exit")

    def handle(self, *args, interval: int, once: bool, **opts):
        self.stdout.write(self.style.SUCCESS(f"Scheduler running (every {interval}s). Ctrl+C to stop."))
        while True:
            close_old_connections()
            try:
                publisher.run_due()
            except Exception:  # keep running; log and continue
                log.exception("scheduler tick failed")
            if once:
                return
            time.sleep(interval)
