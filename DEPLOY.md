# Hosting the demo (free): GitHub → Neon + Render + Vercel

The hosted copy shows **synthetic data only** ("Demo company" and two demo founders). AVAIBE's real exports,
the real database and every `.env` file stay on the laptop; `.gitignore` keeps them out of GitHub.

| Part | Host (free tier) | What runs there |
|---|---|---|
| Code | GitHub, two **private** repositories | **avaibe-linkedin-backend** (this one: Django API) and **avaibe-linkedin-frontend** (React screens), each without what its `.gitignore` excludes |
| Database | Neon (PostgreSQL) | the demo data |
| API | Render (web service) | this repository (`render.yaml`) |
| Screens | Vercel | the frontend repository (its `vercel.json`) |

Vercel forwards `/api/...` to Render, so the browser only ever talks to the Vercel address.

> Limits to know: Render's free server sleeps after ~15 minutes idle, so the first visit after a pause takes
> 30–60 s. Vercel's free (Hobby) plan is meant for personal, non-commercial use. The demo runs without
> sign-in (local mode), so `render.yaml` sets `READ_ONLY_WITHOUT_SIGNIN=true`: the API then refuses every change
> (anyone can view, nobody can edit). Re-run step 3 to reload the data. Once Microsoft sign-in is set up, roles
> apply instead: Viewer < Editor < Approver < Admin < Super admin.

## 1. GitHub
Both repositories already exist and are pushed (pranav161203/avaibe-linkedin-backend and
pranav161203/avaibe-linkedin-frontend). On the laptop they are the `server` and `frontend` folders of the
Test2 copy; commit and push each folder on its own. A browser window asks you to sign in to GitHub the first time.

## 2. Neon (database)
1. neon.tech → sign in with GitHub → **New project** (region: AWS Europe (Frankfurt), close to Render's).
2. **Connect** → copy the connection string (`postgresql://…?sslmode=require`). It is a password: don't paste
   it into chat, email or code.

## 3. Fill the database with the demo data (from this laptop)
The demo data is loaded through the local mock LinkedIn API, so this runs on the laptop, once:
1. Save the Neon string in `.env.deploy` (in this repository's folder) as one line: `DATABASE_URL=postgresql://…`
   (ignored by git).
2. With the Test2 backend running (`MOCK_LINKEDIN=1`, port 8002), in this folder:
   ```powershell
   .\deploy-seed.ps1          # creates the tables and loads the demo accounts into Neon
   ```

## 4. Render (API)
1. render.com → sign in with GitHub → **New → Blueprint** → choose **avaibe-linkedin-backend**. It reads `render.yaml`.
2. When asked, fill in:
   - `DATABASE_URL`: the Neon string
   - `CORS_ORIGINS`: the Vercel address from step 5 (you can add it afterwards and redeploy)
3. Wait for "Live", then open `https://<service>.onrender.com/api/health`: it should show `{"status": "ok"}` (the database is reachable).
   If Render gave the service a different name than `avaibe-linkedin-demo`, change the address in
   the frontend repository's `vercel.json` to match, commit and push that repository.

## 5. Vercel (screens)
1. vercel.com → sign in with GitHub → **Add New → Project** → choose **avaibe-linkedin-frontend**.
2. Framework: Vite (detected). No root directory needed: the app is at the top of the repository.
3. Environment variable: `VITE_DEMO_BANNER` = `1` (shows "Demo data" across the top).
4. Deploy. Open the address, sign in with any email (demo sign-in), and check Dashboard and Data.

## Updating later
Commit and push the repository that changed: Render redeploys on pushes to the backend repository, Vercel
on pushes to the frontend repository. A change that needs both (a new screen and its API) is pushed to both,
backend first, so the new screen never calls an API that isn't live yet.
