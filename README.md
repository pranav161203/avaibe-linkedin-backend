# avaibe · LinkedIn Intelligence

> **Two repositories.** This one is the backend (Django API, in the `server` folder on the laptop). The screens are
> in **avaibe-linkedin-frontend** (the `frontend` folder). Paths below such as `server/` and `frontend/` refer to
> those two folders side by side, as on the laptop.

Internal web app to grow AVAIBE's **relevant LinkedIn reach**: UAE audiences, especially schools and decision-makers.
It tracks posts and audiences, explains what to do next, publishes approved posts, and controls who can see what.

| Part | Stack | Folder |
|---|---|---|
| Backend | Python · **Django 6** · Django REST Framework · PostgreSQL | `server/` |
| Frontend | React · Vite · Tailwind v4 · shadcn/ui · React Query | `frontend/` |
| Docs | Outreach framework, AEO question set, Microsoft sign-in setup | `docs/` |

> `backend/` is the previous FastAPI version, kept read-only as a reference and backup until the team confirms the
> Django version. Its database (`avaibe_linkedin`) was copied into the Django database (`avaibe_django`).

## Quick start (Windows)

```powershell
.\start-dev.ps1
```

This opens three windows: the Django API (port 8000), the publishing scheduler, and the React app. Open
**http://localhost:5173**. The admin panel is at **http://localhost:5173/admin/**.

### First-time setup

1. **PostgreSQL** (18 on this machine; nothing from Stack Builder is needed). Create the database:
   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE avaibe_django;"
   ```
2. **Backend**
   ```powershell
   cd server
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements-dev.txt   # runtime + lint tools
   copy .env.example .env        # then fill in DATABASE_URL, DJANGO_SECRET_KEY, LinkedIn keys…
   .\.venv\Scripts\python manage.py migrate
   ```
3. **Frontend**
   ```powershell
   cd frontend
   npm install
   ```

### Running the parts by hand

| What | Command (in `server/` unless noted) |
|---|---|
| API | `.\.venv\Scripts\python manage.py runserver 127.0.0.1:8000` |
| Publishing scheduler | `.\.venv\Scripts\python manage.py run_scheduler` |
| Front end (in `frontend/`) | `npm run dev` |
| Database changes after updating models | `.\.venv\Scripts\python manage.py makemigrations` then `migrate` |
| Admin login in local mode | `.\.venv\Scripts\python manage.py createsuperuser` |
| Tests (SQLite, never your `.env` database) | `.\.venv\Scripts\python manage.py test` |
| Lint (same as CI) | `.\.venv\Scripts\ruff check .` |
uff check .` |
| Mock LinkedIn API + demo data | `$env:MOCK_LINKEDIN="1"` before `runserver`, then `manage.py seed_demo_linkedin` |
| Copy data from the old FastAPI database (one-off) | `.\.venv\Scripts\python manage.py import_legacy` |

## How the backend is organised (`server/`)

**Read [docs/architecture.md](docs/architecture.md) before changing the backend.** It has the full layout, the layer
rule (checked by a test) and step-by-step recipes for endpoints and models.

| Path | Contents |
|---|---|
| `config/settings/` | `base.py` plus `dev.py` (manage.py default), `prod.py` (gunicorn/Docker/Render), `test.py`; values come from the environment / `.env` |
| `core/api/` | HTTP layer: routes (`urls.py`, the paths the React app calls) and thin views, one module per area |
| `core/auth/` | Session sign-in (Microsoft Entra ID), roles, account access |
| `core/models/` | Database models, one module per area (accounts, posts, publishing, users, ai, leads...) |
| `core/schemas/` | Request validation (Pydantic) |
| `core/services/` | Business logic: analytics, Claude features, imports, publishing, LinkedIn sync, calendar |
| `core/integrations/` | External APIs: Claude (Anthropic SDK) and LinkedIn (member OAuth/posting, Community Management API) |
| `core/common/` | Time zones, token encryption, request-ID middleware |
| `core/tests/` | Tests, one module per area |
| `dev_tools/` | Development only: mock LinkedIn API and demo-data commands (never installed in production) |
| `Dockerfile`, `render.yaml`, `.github/workflows/ci.yml` | Container image, Render deployment, CI (lint, checks, migrations, tests) |

## What it does

- **Tracking:** posts with snapshots at 1h, 6h, 24h, 48h and 7d. A checkpoint closes when the next one arrives,
  because LinkedIn only shows running totals.
- **Relevant reach:** "who saw this post" (location, industry, seniority) gives UAE, education and decision-maker
  shares and estimated UAE impressions. Shares are minimums; dimensions are never added together.
- **Dashboard:** KPIs, relevant reach, top/lowest posts with labels against the account's own history, formats,
  posting-time heatmap (UAE time; 3+ posts before a slot is suggested), topics/CTAs/hashtags, 7/30/90-day consistency.
- **Suggestions:** each one says what, when and for whom, **why** (evidence from your data), how it can **boost**
  and how it could **lower** outreach, confidence and how to measure it.
- **Audience:** weekly page follower/visitor demographics, trend chart.
- **Publishing:** draft → approve → publish now or at a scheduled time, for connected personal profiles (company
  pages need LinkedIn's Community Management API). Approved posts only; never sent twice; late posts are marked missed.
  - **When LinkedIn is busy** (HTTP 429/503, or it can't be reached), nothing is posted and no error is shown. The post shows "Waiting for LinkedIn" with a countdown, and the scheduler tries again automatically after 2, 5, 10, 20 and 30 minutes, or longer if LinkedIn asks. After 6 tries (about 67 minutes) it stops and shows when to try again. If LinkedIn kept answering "too many requests", its daily limit was probably reached, so the wait runs until LinkedIn's reset at midnight UTC (04:00 UAE). A post changed, un-approved or deleted during the wait is never posted automatically.
  - **When LinkedIn may have accepted the post** (a timeout or a 500/502/504 after sending), the app never retries automatically. It asks the team to check the profile after 5 minutes, to avoid a duplicate post.
  - Connecting a profile while LinkedIn is busy shows "try again in about N minutes".
- **Access:** Microsoft sign-in (invite-only), roles Viewer < Editor < Approver < Admin, and "can switch accounts" per
  person. People without it only see the default account. All enforced by the API, with CSRF protection.
  **Local mode** (no sign-in, everyone admin) until `MS_TENANT_ID`, `MS_CLIENT_ID` and `MS_CLIENT_SECRET` are set.
  Setup for IT: `docs/microsoft-signin-setup.md`.
- **Strategy ideas (Claude):** on the Suggestions page. Claude reads the account's own numbers plus Settings → Brand & knowledge and proposes 5–8 ideas: posts, campaigns, outreach, brand, SEO/AEO and sales. Each idea has why (with the evidence cited), how it can boost or lower outreach, effort, confidence and how to measure it. A post idea can become a Publishing draft, which still needs approval. Every run is logged with its token cost, and each account is limited to 20 successful runs a day.
  - To switch it on, add `ANTHROPIC_API_KEY=…` to `server/.env` and restart. Optionally set `CLAUDE_MODEL` (default `claude-opus-5-5`).
- **Settings:** accounts, team, editable audience definitions and performance rules, brand & knowledge (what Claude knows about AVAIBE), Claude status and monthly usage.
- **Time zones:** UAE, India or London for display and input; analysis stays in UAE time.
- **Design:** avaibe.com's look: black and violet, Figtree, glass cards, dark by default with a light option.

## Definitions

- **Engagements** = reactions + comments + reposts + clicks; **engagement rate** = engagements ÷ impressions
- **Click rate** = clicks ÷ impressions
- **Labels** = percentile within the account's own history (cut-offs editable in Settings)
- **Trend** = change vs the previous period beyond the threshold (default ±10%)

## Before hosting

- Set `DJANGO_DEBUG=false`, a strong `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, `COOKIE_SECURE=true` and the HTTPS origins.
- Configure Microsoft sign-in, so local mode is off.
- Run `python manage.py collectstatic`, serve with a production server (e.g. gunicorn/waitress behind HTTPS), and
  run `run_scheduler` as a service.
- Back up the database regularly.
