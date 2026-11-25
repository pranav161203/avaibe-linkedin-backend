# Backend structure

How the Django backend is organised, and where new code goes. Follow this for every change, so the codebase stays
in one shape as it grows.

One Django app (`core`) holds the database and all production code, organised in layers. Development-only code is
in a second app (`dev_tools`) that is never installed in production. The app label stays `core` and the
migration history is unchanged, so table names don't depend on which file a model lives in.

## Layout

```
config/                     Project wiring, no business logic
  settings/base.py          Shared settings (everything comes from the environment or .env)
  settings/dev.py           manage.py default: DEBUG on, dev_tools installed
  settings/prod.py          gunicorn / Docker / Render: stops at start-up if a secret is missing
  settings/test.py          `manage.py test`: SQLite unless TEST_DATABASE_URL is set
  urls.py                   /admin/, /api/ (and /mock-linkedin/ when MOCK_LINKEDIN=1)

core/
  api/                      HTTP layer: the only code that sees `request`
    urls.py                 Every /api/ route (paths are what the React app calls)
    views/<area>.py         Thin views: check access, validate input, call a service, return the response
    errors.py               ApiError, fail(status, detail), the {"detail": ...} error format
    params.py               parse(Schema, body), int_param(), choice_param()
  auth/                     Who is asking and what they may do
    authentication.py       Access-token cookie (DRF authentication), local mode, read-only demo
    cookies.py              The access and refresh cookies
    permissions.py          require(user, role), check_account(), allowed_account_ids() (company-scoped)
    microsoft.py            Microsoft Entra ID (MSAL) client
  models/<area>.py          Database models, one file per area; all re-exported from core/models/__init__.py
  schemas/<area>.py         Request bodies (Pydantic): what the API accepts
  serializers.py            Response shapes for posts and snapshots (post_out, snapshot_out, ...)
  services/                 Business logic: everything the app *does*
    analytics/              Performance (classification, overview, heatmap...), timing model, segments,
                            similar posts, rule-based suggestions
    ai/                     Claude features: ideas, post_assist, chat, research, compare, usage, shared context
    imports/                LinkedIn export files, CSV import, Excel plan import
    auth/                   Passwords, tokens, sign-in, invitations, companies (see docs/auth.md)
    publishing.py           Publishing approved posts to LinkedIn (used by the scheduler and "Publish now")
    linkedin_sync.py        Pulling data from LinkedIn's Community Management API into the tables
    calendar.py             Content calendar (posts and timing advice per date)
    calendar_data.py        Holidays, events and awareness days
    settings_store.py       Settings edited on the Settings page
    account_docs.py, topics.py
  integrations/             External APIs. HTTP clients only: no models, no business rules
    claude.py               Anthropic SDK: client(), api_errors(), pricing, token accounting
    linkedin/member_client.py   OAuth sign-in and posting as a member ("Share on LinkedIn")
    linkedin/community_api.py   Community Management API reader (real API or the mock)
    linkedin/standardized.py    LinkedIn's fixed codes (company size)
  common/                   Small helpers with no app dependencies
    timeutil.py             UTC storage, UAE/India display, posting slots
    crypto.py               Encrypting stored LinkedIn tokens
    middleware.py           X-Request-ID and one log line per API call
  conf.py                   App configuration read from the environment (API keys, LinkedIn/Microsoft settings)
  management/commands/      run_scheduler (publishing), import_legacy (one-off)
  admin.py                  Django admin
  tests/test_<area>.py      Tests, one module per area; factories.py has shared builders

dev_tools/                  Development only (never installed in production)
  mock_linkedin/            Local stand-in for LinkedIn's API with synthetic data
  management/commands/      seed_demo_linkedin, generate_mock_linkedin, compare_demo
```

## The dependency rule

Imports only point down this list. A layer may use anything below it, never anything above it.

```
api (views, urls)                     the only layer that knows about HTTP requests and responses
  auth · schemas · serializers
services                              business logic; raises its own errors, never HTTP ones
integrations                          talk to LinkedIn and Claude; know nothing about our tables
models
common · conf
```

What this means in practice:

- **Views stay thin.** A view checks the role and account access, validates the input with a schema, calls one or
  more services, and returns the result. If a view grows loops over database rows, parsing or calculations, that
  code belongs in a service. See `core/api/views/plan_import.py` (view) and `core/services/imports/plan_excel.py`
  (service) for the pattern.
- **Services never import from `core.api`** and never call `fail()`. When something the user did is wrong, raise a
  service error (for example `PlanFileError`, `claude.AIError`) and let the view turn it into the HTTP status.
- **Only `core/integrations/` talks to external APIs.** Use `claude.client()` and `with claude.api_errors():` instead
  of creating an Anthropic client yourself; use `member_client` / `community_api` for LinkedIn.
- **`core` never imports `dev_tools`.** Tests may.

`core/tests/test_architecture.py` enforces this on every test run (and in CI): an import that points up a layer
fails the build, naming the file and line.

## Where does my code go?

| I need to... | Put it in |
|---|---|
| Add an API endpoint | a view in `core/api/views/<area>.py` + a route in `core/api/urls.py` |
| Accept a new request body | a Pydantic class in `core/schemas/<area>.py` |
| Add or change a table | `core/models/<area>.py`, export it from `core/models/__init__.py`, then `makemigrations` |
| Calculate, decide, import, publish | a function in `core/services/...` |
| Call LinkedIn or Claude | `core/integrations/...` (client code), called from a service |
| Add a Claude feature | a new module in `core/services/ai/` using `core.integrations.claude` |
| Check roles or account access | `core.auth.permissions.require()` / `check_account()` in the view |
| Read a new environment variable | `core/conf.py` (app values) or `config/settings/base.py` (Django settings), plus `.env.example` |
| Add a background or scheduled job | a management command in `core/management/commands/` |
| Add something only for local testing or demos | `dev_tools/` |

## Recipe: a new endpoint

Example: `GET /api/posts/<id>/summary`.

1. **Service** (`core/services/<area>.py`): the logic, taking plain values and returning plain data.
   ```python
   def post_summary(post: Post) -> dict: ...
   ```
2. **Schema** (only for a request body) in `core/schemas/<area>.py`:
   ```python
   class SummaryIn(BaseModel):
       model_config = ConfigDict(extra="forbid")
       length: Literal["short", "long"] = "short"
   ```
3. **View** (`core/api/views/<area>.py`):
   ```python
   @api_view(["POST"])
   def post_summary(request, post_id: int):
       user = request.user
       require(user, "editor")                 # role check, when the endpoint changes data
       post = _get_post(post_id, user)         # 404 if the post's account isn't allowed
       body = parse(SummaryIn, request.data)   # 422 with field errors if invalid
       return Response(summaries.post_summary(post, body.length))
   ```
4. **Route** in `core/api/urls.py`: `path("posts/<int:post_id>/summary", posts.post_summary)`.
5. **Test** in `core/tests/test_<area>.py`: call the endpoint with `APIClient` and patch
   `core.auth.authentication.auth_enabled` to `False` for local mode (see existing tests).

Every endpoint must check account access (`check_account`, or a getter that filters by `allowed_account_ids`).
Hiding something in the UI is not access control.

## Recipe: a model change

1. Edit or add the model in `core/models/<area>.py` (and export new ones from `core/models/__init__.py`).
2. `.\.venv\Scripts\python manage.py makemigrations` and read the generated file before committing it.
3. `.\.venv\Scripts\python manage.py migrate`.
4. CI fails if a model change has no migration (`makemigrations --check`).

## Conventions

- **Errors** keep one shape for the React app: `{"detail": "..."}` with the HTTP status. In views use
  `fail(status, "message")`; 422 for invalid input, 404 for things the user may not see (never 403, so nobody can
  probe which accounts exist).
- **Time**: store UTC; show UAE time first and India time second (`core/common/timeutil.py`).
- **Secrets** only in the environment or `.env` (never committed). New variables go in `.env.example` with a comment.
- **Logging**: `log = logging.getLogger(__name__)`. Every line carries the request ID automatically. Never log
  tokens, keys or personal data.
- **Claude and LinkedIn calls** happen only when someone clicks something or a scheduled job runs, never on page load.
  Every Claude call is stored as an `AIRun` with tokens and cost, and counts toward the daily limit.
- **Tests replace external APIs** with `mock.patch` on the module function (e.g. `core.integrations.claude.configured`,
  `core.services.ai.chat.call_claude_chat`). Tests never call real LinkedIn or Anthropic.

## Running and checking

```powershell
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8000     # dev settings
.\.venv\Scripts\python manage.py test                         # test settings (SQLite)
.\.venv\Scripts\ruff check .                                  # lint (CI runs the same)
.\.venv\Scripts\ruff check . --fix                            # fix import order and unused imports
```

CI (`.github/workflows/ci.yml`) runs on every pull request: ruff, `manage.py check`, migrations in sync, the tests on
PostgreSQL, and a start-up check of the production settings.

## Production

- Render runs `gunicorn config.wsgi` with `DJANGO_SETTINGS_MODULE=config.settings.prod` (see `render.yaml`).
- The `Dockerfile` builds the same thing for any container host: non-root user, migrations at start, health check.
- Required in production: `DJANGO_SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`. Missing ones stop the start-up with
  a clear message instead of running with an unsafe default.
- `GET /api/health` returns 200 when the database is reachable, 503 otherwise.
- The publishing scheduler (`manage.py run_scheduler`) is a separate process. It must run wherever scheduled posts
  should go out.
