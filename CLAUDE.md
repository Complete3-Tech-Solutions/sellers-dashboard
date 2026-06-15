# CLAUDE.md

Guidance for working in this repo. Read this before making changes.

## What this is

SCC Profitability SaaS — a multi-tenant FastAPI backend + static HTML dashboard,
plus a Windows desktop **agent** that watches a folder of job-cost Excel files and
uploads them. Deployed as **one Railway service** (backend serves both the API and
the dashboard HTML). Postgres + Redis are Railway plugins.

- **Backend + dashboard** → Railway (FastAPI · SQLAlchemy 2.0 async · Postgres · Redis)
- **Agent** → ships to the customer's Windows PC. Two implementations, same wire protocol:
  - `agent/` (Python) — the original (PyInstaller exe + NSSM service).
  - `go_agent/` (Go) — newer, **preferred for new installs**: one self-contained
    `scc-agent.exe` that is installer + settings GUI + native service in a single binary.

## Repo layout

```
backend/app/
  main.py            FastAPI entry; lifespan runs AUTO_SEED / AUTO_SEED_ADMIN; security headers + CSP
  settings.py        env-driven config (pydantic-settings); normalises Railway DATABASE_URL → asyncpg
  security.py        Argon2id passwords, JWT RS256, HMAC request signing, Fernet secret encryption
  deps.py            get_current_user (cookie or Bearer), require_admin, get_client_ip
  db.py              async engine/session, set_tenant (RLS GUC)
  models/            SQLAlchemy 2.0 models (tenant, user, api_key, snapshot, project, audit)
  routers/           auth, dashboard, ingest, admin, static
  schemas/           pydantic request/response models
  seed.py            `python -m app.seed`       → loads embedded 2013 demo dataset into "dev" tenant
  seed_admin.py      `python -m app.seed_admin`  → ensures login users only, NO demo data
  seed_data.json     embedded 2013 dataset
backend/alembic/     migrations (run on deploy: `alembic upgrade head`)
dashboard/           static HTML served by the backend (index = dashboard, admin = admin panel)
agent/scc_agent/     desktop agent (Python): watcher → sync → uploader (HMAC-signed); creds in DPAPI
agent/installer/     install.ps1 / uninstall.ps1 (NSSM service, --store-key for the API key)
go_agent/            desktop agent (Go) — single self-contained scc-agent.exe:
  cmd/scc-agent/       entrypoint: no-args→settings GUI (lxn/walk), run→service, install/uninstall
  internal/            config, creds (DPAPI), state (modernc sqlite), uploader, watcher, sync,
                       service (native Windows service), arp (Apps & features registration)
```

## Commands

```bash
# Backend (from backend/)
pip install -e '.[dev]'
docker compose up -d db redis          # local Postgres + Redis (compose at repo root)
alembic upgrade head
uvicorn app.main:app --reload          # serves API + dashboard at :8000
pytest                                 # tests in backend/tests/
ruff check app                         # lint (E,F,W,I,B,UP; E501 ignored; py312)

python -m app.seed                     # seed 2013 demo data + dev admin
python -m app.seed_admin               # seed login users only (no demo data)

# Agent — Python (from agent/)
pip install -e '.[dev]' && pytest

# Agent — Go (from go_agent/)
go test ./...                          # unit tests
make build                            # host binary (dev) → dist/scc-agent
make windows                          # the single shipping exe → dist/scc-agent.exe
# (cross-compiles from macOS/Linux; embeds UAC manifest, builds GUI-subsystem)
```

After editing Python, byte-compile-check changed files: `python3 -m py_compile <files>`.
There is no Python on PATH as `python` here — use `python3`.

## Architecture notes that aren't obvious

- **Single service, route order matters.** `static.py` is included LAST in `main.py` so
  `/api/*` routes win; the static catch-all serves the dashboard otherwise.
- **Auth.** Login sets `access_token` + `refresh_token` httponly cookies. Access = JWT RS256
  (15 min) carrying `sub`/`tid`/`role`; refresh tokens are hashed in `refresh_tokens` with
  family-based theft detection. `require_admin` checks the `role` claim.
- **Multi-tenant by schema, single-tenant in practice.** Every row is scoped by `tenant_id`
  (`users` are unique per `(tenant_id, email)`), but login looks users up by email globally.
  This deployment runs as ONE tenant — see "Operational model" below.
- **Agent auth is one-directional.** The agent stores its key locally (`creds.bin`, DPAPI on
  Windows) and signs uploads with HMAC. **The server can never push to the agent** — it only
  receives. Any key change reaches the agent by re-installing the key on the agent machine
  (Python: `scc-agent.exe --store-key "<key>"`; Go: the settings GUI, or `scc-agent.exe
  store-key "<key>"`), not by the server reaching out.
- **Go agent specifics (`go_agent/`).** One `scc-agent.exe` does everything via subcommands:
  double-click → auto-elevating settings GUI (embedded `requireAdministrator` manifest), SCM →
  service, `uninstall` → headless full removal. The native Windows service is registered
  Automatic (Delayed Start) with crash-recovery restart, and an Apps & features entry is added
  so it uninstalls the standard Windows way. The GUI reopens (Start Menu/Desktop shortcut) as a
  settings editor that rewrites `config.toml` and restarts the service. Wire protocol, HMAC
  signing, and heartbeat behaviour are identical to the Python agent — only packaging differs.
  CI: `.github/workflows/go-agent.yml` builds/signs/releases on `go-agent-v*` tags.
- **Heartbeat + sync-on-demand (agent v0.2+).** The agent pings `POST /api/snapshot/heartbeat`
  every `poll_interval` (default 30s); this stamps `api_keys.last_used_at` (the Agent page reads
  it as "last seen" liveness) and returns whether an admin requested a sync. "Request sync now"
  on the Agent page (`POST /api/admin/api-keys/{id}/request-sync`) sets a short-lived Redis flag
  (`agent:sync_req:{key_id}`, 10-min TTL) that the next heartbeat consumes, triggering a forced
  full re-upload (`sync_once(force=True)`). Still pull-based — the server never initiates a
  connection. **Idle agents make no network calls** (a no-change `sync_once` returns early), so
  liveness comes from the heartbeat, not from uploads.
- **API key secrets.** Stored as a sha256 hash AND a Fernet ciphertext. The full key is only
  shown once, at create/rotate time. The Agent page never renders secrets on screen.
- **Parser runs inline** at snapshot commit by default (`PARSER_INLINE=true`) so a single
  Railway service works; set false + run an `rq worker` for a separate worker.
- **Dashboard data is per-tenant and per-year.** `seed.py` deletes+reinserts per year (idempotent).
  Real data comes from agent uploads; demo data (2013) is separate years in the same tenant.
- **Billing columns are unreliable.** `INVOICED`/`PMT RECD`/`OPEN PO` in the source spreadsheets
  hold stale template values (identical across 2012–2025), so the Cash Position chart + A/R table
  columns are **hidden** in the dashboard. See [data_issue.md](data_issue.md). Don't "fix" the
  parser for these — the mapping is correct; the source data isn't.

## Operational model (IMPORTANT — current deployment)

**This is a single-tenant deployment.** Decisions baked into the code:

- **Self-service signup is disabled.** `ALLOW_REGISTRATION` (settings, default `false`) gates the
  `/register` page and `POST /auth/register-tenant`. Keep it `false`. There is one tenant; the
  admin adds everyone else from the admin panel.
- **Seeding login users:** prefer `AUTO_SEED_ADMIN=true` + `seed_admin.py` over `AUTO_SEED`.
  - `seed_admin` always seeds an admin (`ADMIN_EMAIL`/`ADMIN_PASSWORD`); the member user is
    OPTIONAL (only when `USER_EMAIL`/`USER_PASSWORD` are both set).
  - It defaults to the **`dev` tenant slug** (same as `app.seed` + agent uploads) so seeded
    users see existing data instead of a fresh empty tenant. Don't set `SEED_TENANT` unless you
    intend a different tenant.
  - `ADMIN_PASSWORD`/`USER_PASSWORD` are REQUIRED outside dev (`ENV=prod`) — no weak defaults.
  - `SEED_REMOVE_EMAIL` deletes a legacy user (e.g. `dev@example.com`) on boot; it never deletes
    the users it just seeded. One-time cleanup.
  - `SEED_RESET_PASSWORD=true` resets seeded passwords to the current env values.
- **Don't run `AUTO_SEED` and `AUTO_SEED_ADMIN` together long-term** — `AUTO_SEED` recreates the
  demo `dev@example.com` admin (`devpassword`) on every boot, which is a security hole.
- **Railway** deploys via `backend/Dockerfile` (`railway.json`). Start command runs
  `alembic upgrade head` then uvicorn. Healthcheck `/health`. Keep `COOKIE_SECURE=true`,
  `ENV` set, `ALLOWED_ORIGINS` = the deployed origin, and `KMS_FERNET_KEY` + JWT keys for prod.

## Admin panel (dashboard/admin.html, served at /admin, admins only)

Sections, each backed by `/api/admin/*`:

- **Agent** (default landing) — the focused "which agent is connected" page. Shows the active
  key's label / key ID / IP allowlist / connection status (last sync time+IP), no secret.
  **Rotate key & download new** → `POST /api/admin/api-keys/{id}/rotate` revokes the old key,
  issues a new one (carrying label + IP allowlist), and downloads `scc-agent-key.txt` with the
  new key + install instructions. **Generate agent key** when none exists. This is how you
  change the connected agent: rotate here, install the downloaded key on the target machine.
- **API Keys** — advanced multi-key management: create / list / revoke.
- **Users** — list + invite (`POST /api/admin/users`), plus per-row **Reset password**,
  **Make admin/member** (`PATCH /api/admin/users/{id}`), and **Remove** (`DELETE`). Guardrails:
  can't delete/demote yourself or the last admin; role/password changes revoke that user's
  refresh tokens; everything is audit-logged.
- **Snapshots** — agent upload sessions (status/files/size/timestamps).
- **Audit Log** — last 100 security events for the tenant.
- **Settings** — tenant logo upload (PNG ≤ 2 MB).

## Login / navigation UX

- After login, **everyone lands on the dashboard** (`/`). Admins get an `⚙️ Admin` link +
  `Sign out` in the dashboard header (role fetched via `/auth/me`). The admin panel has a
  `← Dashboard` link back. `/login` and `/register` redirect logged-in users to `/`.

## Conventions

- Match surrounding style; no needless comments. Async SQLAlchemy throughout (`AsyncSession`,
  `select(...)`, `await session.execute`). Pydantic v2 schemas in `schemas/`.
- Audit-log security-relevant admin actions (`AuditLog(action=..., tenant_id, user_id, resource)`).
- File references in chat use markdown links, e.g. [admin.py](backend/app/routers/admin.py).
- Commit only when asked; branch off `main`; this work lives on `feature-dashboard_enhancement`.
