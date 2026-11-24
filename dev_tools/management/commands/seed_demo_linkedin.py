"""Set up the demo accounts and fill them through the (mock) LinkedIn API, exactly as a real sync would.

    python manage.py seed_demo_linkedin            # needs the backend running with MOCK_LINKEDIN=1
    python manage.py seed_demo_linkedin --reset    # wipe the demo accounts' data first

Creates three test accounts, kept apart from real data:
  "Demo company" (company page), "Demo Founder (CEO)" and "Demo Co-founder (CTO)" (founder profiles).
Founders' posts can't be listed through LinkedIn's API, so the posts the app would have published for them are
added from the dummy data first (as if published through the app); their numbers then come from the API.
"""

import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand
from django.db import transaction

from core.integrations.linkedin.community_api import LinkedInAPI
from core.models import Account, AccountDoc, PageAudience, PageDaily, Post
from core.services import topics
from core.services.linkedin_sync import (
    API_NOTE,
    little_to_text,
    post_format,
    sync_company,
    sync_member,
)
from dev_tools.mock_linkedin import MOCK_DIR
from dev_tools.mock_linkedin.server import TOKENS

MOCK_BASE = "http://127.0.0.1:8002/mock-linkedin"
TOKEN_FOR = {"company": "mock-page-admin", 0: "mock-founder-ceo", 1: "mock-founder-cto"}
assert set(TOKEN_FOR.values()) <= set(TOKENS)


class Command(BaseCommand):
    help = "Create the demo company + founders and sync them from the mock LinkedIn API"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the demo accounts' posts and page data first")
        parser.add_argument("--base", default=MOCK_BASE, help="API base URL (default: the local mock)")

    def handle(self, *args, **opts):
        world = json.loads((MOCK_DIR / "linkedin_world.json").read_text(encoding="utf-8"))
        org = world["organization"]

        def account(name, kind, urn):
            acc, _ = Account.objects.get_or_create(name=name, defaults={"kind": kind, "is_test": True})
            acc.kind, acc.is_test, acc.linkedin_urn = kind, True, urn
            acc.linkedin_url = acc.linkedin_url or (f"https://www.linkedin.com/company/{org['vanityName']}" if kind == "company" else None)
            acc.save()
            return acc

        company = account("Demo company", "company", org["urn"])
        founders = [account(m["name"], "founder", m["urn"]) for m in world["members"]]
        for f in founders:  # founders belong to the company page (shown together on the Dashboard)
            f.parent = company
            f.save(update_fields=["parent"])
        demo = [company, *founders]

        if opts["reset"]:
            for acc in demo:
                Post.objects.filter(account=acc).delete()
                PageDaily.objects.filter(account=acc).delete()
                PageAudience.objects.filter(account=acc).delete()
            self.stdout.write("Cleared the demo accounts' data")

        # Tokens for the mock API (a real connection would store the OAuth token encrypted instead)
        for acc, tok in ((company, TOKEN_FOR["company"]), *((f, TOKEN_FOR[i]) for i, f in enumerate(founders))):
            AccountDoc.objects.update_or_create(account=acc, kind="api_access", defaults={"data": {"token": tok, "note": "Demo token for the mock LinkedIn API"}})

        # Founders' posts "published through the app" (the API can't list them)
        with transaction.atomic():
            for acc, m in zip(founders, world["members"]):
                for p in m["posts"]:
                    url = f"https://www.linkedin.com/feed/update/{p['id']}/"
                    if Post.objects.filter(post_url=url).exists():
                        continue
                    caption = little_to_text(p["commentary"])
                    s = topics.suggest(caption)
                    Post.objects.create(
                        account=acc, post_url=url, linkedin_post_id=p["id"], author=m["name"],
                        published_at=datetime.fromtimestamp(p["publishedAt"] / 1000, tz=timezone.utc), time_known=True,
                        format=post_format(p.get("content")), caption=caption, hashtags=topics.hashtags(caption),
                        topic=s["topic"], industry=s["industry"], cta=s["cta"], topic_suggested=bool(s["topic"]),
                        notes="Published through the app (demo)",
                    )

        total_calls = 0
        api = LinkedInAPI(TOKEN_FOR["company"], base=opts["base"])
        r = sync_company(company, api)
        total_calls += r.calls
        self.stdout.write(f"{r.account}: {r.posts_created} new / {r.posts_updated} updated posts, {r.snapshots} snapshots, "
                          f"{r.days} days, {r.demographic_rows} audience rows, {r.calls} API calls")
        for i, f in enumerate(founders):
            api = LinkedInAPI(TOKEN_FOR[i], base=opts["base"])
            r = sync_member(f, api)
            total_calls += r.calls
            self.stdout.write(f"{r.account}: {r.snapshots} post snapshots, {r.days} follower days, {r.calls} API calls"
                              + (f" · {'; '.join(r.notes[-1:])}" if r.notes else ""))
        self.stdout.write(self.style.SUCCESS(f"Demo data synced through the {'mock' if 'mock' in opts['base'] else 'real'} API "
                                             f"in {total_calls} calls. ({API_NOTE})"))
