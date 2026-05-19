# SCC Profitability SaaS — Implementation Plan

> Spec for the implementation. Every decision is locked. No "either/or."
> Follow the phases in order. Each phase has acceptance criteria.

---

## 0. What we're building

A multi-tenant SaaS that takes the existing `SCC_Profitability_Dashboard2.html` and turns it into a live, login-protected dashboard. Customers run a small Windows agent on the server where their job-cost Excel files live. The agent watches the folder; whenever a file changes, the changed files are uploaded over HTTPS to the SaaS backend, which stores the raw files (audit trail) and parses them into structured data that the dashboard renders.

**Three deliverables:**

1. **`backend/`** — FastAPI app (auth, ingestion API, dashboard API, static frontend)
2. **`dashboard/`** — modified version of the existing HTML + new login page
3. **`agent/`** — Python script packaged as a Windows service that watches a folder and uploads changed files

---

## 1. Locked technical decisions

| Concern | Choice | Rationale |
|---|---|---|
| Backend language | Python 3.12 | Matches agent; rich Excel ecosystem |
| Web framework | FastAPI | Async, OpenAPI built-in, fast |
| Database | PostgreSQL 16 | RLS for tenant isolation |
| ORM | SQLAlchemy 2.0 async | Standard |
| Migrations | Alembic | Standard |
| Cache / nonces / queue | Redis 7 | Single dep, multi-use |
| Background jobs | RQ (Redis Queue) | Simpler than Celery |
| Object storage | Cloudflare R2 (S3-compatible) | Zero egress, S3 API |
| Password hashing | Argon2id via `argon2-cffi` | Modern, tunable cost |
| Auth tokens | JWT RS256 — access 15 min, refresh 7 d (rotation) | Stateless API |
| Auth storage in browser | `httpOnly` cookie, `Secure`, `SameSite=Lax` | XSS-resistant |
| Frontend | Existing HTML, minimally modified | Zero design rework |
| Agent language | Python 3.12 | Same as backend |
| Agent file watcher | `watchdog` 4.x | Cross-platform |
| Agent packaging | PyInstaller → single `.exe` | No Python install on customer |
| Agent service mgmt | NSSM | Free, reliable |
| Agent credential storage | Windows DPAPI (LocalMachine scope) | OS-native |
| Agent → server auth | API key (Bearer) + HMAC-SHA256 signed requests | Defense in depth |
| Replay protection | Timestamp ±5 min + nonce cache 10 min | Standard |
| TLS / edge | Cloudflare → origin | TLS 1.3, HSTS, WAF |
| Hosting (testing) | Railway | One service + Postgres + Redis plugins |
| Email | Postmark | Transactional |
| Error monitoring | Sentry | Both backend and agent |
| Logs | Railway log drain / Better Stack | Structured JSON |
| CI | GitHub Actions | Lint, test, build agent .exe |

---

## 2. Repository layout

```
sellers-dashboard/
├── README.md
├── PLAN.md                          # this file
├── railway.json                     # Railway build config
├── Procfile                         # web + worker entrypoints
├── docker-compose.yml               # local Postgres + Redis
├── .github/workflows/
│   ├── backend.yml                  # test backend on push to main
│   └── agent.yml                    # build .exe on tag, attach to release
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── alembic/versions/
│   └── app/
│       ├── main.py
│       ├── settings.py
│       ├── db.py
│       ├── deps.py
│       ├── security.py
│       ├── models/
│       ├── schemas/
│       ├── routers/
│       ├── services/                # parser, storage, rate_limit
│       ├── workers/                 # RQ jobs
│       ├── seed.py
│       └── seed_data.json
├── dashboard/
│   ├── index.html                   # modified copy of SCC_Profitability_Dashboard2.html
│   ├── login.html
│   └── assets/scc.png
├── agent/
│   ├── pyproject.toml
│   ├── scc_agent/
│   ├── installer/                   # install.ps1, uninstall.ps1
│   └── build.py                     # PyInstaller spec
└── docs/
    ├── customer-install.md
    └── admin-runbook.md
```

---

## 3. Database schema

Alembic migration `001_initial.py` creates the following tables. All domain tables include `tenant_id` and are protected by Postgres RLS (see `routers` → `set_tenant` per-session).

See [backend/alembic/versions/001_initial.py](backend/alembic/versions/001_initial.py) for the authoritative DDL.

Tables:
- `tenants`, `users`, `refresh_tokens`
- `api_keys` (with `secret_hash` + KMS-encrypted `secret_ciphertext` for HMAC verify)
- `snapshots`, `snapshot_files`
- `projects`, `monthly_metrics`, `quarterly_metrics`, `overhead_detail`
- `audit_log`

RLS tables: `projects`, `monthly_metrics`, `quarterly_metrics`, `overhead_detail`, `snapshots`, `snapshot_files`.

Every DB session sets `SET LOCAL app.tenant_id = '<uuid>'` immediately after the auth dependency resolves. If application code ever forgets `WHERE tenant_id =`, RLS still prevents cross-tenant leaks.

---

## 4. Backend API specification

Base URL: `https://<your-railway-domain>.up.railway.app` (or your custom domain). All endpoints return JSON unless noted.

### 4.1 Auth endpoints (`/auth`)

- `POST /auth/register-tenant` — Creates tenant + admin user. Rate limit: 5/hour/IP.
- `POST /auth/login` — Sets `access_token` (15 min) and `refresh_token` (7 d) httpOnly cookies. Argon2id verify. Rate limit: 5/min/IP, 20/hr per email.
- `POST /auth/refresh` — Rotates refresh; revokes whole family on reuse-after-rotation (theft detection).
- `POST /auth/logout` — Revokes refresh, clears cookies.
- `GET /auth/me` — Current user + tenant.
- `POST /auth/2fa/enroll`, `/auth/2fa/verify`, `/auth/2fa/disable` — TOTP via `pyotp`.

### 4.2 Dashboard endpoints (`/api`)

- `GET /api/years` — `{ "years": [2013, ...], "default": 2013 }`
- `GET /api/dashboard?year=2013` — Returns the **exact same shape** as the original embedded `DATA["2013"]` literal so the existing JS works unchanged. Cached per `(tenant_id, year)` with 60 s TTL.

### 4.3 Ingestion endpoints (`/api/snapshot`)

All ingestion endpoints require both Bearer API key and HMAC signature headers.

- `POST /api/snapshot/start` — Opens a snapshot. Auto-expires after 1 hour without commit.
- `POST /api/snapshot/{snapshot_id}/file` — Multipart. Magic-byte check (`PK\x03\x04`). Max 50 MB/file.
- `POST /api/snapshot/{snapshot_id}/commit` — Verifies the uploaded files match the manifest, marks snapshot `committed`, parses (inline or via RQ job).
- `GET /api/snapshot/{snapshot_id}` — Status.

### 4.4 Admin endpoints (`/api/admin`)

Require `role=admin`.

- `POST /api/admin/api-keys` — Issue. Returns plaintext **once**.
- `GET /api/admin/api-keys` — List.
- `DELETE /api/admin/api-keys/{id}` — Revoke.
- `GET /api/admin/snapshots?limit=50` — Recent ingestion runs.
- `GET /api/admin/audit?limit=100` — Audit log.
- `POST /api/admin/logo` — Upload tenant logo.
- `POST /api/admin/users` — Invite member.

### 4.5 Static endpoints

- `GET /` — If logged in: serve `dashboard/index.html`; else redirect `/login`.
- `GET /login` — Serve `dashboard/login.html`.
- `GET /assets/*` — Static files.
- `GET /tenant-logo.png` — Tenant logo from R2 (or default).

---

## 5. Auth and security implementation

### 5.1 Password hashing — Argon2id (time_cost=3, memory_cost=64 MiB, parallelism=4).

### 5.2 JWT — RS256, 2048-bit. Access 15 min, refresh 7 d. Rotation; revoke family on reuse.

### 5.3 API key — `scc_live_<12chars>.<48chars>`. We store: `key_id`, `sha256(secret)`, and a Fernet-encrypted copy of the secret for HMAC verify.

### 5.4 Request signing (agent → server)

```
Authorization: Bearer <key_id>.<secret>
X-Timestamp: <unix>
X-Nonce: <uuid4>
X-Signature: hex(hmac_sha256(secret, METHOD + "\n" + PATH + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + sha256(body)))
```

Server verifies: key lookup → IP allowlist → secret hash → timestamp window (±5 min) → nonce SETNX (10 min TTL) → HMAC `compare_digest` → rate limit → request.

### 5.5 Rate limiting (Redis sliding window)

- Login: 5/min/IP, 20/hr/email
- Register: 5/hr/IP
- Snapshot: 60 req/min/api_key
- Generic: 600 req/min/IP

### 5.6 TLS / network — Railway provides TLS termination. Add HSTS via `SecurityHeadersMiddleware`. CSP narrowly tuned to the dashboard's external CDN deps.

---

## 6. Excel parser

Reads SCC's "Profit Summary" workbooks ([backend/app/services/parser.py](backend/app/services/parser.py)).

### Real-world file layout

Customer files live on a network share, e.g. `\\sgc-fs01\Company Files\Profit Summaries\`, named:

| Filename | Year | Notes |
| -------- | ---- | ----- |
| `2013 PS SCC.xlsx` | 2013 | One file per year |
| `2015 PS SCC.xlsx` + `2015 PS SCC NEW.xlsx` | 2015 | Two revisions — newer mtime wins on overlapping job #s |
| `2016 PS SCC - 4.22.16.xlsx` + `2016 PS SCC 7.27.16.xlsx` | 2016 | Same idea |
| `Profit_Summary_Template.xlsx` | — | Layout template, skipped by agent + parser |

Each workbook has a single sheet with **12 stacked monthly blocks** (Jan → Dec):

```
###  | JOB #  | PROJECT NAME            | % COMPL | CONTRACT | COST | PROFIT | %    ← header
1    | 323    | Shelby West - AGC       | 0.5     | 116825   | 91998 | 24827  | 21%
2    | 419    | POB 110 Renovation      | 1       | 18231    | 11625 | 6606   | 36%
...                                                                                  ← project rows
     |        |                         |         | 187760   | 140350 | 47410 |     ← month totals (Jan)
     |        | CUMULATIVE TOT          |         | ...                              ← cumulative (skipped)
###  | JOB #  | PROJECT NAME            | ...                                       ← next month header (Feb)
```

Columns past `%` (col H) carry secondary data the dashboard doesn't use (`Est. Profit`, `QB`, `$$$`, `CTC`, `OPEN PO`) — parser ignores them.

### Implementation

- Uses `openpyxl` read-only, `data_only=True` (reads formula results, not formulas).
- Detects month boundaries by header rows (col B = `JOB #`, col C = `PROJECT NAME`).
- Assigns each project's `last_month` from its containing block's position (0–11 → January–December).
- Reads each block's monthly-totals row (blank ID + numeric CONTRACT/PROFIT) and uses it as `monthly[].gross_profit`. Falls back to summing project profits per month when the totals row is missing.
- Skips "CUMULATIVE TOT" rows.
- Currency parsing strips `$`, `,`, `(...)` → negative. Treats `#DIV/0!`/`#REF!`/`INVOICED`/`PMT RECD` sentinels as null.
- Dedupes by `job_no` when multiple files for the same year are in one snapshot — last (by mtime) wins.
- `invoiced` and `pmt_recd` are not present in the Profit Summary file format; they remain `null` until a separate invoicing source is added.
- Overhead data is similarly absent — `overhead` defaults to `0` per month so `net_profit == gross_profit` for the testing tier.

### Worker (`backend/app/workers/parse_snapshot.py`)

1. Loads committed snapshot.
2. Downloads files from object storage to tempdir.
3. Parses with `parser.parse_folder`.
4. In a transaction: deletes existing year data, inserts fresh rows.
5. Invalidates dashboard cache.
6. On failure: marks snapshot `failed`, records error message.

When `PARSER_INLINE=true` (default for single-service deploys), the commit endpoint runs the worker synchronously.

---

## 7. Dashboard frontend changes

Existing `SCC_Profitability_Dashboard2.html` → `dashboard/index.html` with three changes:

1. **Embedded `DATA` literal removed** → replaced with `fetch('/api/dashboard?year=Y')`.
2. **Base64 `SCC_LOGO_B64` removed** → masthead `<img>` and PDF export fetch `/tenant-logo.png`.
3. **Year selector wired to API** — populated by `/api/years`, calls `loadYear(value)` on change.

`dashboard/login.html` is a new sign-in form styled to match the dashboard.

---

## 8. Agent specification

See [agent/README.md](agent/README.md) for the developer-facing version, and [docs/customer-install.md](docs/customer-install.md) for the operator-facing one.

- Config: `%PROGRAMDATA%\SCCAgent\config.toml`
- Credentials: `%PROGRAMDATA%\SCCAgent\creds.bin` (DPAPI LocalMachine)
- State: `%PROGRAMDATA%\SCCAgent\state.db` (SQLite — file hash store)
- Watcher: `watchdog` Observer + 30 s safety-net poll + 8 s debounce
- Uploader: signed multipart POST + exponential backoff retry
- Service: NSSM-managed `SCCAgent`, auto-start at boot, runs as LocalSystem

---

## 9. Implementation phases

- [x] **Phase 0** — Scaffolding (½ day)
- [x] **Phase 1** — Auth foundation (2 days)
- [x] **Phase 2** — Dashboard API + static frontend (2 days)
- [x] **Phase 3** — Ingestion API (2 days)
- [x] **Phase 4** — Parser worker (3 days)
- [x] **Phase 5** — Agent prototype (3 days)
- [x] **Phase 6** — Agent service + installer (2 days)
- [ ] **Phase 7** — Admin UI (2 days) — endpoints exist; HTML screens pending
- [ ] **Phase 8** — Hardening (2 days) — TOTP UX, IP allowlist UX, RLS test, Sentry, WAF, backups
- [ ] **Phase 9** — Customer pilot (1 week)

---

## 10. Local development setup

```bash
docker compose up -d                # Postgres + Redis
cd backend
python -m venv .venv && . .venv/Scripts/activate
pip install -e ".[dev]"
alembic upgrade head
python -m app.seed                  # loads the 2013 dataset for a dev tenant
uvicorn app.main:app --reload --port 8000

# In another shell — run the agent
cd agent
pip install -e ".[dev]"
python -m scc_agent --store-key "scc_live_xxx.yyy"
python -m scc_agent
```

---

## 11. Environment variables (backend)

| Var | Purpose | Required? |
|---|---|---|
| `DATABASE_URL` | Postgres connection | Yes (Railway plugin auto-sets) |
| `REDIS_URL` | Redis connection | Yes (Railway plugin auto-sets) |
| `ENV` | `dev` allows auto-generated JWT/Fernet keys | Yes |
| `AUTO_SEED` | `true` to seed dev tenant on first boot | First deploy only |
| `JWT_PRIVATE_KEY_PEM` / `JWT_PUBLIC_KEY_PEM` | RS256 keys | Production |
| `KMS_FERNET_KEY` | For api_key secret encryption | Production |
| `R2_*` | Cloudflare R2 credentials | Optional — falls back to local disk |
| `PARSER_INLINE` | `true` runs parser in commit handler (default) | Optional |
| `COOKIE_DOMAIN`, `COOKIE_SECURE` | Cookie scoping | Production |
| `ALLOWED_ORIGINS` | CORS allow-list (comma-separated) | Yes |
| `SENTRY_DSN_BACKEND` | Error reporting | Optional |
| `POSTMARK_SERVER_TOKEN` | Email | Optional |

---

## 12. What "done" looks like

- Customer's IT runs one `install.ps1` command with the API key the admin shows them in the dashboard.
- The agent starts as a Windows service, watches the Excel folder.
- A bookkeeper opens a `.xlsx`, edits, saves.
- Within ~15 s the dashboard auto-refreshes with new numbers.
- Every saved version is in R2 indefinitely (or local disk for the testing tier).
- Admin can rotate the API key in 30 s. The old key stops working immediately.
- If the parser breaks, you fix it server-side and re-process any past snapshot without touching the customer.

---

## 13. Out of scope for v1

- Mobile app
- White-label custom domains per tenant
- Webhooks for downstream integrations
- SSO / SAML
- Granular roles beyond admin/member
- Real-time push (browser refreshes on focus + 60 s polling is enough)
- mTLS (added for enterprise tier later)
