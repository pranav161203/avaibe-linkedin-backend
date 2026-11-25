# Sign-in, companies and tokens: schema design

How people sign in, how companies are kept apart, and how the tables relate.

- Models: `core/models/{users,companies,auth_tokens,base}.py`
- Logic: `core/services/auth/` (no HTTP), `core/services/settings_store.py`
- HTTP: `core/auth/` (authentication, permissions, cookies), `core/api/views/{auth,team,companies,settings}.py`
- Tests: `core/tests/test_auth.py`, `core/tests/test_company_settings.py`
- Migrations: `0022` to `0027` (listed at the end)

**Owner** in the app is the role value `superadmin` in the database. The label changed; the stored value didn't.

## 1. Table groups

The tables fall into three groups, kept apart on purpose:

| Group | Tables | Holds |
|---|---|---|
| Identity | `users`, `companies` | Who people are and which company they belong to |
| Sign-in state | `auth_sessions`, `auth_refresh_tokens`, `auth_invitations`, `auth_password_resets`, `auth_login_attempts`, `auth_flows` | Sessions, tokens, links, failed attempts. These tables describe no one: they only point at `users.id` |
| Company data | `company_settings`, `accounts` (and through it posts, leads...), `knowledge_sources` | Each row belongs to one company, directly or through its account |

Tokens never sit in `users` or `companies`. Removing a token table would not change who anyone is or which company they
belong to.

## 2. Relations

```
companies ─┬─< users                    users.company_id            (NULL only for owners)
           ├─< accounts ─< posts, leads… accounts.company_id
           ├─< knowledge_sources        knowledge_sources.company_id
           ├─< company_settings         company_settings.company_id (one row per section)
           ├─< auth_invitations         auth_invitations.company_id (NULL = inviting an owner)
           └── default_account_id ────> accounts.id

users ─┬─< auth_sessions ─< auth_refresh_tokens
       ├─< auth_password_resets
       └── created_by / updated_by <── users, companies, company_settings
           invited_by / accepted_user_id <── auth_invitations
```

- Every relation is a foreign key on `id`, never a copied email or name. Changing someone's email breaks nothing.
- Deleting a user keeps the rows they created: `created_by` / `updated_by` become NULL (`SET NULL`). Their sessions,
  refresh tokens and reset links are deleted with them (`CASCADE`).
- A company that still has users or accounts can't be deleted (`PROTECT`): suspend it instead (`is_active = false`).
  Deleting an empty company removes its settings and invitations (`CASCADE`).

## 3. Identity

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `email` | varchar(320), unique | Stored lowercase |
| `name` | varchar(200), null | |
| `password` | varchar(128) | Argon2id hash with its own salt (`argon2$argon2id$v=19$...`). Starts with `!` = no password (Microsoft only) |
| `role` | varchar(20) | `viewer` < `editor` < `admin` < `superadmin` (Owner) |
| `can_switch_accounts` | bool | Admins and owners can always switch, whatever this says |
| `company_id` | FK → `companies.id`, null, PROTECT | |
| `is_active` | bool | Off = signed out on the next request and can't sign in |
| `last_login` | timestamptz, null | |
| `created_at`, `updated_at` | timestamptz | |
| `created_by`, `updated_by` | FK → `users.id`, null, SET NULL | `created_by` = who invited them |

Constraint `user_company_unless_superadmin`: `company_id` is required unless `role = 'superadmin'`. Owners belong to no
company, so they can manage every company.

### `companies`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `name` | varchar(200) | Unique ignoring case (checked in `services/auth/companies.py`) |
| `slug` | varchar(60), unique | Stable handle, e.g. `avaibe` |
| `website` | varchar(300), null | |
| `country` | varchar(2) | ISO 3166-1 code, default `AE` |
| `industry` | varchar(120), null | |
| `is_active` | bool | Off (suspended) = everyone in it is signed out at once; data is kept |
| `default_account_id` | FK → `accounts.id`, null, SET NULL | The account people without "can switch accounts" see |
| `created_at`, `updated_at`, `created_by`, `updated_by` | | As on `users` |

### Audit columns

`created_at`, `updated_at`, `created_by` and `updated_by` come from one abstract model, `core/models/base.py: Audited`.
`users`, `companies` and `company_settings` all use it, so the definition is the same everywhere. Services fill
`created_by` / `updated_by` with the acting person's `users.id` (`core/services/auth/audit.py: stamp()`). NULL means the
system: a migration, a command, or local mode.

### The owner and the keys

- An owner is a normal `users` row: `role = 'superadmin'`, `company_id` NULL.
- The first owner is created with `python manage.py createsuperuser`, or by listing their email in `ADMIN_EMAILS` and
  signing in with Microsoft. Their own `created_by` is NULL, because nobody created them.
- Everything an owner creates (companies, invitations, settings) records their `users.id` in `created_by` /
  `invited_by`.
- There is always at least one active owner: removing, demoting or deactivating the last one is refused.

## 4. Sign-in state

| Table | Columns | Notes |
|---|---|---|
| `auth_sessions` | `id` uuid PK, `user_id` FK CASCADE, `method` varchar(20) (`password` / `microsoft`), `user_agent` varchar(300), `created_at`, `last_used_at`, `expires_at`, `revoked_at` null, `revoked_reason` varchar(30) | One row per signed-in device. Index `auth_sess_user_active (user_id, revoked_at)` |
| `auth_refresh_tokens` | `id`, `session_id` FK CASCADE, `token_hash` varchar(64) unique, `created_at`, `expires_at`, `used_at` null | Only the SHA-256 hash is stored |
| `auth_invitations` | `id`, `email` varchar(320), `company_id` FK null CASCADE, `role`, `can_switch_accounts`, `token_hash` varchar(64) unique, `invited_by` FK null, `created_at`, `expires_at`, `accepted_at` null, `accepted_user_id` FK null, `revoked_at` null, `emailed_at` null | Single-use sign-up links, valid 7 days. `emailed_at` = when the current link was emailed. Index `auth_inv_email` |
| `auth_password_resets` | `id`, `user_id` FK CASCADE, `token_hash` varchar(64) unique, `created_at`, `expires_at`, `used_at` null | Forgot-password links, single use, valid 60 minutes. Index `auth_reset_user_created (user_id, created_at)` |
| `auth_login_attempts` | `id`, `email` varchar(320), `created_at` | Failed passwords only; old rows are deleted as new ones are checked |
| `auth_flows` | `state` varchar(128) PK, `flow` json, `created_at` | A Microsoft sign-in in progress |

Values of `revoked_reason`: `signed_out`, `signed_out_remotely`, `password_changed`, `password_reset`, `token_reuse`,
`user_disabled`, `removed`.

## 5. Company data: `company_settings`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `company_id` | FK → `companies.id`, CASCADE | |
| `section` | varchar(30) | `segments` (audience definitions), `performance` (performance rules) or `brand` (brand kit) |
| `value` | json | Validated by the section's schema in `services/settings_store.py` |
| `created_at`, `updated_at`, `created_by`, `updated_by` | | Audit columns |

- Unique constraint `company_setting_unique_section (company_id, section)`.
- A section with no row uses the defaults. New companies start with an empty brand kit.
- Analytics read the settings of the company that owns the account being viewed. `check_account()` sets that
  company for the rest of the request, and middleware resets it between requests.

## 6. Passwords

- Passwords are hashed, not encrypted. Anything encrypted can be decrypted by whoever holds the key; a hash can't be
  turned back into the password by anyone, including us. Signing in hashes what was typed and compares the two.
- Algorithm: Argon2id with a random salt per password (Django's hasher). Older PBKDF2 hashes still work, and are
  re-hashed with Argon2id at the person's next sign-in.
- Rules: 10 to 128 characters, not a common password, not only numbers, not similar to the email.
- Lockout: 5 wrong passwords for one email within 15 minutes lock that email for 15 minutes.
- "No such email" and "wrong password" give the same message and take the same time, so the form can't be used to
  find out who has an account.
- Changing your password signs out your other devices.

## 7. Tokens

| | Access token | Refresh token |
|---|---|---|
| What | Signed JWT (HS256) with `sub` (user id), `sid` (session id), `typ`, `iat`, `exp`, `iss` | 48 random bytes |
| Lives | 15 minutes (`ACCESS_TOKEN_MINUTES`) | Until the session ends, at most 7 days (`REFRESH_TOKEN_DAYS`) |
| Stored on the server | No | Only its SHA-256 hash |
| Cookie | `avaibe_access`: httpOnly, SameSite=Lax, path `/` | `avaibe_refresh`: httpOnly, SameSite=Lax, path `/api/auth/` only |

- **Every request** checks the JWT, then loads the session, user and company in one query. Role, company and active
  status come from the database, not the token, so a change applies on the very next request.
- **Refresh:** when the access token expires, the app calls `POST /api/auth/refresh` once and repeats the request.
- **Rotation:** each refresh token works once and is replaced. If a used token comes back more than 30 seconds later,
  someone copied it, and the whole session is revoked. Within 30 seconds it is treated as two tabs refreshing at the
  same time.
- **Ending sessions at once:** signing out, changing or resetting a password, deactivating or removing someone, and
  suspending their company all revoke sessions immediately.
- **CSRF:** cookies are sent automatically by browsers, so every write also needs the `X-CSRFToken` header. Sign-in is
  CSRF-protected too.
- **Signing key:** `JWT_SIGNING_KEY`, or one derived from `DJANGO_SECRET_KEY` when that isn't set. Changing it signs
  everyone out within 15 minutes.

## 8. How companies are kept apart

- `allowed_account_ids()` (`core/auth/permissions.py`) returns only the accounts of the person's company. Every
  account-scoped endpoint goes through it, so posts, leads, analytics and AI runs are all limited to the company.
- Knowledge sources carry `company_id`. "Applies to every account" means every account of that company.
- Settings are per company (section 5).
- Team and invitation endpoints only reach the person's own company. Owners choose a company with `?company_id=`.
- Owners only: setting names (e.g. `ANTHROPIC_API_KEY`), the Claude key hint, and AI usage and cost across all
  companies. Everyone else gets a plain message (`core/auth/permissions.py: for_viewer()`).

## 9. Links sent by email

Email is sent over SMTP when `EMAIL_HOST` and `DEFAULT_FROM_EMAIL` are set (`core/services/auth/emails.py`). Without
them, invitation links are shown to copy, and "Forgot password?" is hidden.

**Invitations**
- Inviting someone, or regenerating their link, emails them the link.
- The link is also shown once to the person who invited, in case the email doesn't arrive.
- A failed send never cancels the invitation; the cause goes to the server log only.
- A new link replaces the old one, and `emailed_at` is reset.

**Password reset**
- The request gets the same reply whether or not the email has an account, and the email is sent in the background,
  so response time doesn't reveal it either.
- At most 3 links per person per hour (`PASSWORD_RESET_PER_HOUR`). A newer link replaces an older one.
- No link for deactivated people or suspended companies.
- Setting the new password ends every session, clears the sign-in lock and signs this device in.

## 10. Endpoints

| Method and path | Who | Does |
|---|---|---|
| `GET /api/auth/me` | anyone | Who is signed in, their company, sign-in options; sets the CSRF cookie |
| `POST /api/auth/login` | anyone | Email and password → cookies |
| `POST /api/auth/refresh` | refresh cookie | New access and refresh tokens |
| `POST /api/auth/logout` | signed in | Ends this session |
| `POST /api/auth/password` | signed in | Change (or first set) your password |
| `GET /api/auth/sessions` | signed in | Your signed-in devices |
| `DELETE /api/auth/sessions/<id>`, `POST /api/auth/sessions/sign-out-others` | signed in | Sign out one other device, or all others |
| `POST /api/auth/password-reset/request` | anyone | Email a reset link |
| `GET /api/auth/password-reset/check?token=`, `POST /api/auth/password-reset` | valid link | Which account; set the new password |
| `GET /api/auth/invitation?token=` | anyone | What an invitation link is for |
| `POST /api/auth/signup` | valid link | Name and password → account, signed in |
| `GET /api/auth/microsoft`, `GET /api/auth/callback` | anyone | Microsoft sign-in (also accepts a pending invitation) |
| `GET, POST /api/companies`, `GET, PUT /api/companies/<id>` | owner | List, create, edit, suspend |
| `GET, POST /api/team[?company_id=]` | admin | Members and pending invitations; invite |
| `PUT, DELETE /api/team/<id>` | admin | Change or remove someone |
| `DELETE /api/team/invitations/<id>`, `POST /api/team/invitations/<id>/renew` | admin | Revoke an invitation, or regenerate its link |
| `GET /api/settings[?company_id=]` | signed in | The company's settings |
| `PUT /api/settings/<section>`, `POST /api/settings/<section>/reset` | admin | Save or reset one section |

Admins manage viewers and editors in their own company. Only owners change admins and owners, and nobody changes their
own access.

## 11. Configuration (`.env`)

| Setting | Default | Purpose |
|---|---|---|
| `AUTH_ENABLED` | `false` | Turns sign-in on. Also on whenever Microsoft sign-in is configured. Off = local mode, where every request acts as an owner |
| `JWT_SIGNING_KEY` | derived from `DJANGO_SECRET_KEY` | Signs access tokens |
| `ACCESS_TOKEN_MINUTES` / `REFRESH_TOKEN_DAYS` | 15 / 7 | Token lifetimes |
| `INVITATION_DAYS` | 7 | Invitation link lifetime |
| `PASSWORD_RESET_MINUTES` / `PASSWORD_RESET_PER_HOUR` | 60 / 3 | Reset link lifetime and limit |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCK_MINUTES` | 5 / 15 | Sign-in lockout |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | off | SMTP for invitation and reset emails |
| `EMAIL_BACKEND` | SMTP | Development only: the console backend prints emails to the log instead of sending |
| `FRONTEND_URL` | `http://localhost:5173` | Base address of the links in emails |

## 12. Migrations

| Migration | Does |
|---|---|
| `0022_companies_and_auth_tokens` | Creates `companies` and the sign-in state tables; adds audit columns and `company_id` to `users`, `accounts` and `knowledge_sources` |
| `0023_assign_existing_data_to_avaibe` | Puts existing accounts, knowledge and people into an "AVAIBE" company, then adds the user/company constraint |
| `0024_role_label_owner` | Label change only (`superadmin` shown as Owner); no data change |
| `0025_company_settings` | Creates `company_settings`, copies the old app-wide settings to AVAIBE (including the AVAIBE brand kit that used to be the default), drops `app_settings` |
| `0026_invitation_emailed_at` | Adds `auth_invitations.emailed_at` |
| `0027_password_resets` | Creates `auth_password_resets` |

## 13. Not done yet

- Per-IP rate limits for sign-in and reset requests. Today the limits are per email, which slows guessing on one
  account but not attempts spread across many.
- A history of who changed what. The audit columns record only the creator and the last editor.
- Microsoft sign-in restricted to each company's own Microsoft tenant. Today one tenant is configured for the whole app.
