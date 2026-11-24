"""Create the dummy LinkedIn data (12 months, company page + 2 founders) that the mock LinkedIn server serves.

    python manage.py generate_mock_linkedin                # data up to yesterday (UTC)
    python manage.py generate_mock_linkedin --end 2026-11-17

Demographic proportions are taken from mock_data/calibration_demographics.json (aggregate follower/visitor counts
from a real LinkedIn page export); everything else is generated. The output is synthetic and belongs to no one.
"""

from datetime import date, datetime, timedelta, timezone

from django.core.management.base import BaseCommand

from dev_tools.mock_linkedin import MOCK_DIR, generate


class Command(BaseCommand):
    help = "Generate dummy LinkedIn Community Management API data for local testing"

    def add_arguments(self, parser):
        parser.add_argument("--end", help="Last day of data (YYYY-MM-DD), default yesterday UTC")

    def handle(self, *args, **opts):
        end = date.fromisoformat(opts["end"]) if opts["end"] else datetime.now(timezone.utc).date() - timedelta(days=1)
        world = generate.generate(MOCK_DIR / "calibration_demographics.json", MOCK_DIR / "linkedin_world.json", end)
        m = world["members"]
        self.stdout.write(self.style.SUCCESS(
            f"Dummy LinkedIn data {world['meta']['dataStart']} → {world['meta']['dataEnd']}: "
            f"{len(world['posts'])} page posts, {len(world['pageDays'])} page days, "
            f"{world['followers']['total']} followers, founders {', '.join(f'{x['name']} ({len(x['posts'])} posts)' for x in m)}, "
            f"{len(world['notifications'])} notifications → {MOCK_DIR / 'linkedin_world.json'}"
        ))
