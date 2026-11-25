# Sign-in, companies and tokens

How people sign in, how companies are kept apart, and how the tables fit together. Code:
`core/models/{users,companies,auth_tokens,base}.py`, `core/services/auth/`, `core/auth/`, `core/api/views/{auth,team,companies}.py`.
Tests: `core/tests/test_auth.py`.

## Tables

Three groups, kept apart on purpose:

| Group | Tables | Holds |
|---|---|---|
| Identity | `users`, `companies` | Who people are and which company they belong to |
| Sign-in state | `auth_sessions`, `auth_refresh_tokens`, `auth_invitations`, `auth_login_attempts`, `auth_flows` | Sessions, tokens, invitation links, failed attempts. Nothing here describes a person; it only points at `users.id` |
| Company data | `accounts`, `knowledge_sources`, `company_settings`, ... | Each row belongs to one company (`company_id`), directly or through its account |

```
companies ─┬─< users                     users.company_id → companies.id   (NULL only for super admins)
           ├─< accounts ─< posts, leads… accounts.company_id → companies.id
           ├─< knowledge_sources         knowledge_sources.company_id → companies.id
           ├─< company_settings          company_settings.company_id → companies.id (one row per section)
           ├─< auth_invitations          (NULL company = a super admin invitation)
           └── default_account_id → accounts.id

users ─< auth_sessions ─< auth_refresh_tokens
users ← created_by / updated_by  (on users and companies)
```

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `email` | varchar(320), unique | Stored lowercase |
| `name` | varchar(200), null | |
| `password` | varchar(128) | Argon2id hash with its own random salt (`argon2$argon2id$v=19$...`). `!...` = no password (Microsoft only) |
| `role` | varchar(20) | `viewer` < `editor` < `admin` < `superadmin` (shown in the app as "Owner") |
| `can_switch_accounts` | bool | Admins and super admins always can |
| `company_id` | FK → `companies.id`, null, PROTECT | Check constraint: required unless `role = 'superadmin'` |
| `is_active` | bool | Off = signed out on the next request and can't sign in |
| `last_login` | timestamptz, null | |
| `created_at`, `updated_at` | timestamptz | |
| `created_by`, `updated_by` | FK → `users.id`, null, SET NULL | `created_by` = who invited them. NULL = the system, or the first super admin |

### `companies`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `name` | varchar(200) | Unique ignoring case (checked in the service) |
| `slug` | varchar(60), unique | e.g. `avaibe` |
| `website` | varchar(300), null | |
| `country` | char(2) | ISO code, default `AE` |
| `industry` | varchar(120), null | |
| `is_active` | bool | Off = everyone in it is signed out at once; data is kept |
| `default_account_id` | FK → `accounts.id`, null, SET NULL | What people without the account switcher see |
| `created_at`, `updated_at`, `created_by`, `updated_by` | | As on `users` |

The four audit columns come from one abstract model (`core/models/base.py: Audited`), so every table that needs
them gets the same definition. Services fill `created_by` / `updated_by` from the signed-in user
(`core/services/auth/audit.py: stamp()`).

### Sign-in state

| Table | Key columns | Notes |
|---|---|---|
| `auth_sessions` | `id` uuid PK, `user_id`, `method` (password / microsoft), `user_agent`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`, `revoked_reason` | One per signed-in device. Revoking it ends that device's access at once |
| `auth_refresh_tokens` | `id`, `session_id`, `token_hash` (unique, SHA-256), `created_at`, `expires_at`, `used_at` | The raw token is never stored |
| `auth_invitations` | `id`, `email`, `company_id` (null = owner), `role`, `can_switch_accounts`, `token_hash` (unique), `invited_by`, `created_at`, `expires_at`, `accepted_at`, `accepted_user_id`, `revoked_at`, `emailed_at` | One-time sign-up links. `emailed_at`: when the current link was emailed |
| `auth_password_resets` | `id`, `user_id`, `token_hash` (unique, SHA-256), `created_at`, `expires_at`, `used_at` | Forgot-password links: single use, 60 minutes |
| `auth_login_attempts` | `id`, `email`, `created_at` | Failed passwords only; old rows are deleted as new ones are checked |
| `auth_flows` | `state` PK, `flow` json, `created_at` | An in-progress Microsoft sign-in (existed before) |

## The super admin and the keys

- A super admin is a normal `users` row with `role = 'superadmin'` and `company_id` NULL. Everything they create
  points back at their `users.id` through `created_by`.
- The first super admin is made with `python manage.py createsuperuser` (asks for email and password), or by
  listing their email in `ADMIN_EMAILS` and signing in with Microsoft. Their own `created_by` is NULL: nobody
  created them.
- Every relation is a real foreign key on `id`, never a copied email or name, so changing someone's email
  doesn't break anything. Removing a user keeps the rows they created (`SET NULL`); a company with users or
  accounts can't be deleted (`PROTECT`): pause it instead.

## Passwords

- Hashed, not encrypted. Encryption can be reversed by whoever has the key; a hash can't be turned back into the
  password by anyone, including us. Signing in hashes what was typed and compares.
- Argon2id (the current OWASP recommendation) with a random salt per password, through Django's hasher. Older
  PBKDF2 hashes still work and are re-hashed with Argon2id at the person's next sign-in.
- Rules: at least 10 characters, not a common password, not only numbers, not like the email, at most 128.
- Five wrong passwords for one email in 15 minutes locks that email for 15 minutes. "No such email" and "wrong
  password" give the same message and take the same time, so the form can't reveal who has an account.

## Tokens

| | Access token | Refresh token |
|---|---|---|
| What | Signed JWT (HS256): `sub` user id, `sid` session id, `typ`, `iat`, `exp`, `iss` | 48 random bytes |
| Lives | 15 minutes (`ACCESS_TOKEN_MINUTES`) | Until the session ends, 7 days (`REFRESH_TOKEN_DAYS`) |
| Stored on the server | No | Only its SHA-256 hash |
| Cookie | `avaibe_access`, httpOnly, SameSite=Lax, path `/` | `avaibe_refresh`, httpOnly, SameSite=Lax, path `/api/auth/` only |

- Every API call checks the JWT, then loads its session, user and company in one query. Role, company and
  "active" come from the database, not the token, so changes apply at once.
- When the access token expires the app calls `POST /api/auth/refresh` once and repeats the request. Each refresh
  token works once and is replaced (rotation). A used token presented again more than 30 seconds later means
  someone copied it, so the whole session is revoked. Inside 30 seconds it is two tabs refreshing together, and
  only a new access token is given.
- Signing out, changing your password (other devices), turning someone off, removing them, or pausing their
  company revokes the sessions at once.
- Cookies can be sent by other sites, so every write also needs the CSRF header (`X-CSRFToken`), and sign-in
  itself is CSRF-protected.
- The signing key is `JWT_SIGNING_KEY`, or one derived from `DJANGO_SECRET_KEY` if that isn't set. Changing it
  signs everyone out within 15 minutes.

## Companies keep apart

- `allowed_account_ids()` (core/auth/permissions.py) only returns the person's company's accounts, and every
  account-scoped endpoint already goes through it, so posts, leads, analytics, AI runs and so on follow.
- Knowledge sources carry `company_id`: "applies to every account" means every account of that company.
- Team and invitation endpoints are limited to the person's company. Super admins pass `?company_id=`.
- Setup details are for owners only: setting names (e.g. `ANTHROPIC_API_KEY`), the Claude key hint and the
  platform-wide AI usage and cost. Everyone else gets a plain message (`core/auth/permissions.py: for_viewer()`).
- Settings sections are per company (`company_settings`: one row per company and section, with the four audit
  columns). Audience definitions, performance rules and the brand kit apply to that company's accounts only; a
  section with no row uses the defaults. Analytics read the settings of the account's company
  (`core/services/settings_store.py`), set per request by `check_account`. Owners pick the company on the Settings page.

## Endpoints

| Method and path | Who | Does |
|---|---|---|
| `GET /api/auth/me` | anyone | Who is signed in, their company, sign-in options; sets the CSRF cookie |
| `POST /api/auth/login` | anyone | Email and password → cookies |
| `POST /api/auth/refresh` | anyone with the cookie | New access and refresh tokens |
| `POST /api/auth/logout` | signed in | Ends this session |
| `POST /api/auth/password` | signed in | Change (or first set) your password |
| `GET /api/auth/sessions` | signed in | Your signed-in devices (browser and system, sign-in method, last active) |
| `DELETE /api/auth/sessions/<id>`, `POST /api/auth/sessions/sign-out-others` | signed in | Sign one other device, or all others, out |
| `POST /api/auth/password-reset/request` | anyone | Email a reset link. Same reply whether or not the email has an account |
| `GET /api/auth/password-reset/check?token=`, `POST /api/auth/password-reset` | anyone with a valid link | Which account; set the new password (signs out everywhere, signs this device in) |
| `GET /api/auth/invitation?token=` | anyone | What an invitation link is for |
| `POST /api/auth/signup` | anyone with a valid link | Name and password → account, signed in |
| `GET /api/auth/microsoft`, `GET /api/auth/callback` | anyone | Microsoft sign-in (also accepts a pending invitation) |
| `GET, POST /api/companies`, `GET, PUT /api/companies/<id>` | super admin | List, create, edit, pause |
| `GET, POST /api/team[?company_id=]` | admin | People and pending invitations; invite (returns the link once) |
| `PUT, DELETE /api/team/<id>` | admin | Change or remove someone |
| `DELETE /api/team/invitations/<id>`, `POST .../renew` | admin | Cancel an invitation, or make a new link |

## Invitation emails

When `EMAIL_HOST` and `DEFAULT_FROM_EMAIL` are set, inviting someone (or making a new link) emails them the link
over SMTP (`core/services/auth/emails.py`). The link is also shown once to the person who invited, so it can be
shared by hand if the email doesn't arrive. A failed send never cancels the invitation; the cause goes to the server
log only. Without a mail server the app works as before: copy the link.

## Forgotten passwords

"Forgot password?" appears on the sign-in page when email is configured. The link is single use, expires after 60
minutes (`PASSWORD_RESET_MINUTES`), and a newer link replaces an older one. The request never reveals whether an email
has an account: the reply is identical and the email is sent in the background, so the reply time is the same too.
At most `PASSWORD_RESET_PER_HOUR` (3) links per person per hour; deactivated people and suspended companies get none.
Setting the new password ends every session, clears the sign-in lockout and signs this device in.

## Settings

`.env`: `AUTH_ENABLED=true` turns sign-in on (it is also on whenever Microsoft is configured). Optional:
`JWT_SIGNING_KEY`, `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `INVITATION_DAYS`, `LOGIN_MAX_FAILURES`,
`LOGIN_LOCK_MINUTES`. Email: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`,
`DEFAULT_FROM_EMAIL`.

## Not done yet

