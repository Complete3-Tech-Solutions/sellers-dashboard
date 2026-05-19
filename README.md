# Sellers Dashboard — SCC Profitability SaaS

Multi-tenant SaaS that turns the SCC Profitability Dashboard into a live, login-protected dashboard. A small Windows agent watches the customer's job-cost Excel folder; every save uploads to the backend, which parses the files and re-renders the dashboard within ~15 seconds.

```
┌──────────────────────────┐         HTTPS + HMAC          ┌────────────────────────┐
│  Customer's Windows PC   │ ────────────────────────────► │  Railway service       │
│  ──────────────────────  │                                │  ────────────────────  │
│  • Excel files in folder │ ◄────────  /tenant-logo.png   │  • FastAPI backend     │
│  • scc-agent.exe service │            JWT auth cookie     │  • Postgres + Redis    │
└──────────────────────────┘                                │  • Dashboard (HTML)    │
                                                            └────────────────────────┘
```

| Layer | Where it runs | Tech |
| ----- | ------------- | ---- |
| Backend + dashboard | Railway (one service) | FastAPI · SQLAlchemy 2.0 · Postgres · Redis |
| Agent | Customer's Windows machine | Python 3.12 → PyInstaller `.exe` · NSSM service · DPAPI creds |
| Object storage | Cloudflare R2 (optional — falls back to local disk) | S3-compatible |

---

## Quick deploy on Railway (5 min)

> Requires a Railway account at https://railway.app. Free tier is fine for testing.

### 1. Create the project

1. Go to https://railway.app/new → **Deploy from GitHub repo** → select **`Complete3-Tech-Solutions/sellers-dashboard`**.
2. Railway detects [railway.json](railway.json) and uses [backend/Dockerfile](backend/Dockerfile) automatically.
3. The first build will **fail** because there's no database yet. That's expected — go to step 2.

### 2. Add the plugins

In the Railway project:

- **+ New → Database → Add PostgreSQL** — sets `DATABASE_URL`.
- **+ New → Database → Add Redis** — sets `REDIS_URL`.

Railway injects both env vars into the backend service automatically — no manual wiring needed.

### 3. Set required environment variables

On the backend service → **Variables** tab, add:

| Variable | Value | Purpose |
| -------- | ----- | ------- |
| `ENV` | `dev` | Lets the app auto-generate ephemeral JWT keys and a Fernet key on boot — fine for testing. For production, see [Production variables](#production-variables-optional). |
| `AUTO_SEED` | `true` | On first boot, seeds a "Dev Tenant" with the 2013 dataset so you can log in immediately. Remove this var after the first successful deploy. |
| `COOKIE_SECURE` | `true` | Railway serves over HTTPS — cookies should be Secure. |
| `ALLOWED_ORIGINS` | `https://<your-railway-domain>.up.railway.app` | Same origin as the deployed service. |

### 4. Generate a public domain

Backend service → **Settings → Networking → Generate Domain**. You'll get something like `sellers-dashboard-production.up.railway.app`.

### 5. Redeploy

After adding the plugins and variables, click **Deploy** again. The service should start cleanly:

```
INFO ... Uvicorn running on http://0.0.0.0:8080
INFO ... auto-seed complete
```

### 6. Log in

Visit your Railway domain → you'll be redirected to `/login`. Use the seeded credentials:

- **Email:** `dev@example.com`
- **Password:** `devpassword`

You should see the 2013 dashboard rendered from the backend API.

### Production variables (optional)

Once you want the app to survive a restart without re-issuing tokens or losing per-tenant data:

| Variable | Notes |
| -------- | ----- |
| `ENV` | Set to `prod`. |
| `JWT_PRIVATE_KEY_PEM` / `JWT_PUBLIC_KEY_PEM` | `openssl genrsa -out priv.pem 2048 && openssl rsa -in priv.pem -pubout -out pub.pem`, paste contents. |
| `KMS_FERNET_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_ENDPOINT_URL` | Cloudflare R2. Without these, the app stores uploads on the container's local disk (lost on redeploy). |
| `SENTRY_DSN_BACKEND` | Error reporting. |
| `COOKIE_DOMAIN` | If you put the app behind a custom domain. |

---

## Running the agent on your local computer

The agent is the piece that ships **to the customer**, but you can also run it on your own Windows machine to test the full ingestion loop against your Railway deployment.

### Option A — run from source (fastest for testing)

```powershell
git clone https://github.com/Complete3-Tech-Solutions/sellers-dashboard.git
cd sellers-dashboard\agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Create the agent's data directory + config
$pd = "$env:PROGRAMDATA\SCCAgent"
New-Item -ItemType Directory -Force -Path $pd | Out-Null

@"
api_base_url  = "https://<your-railway-domain>.up.railway.app"
watch_folder  = "C:\path\to\your\excel\folder"
debounce_secs = 8
poll_interval = 30
log_level     = "INFO"
"@ | Set-Content -Encoding utf8 "$pd\config.toml"
```

Issue an API key in the dashboard (sign in as admin → **the admin endpoints work via API today**; a UI is on the roadmap):

```powershell
# After you've logged into the dashboard, copy the access_token cookie from
# DevTools and paste it below — or use the JSON shown by /auth/login.
$base = "https://<your-railway-domain>.up.railway.app"
$cookie = "<paste access_token cookie value>"

$key = Invoke-RestMethod -Method POST -Uri "$base/api/admin/api-keys" `
  -Headers @{ Authorization = "Bearer $cookie"; "Content-Type" = "application/json" } `
  -Body '{"label":"local-test"}'
$key.full_key   # ← copy this; shown once
```

Persist the key and run the agent:

```powershell
python -m scc_agent --store-key "scc_live_xxxxxxxxxxxxxxxxx.yyyyyyyyyyyy"
python -m scc_agent
```

Now drop a `.xlsx` into your watch folder, save it, and within ~15 s the dashboard reloads with parsed data.

### Option B — install as a Windows service (mirrors the customer experience)

```powershell
cd sellers-dashboard\agent
pip install -e ".[dev]"
python build.py                  # produces dist\scc-agent.exe

# Bundle the .exe with installer scripts + nssm.exe (https://nssm.cc)
mkdir release
copy dist\scc-agent.exe release\
copy installer\install.ps1 release\
copy installer\uninstall.ps1 release\
# Drop nssm.exe into release\ as well.

cd release
.\install.ps1 -ApiKey "scc_live_xxx.yyy" `
              -WatchFolder "C:\path\to\excel\folder" `
              -ApiBaseUrl "https://<your-railway-domain>.up.railway.app"
```

The service runs under LocalSystem, stores the API key encrypted with DPAPI (LocalMachine scope), and auto-starts at boot. Logs land in `C:\ProgramData\SCCAgent\logs\`.

---

## Local development (without Railway)

```bash
docker compose up -d                       # Postgres + Redis
cd backend
python -m venv .venv
. .venv/Scripts/activate                   # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
python -m app.seed                         # loads 2013 dataset
uvicorn app.main:app --reload --port 8000
```

Then http://localhost:8000 → `dev@example.com` / `devpassword`.

In another shell, run the agent against localhost:

```powershell
cd agent
pip install -e ".[dev]"
# point config.toml at http://localhost:8000, then:
python -m scc_agent
```

---

## Repository layout

```
sellers-dashboard/
├── README.md                  ← this file
├── PLAN.md                    ← full design spec
├── railway.json               ← Railway build config
├── Procfile                   ← alt start commands (web / worker)
├── docker-compose.yml         ← local Postgres + Redis
├── backend/                   ← FastAPI service deployed to Railway
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/               ← SQL migrations (RLS enabled)
│   ├── app/
│   │   ├── main.py            ← FastAPI entry + AUTO_SEED lifespan
│   │   ├── settings.py        ← env-driven config (normalises Railway DATABASE_URL)
│   │   ├── security.py        ← Argon2id, JWT RS256, HMAC, Fernet
│   │   ├── models/            ← SQLAlchemy 2.0 models
│   │   ├── routers/           ← /auth, /api/dashboard, /api/snapshot, /api/admin
│   │   ├── services/          ← Excel parser, storage (R2 + local fallback), rate limit
│   │   ├── workers/           ← RQ job (parser also runs inline when PARSER_INLINE=true)
│   │   ├── seed.py            ← `python -m app.seed`
│   │   └── seed_data.json     ← embedded 2013 dataset
│   └── tests/
├── dashboard/                 ← served by the backend as static files
│   ├── index.html             ← original SCC dashboard, modified to fetch from API
│   ├── login.html             ← sign-in form
│   └── assets/scc.png         ← default logo (tenants can override)
├── agent/                     ← Windows agent (runs on customer's PC)
│   ├── pyproject.toml
│   ├── scc_agent/             ← watcher, uploader, state, DPAPI creds
│   ├── installer/             ← install.ps1, uninstall.ps1, version.txt
│   └── build.py               ← PyInstaller spec
└── docs/
    ├── customer-install.md
    └── admin-runbook.md
```

---

## API surface (quick reference)

| Method | Path | Auth | Purpose |
| ------ | ---- | ---- | ------- |
| `POST` | `/auth/register-tenant` | none | Create a tenant + admin user |
| `POST` | `/auth/login` | none | Sets `access_token` + `refresh_token` cookies |
| `POST` | `/auth/refresh` | refresh cookie | Rotate tokens |
| `POST` | `/auth/logout` | cookie | Revoke refresh + clear cookies |
| `GET`  | `/auth/me` | cookie | Current user + tenant |
| `GET`  | `/api/years` | cookie | Years with data for this tenant |
| `GET`  | `/api/dashboard?year=YYYY` | cookie | Full dashboard payload |
| `POST` | `/api/snapshot/start` | HMAC key | Begin a snapshot |
| `POST` | `/api/snapshot/{id}/file` | HMAC key | Upload an xlsx |
| `POST` | `/api/snapshot/{id}/commit` | HMAC key | Finalize + (parse inline or enqueue) |
| `GET`  | `/api/snapshot/{id}` | HMAC key | Status |
| `POST` | `/api/admin/api-keys` | admin cookie | Issue a new agent key (returned once) |
| `GET`  | `/api/admin/api-keys` | admin cookie | List keys |
| `DELETE` | `/api/admin/api-keys/{id}` | admin cookie | Revoke key |
| `GET`  | `/api/admin/snapshots` | admin cookie | Recent ingestion runs |
| `GET`  | `/api/admin/audit` | admin cookie | Audit log |
| `POST` | `/api/admin/logo` | admin cookie | Upload tenant logo |
| `POST` | `/api/admin/users` | admin cookie | Invite member |

Agent → server requests include four extra headers: `Authorization: Bearer <key_id>.<secret>`, `X-Timestamp`, `X-Nonce`, `X-Signature` (hex HMAC-SHA256 over `METHOD\nPATH\nTIMESTAMP\nNONCE\nsha256(body)`). See [PLAN.md §5.4](PLAN.md).

---

## What's intentionally simplified for the testing deployment

- **Parser runs inline** at commit time (single Railway service is fine). For production, set `PARSER_INLINE=false` and run a second Railway service with start command `rq worker --url $REDIS_URL snapshots`.
- **Object storage falls back to local disk** when R2 env vars aren't set — uploads survive within a single container run but are lost on redeploy. Add R2 before relying on the audit trail.
- **JWT keys auto-generate** at startup when `ENV=dev`. Sessions invalidate on every restart. Set `JWT_PRIVATE_KEY_PEM` + `JWT_PUBLIC_KEY_PEM` for stable auth.
- **No admin UI yet** — admin endpoints exist (`/api/admin/*`) and work via curl/Postman; HTML screens are on the roadmap (Phase 7).

---

## Roadmap (from PLAN.md §9)

- [x] Phase 0–3: scaffolding, auth, dashboard API, ingestion API
- [x] Phase 4: Excel parser + RQ worker
- [x] Phase 5–6: agent, installer, PyInstaller build
- [ ] Phase 7: Admin UI screens
- [ ] Phase 8: Hardening (TOTP UX, IP allowlist UX, RLS cross-tenant test, Sentry, WAF, backups)
- [ ] Phase 9: Customer pilot

See [PLAN.md](PLAN.md) for the full design document.

---

## Support

- Issues: https://github.com/Complete3-Tech-Solutions/sellers-dashboard/issues
- Email: help@complete3tech.com
