# Deployment Postmortem — SCC Profitability SaaS

A running log of the issues hit while bringing the system up on Railway and the
Windows agent, with root causes and fix commits. Future Corey-or-Claude: scan
this before debugging similar symptoms.

---

## Backend / Server-side

### 1. RLS policy `tenant_id` column does not exist on `snapshot_files`
**Commit:** `25b20e3` — *Migration: fix RLS policy on snapshot_files*

**Symptom:** Initial Railway deploy failed during `alembic upgrade head` with
`column "tenant_id" does not exist`.

**Cause:** The migration's `RLS_TABLES` loop tried to attach a `tenant_id`-based
policy to every RLS-enabled table, but `snapshot_files` doesn't carry
`tenant_id` directly — it's protected via its parent `snapshots` row.

**Fix:** Remove `snapshot_files` from the `RLS_TABLES` loop and add a dedicated
join-based policy:
```sql
CREATE POLICY tenant_isolation ON snapshot_files
    USING (snapshot_id IN (
        SELECT id FROM snapshots
        WHERE tenant_id = current_setting('app.tenant_id', true)::uuid))
    WITH CHECK (...same...)
```

---

### 2. `email-validator` missing for `EmailStr`
**Commit:** `d32da7e` — *Add email-validator for pydantic.EmailStr*

**Symptom:** Railway boot crashed with
`ImportError: email-validator is not installed, run pip install 'pydantic[email]'`.

**Cause:** `schemas/auth.py` and `schemas/admin.py` import `EmailStr`, which
requires the optional `email-validator` extra. Plain `pydantic>=2.7` didn't
pull it in.

**Fix:** In `backend/pyproject.toml`, change `pydantic>=2.7` → `pydantic[email]>=2.7`
and add `email-validator>=2.2` explicitly so the extra isn't conditional on
pydantic's marker logic.

---

### 3. Login 500: tz-aware vs tz-naive datetime mismatch
**Commit:** `9e4577c` — *Fix login 500: declare datetime columns as tz-aware in models*

**Symptom:** `POST /auth/login` returned 500 with
`asyncpg.exceptions.DataError: invalid input for query argument $4: ... (can't subtract offset-naive and offset-aware datetimes)`.
Insert SQL showed `$4::TIMESTAMP WITHOUT TIME ZONE`.

**Cause:** Postgres columns were declared `TIMESTAMP WITH TIME ZONE` (correct
in the initial migration), but the SQLAlchemy ORM models had
`Mapped[datetime]` without an explicit `DateTime(timezone=True)`. SQLAlchemy
inferred naive `DateTime()`, so its bind-parameter cast was `WITHOUT TIME ZONE`.
asyncpg refused the tz-aware UTC values produced by `datetime.now(tz=timezone.utc)`.

**Fix:** Every datetime column across `models/{user,tenant,api_key,snapshot,audit,project}.py`
now uses `mapped_column(DateTime(timezone=True), ...)`. No DB migration needed —
the columns were already correct in Postgres.

**Lesson:** Always declare the column type explicitly when timezone matters.
`Mapped[datetime]` is not enough.

---

### 4. Every authenticated endpoint 500s with no useful error
**Commit:** `14f7068` — *Fix 500 on every authed endpoint: use set_config() for tenant binding*

**Symptom:** Login worked. Every endpoint that depended on `get_current_user`
(dashboard, admin/*, agent verification) returned a generic 500.

**Cause:** `db.py`'s `set_tenant` issued
`SET LOCAL app.tenant_id = :tid` — but **Postgres `SET LOCAL` does not accept
bound parameters**. asyncpg sent `SET LOCAL app.tenant_id = $1` and Postgres
rejected the statement as a syntax error. Login worked because the login
endpoint doesn't call `set_tenant`.

**Fix:** Use the `set_config(name, value, is_local)` function, which is a
regular function call and *does* accept parameters:
```python
await session.execute(
    text("SELECT set_config('app.tenant_id', :tid, true)"),
    {"tid": str(tenant_id)},
)
```

---

### 5. Multipart file upload 500 → `RuntimeError: Stream consumed`
**Commit:** `337d5e0` — *Fix upload_file 500 (Stream consumed): parse multipart form manually*

**Symptom:** Agent could open snapshots but every `POST /api/snapshot/{id}/file`
returned 500. Server traceback: `RuntimeError: Stream consumed` at
`body = await request.body()` inside `verify_agent`.

**Cause:** FastAPI 0.136's dependency resolver parses `Form()` / `File()`
parameters *before* calling `Depends(...)` dependencies. The multipart parser
drains `request.stream()`, so by the time `verify_agent` tries to read
`request.body()` for HMAC verification, the stream is empty.

**Fix:** Drop the `Form()` / `File()` params from `upload_file`'s signature,
take `request: Request` instead, and call `await request.form()` *inside* the
handler — after `verify_agent` has run and cached the body via `request.body()`.
Starlette's `request._body` cache makes `request.form()` reuse the same bytes.

---

### 6. Upload returns 400 `missing_file` even though the file is there
**Commit:** `700f826` — *Fix 'missing_file' 400 on upload: import UploadFile from Starlette*

**Symptom:** After fix #5, uploads returned 400 with detail `missing_file`.

**Cause:** When `request.form()` is called directly (not via FastAPI's
`File(...)` wiring), it returns `starlette.datastructures.UploadFile`, **not**
the FastAPI subclass. The handler's `isinstance(file, fastapi.UploadFile)`
check therefore returned False.

**Fix:** Import `UploadFile` from `starlette.datastructures` directly:
```python
from starlette.datastructures import UploadFile  # not fastapi
```

**Lesson:** FastAPI's `UploadFile` is a subclass — `isinstance` works
*subclass-to-parent*, never *parent-to-subclass*. Don't `isinstance` against
the subclass if the producer emits the parent.

---

### 7. Snapshots commit but no projects appear; only seed data shows
**Commit:** `38217e9` — *Fix silent parse-snapshot failure: add psycopg2 driver, log exceptions*

**Symptom:** Agent uploaded 20 files, snapshot committed `202 Accepted`, but
`/api/years` returned only `[2013]` (the seed data). No `[err]` or `[inf]`
parser log lines appeared in Railway between commit and the next request.

**Cause:** Two-deep bug.
1. The inline parser path calls `parse_snapshot_job`, which is sync code that
   creates a `postgresql+psycopg2://` engine for RQ worker compatibility. But
   `psycopg2` was never in the deps list — only `asyncpg`. The very first line
   of the worker raised `ModuleNotFoundError`.
2. The commit endpoint wrapped `asyncio.to_thread(parse_snapshot_job, ...)` in
   `try / except Exception: pass`. The driver-import error happened *before*
   any internal `try` inside the worker, so the snapshot row was never marked
   `failed` and the exception was silently swallowed.

**Fix:**
1. Add `psycopg2-binary>=2.9` to backend deps.
2. Replace `except: pass` with `log.exception("inline parse failed for snapshot %s", snap.id)`
   so future driver / pre-try errors land in Railway logs immediately.

**Lesson:** Never silently swallow exceptions from a job runner unless the job
itself guarantees it records every failure path. The "the inner code logs it"
comment is a load-bearing assumption that can be violated by anything that
fails *before* the inner try.

---

## Earlier fixes (pre-deployment polish)

### 8. Parser only handled the latest year of a multi-year backfill
**Commit:** `380f776` — *Worker: handle multi-year snapshots (initial backfill)*

**Symptom:** Snapshot containing 17 years of files only produced one year of
dashboard data.

**Cause:** The original `parse_folder()` did `year = max(by_year)` and only
parsed that year's files.

**Fix:** New `parse_folder_all_years()` returns one `ParsedSnapshot` per
discovered year; the worker iterates and applies each independently. The
single-year `parse_folder()` is kept for the seed / tests.

---

### 9. Three accounting modes for multi-year projects
**Commit:** `5810c65` — *Dashboard: three accounting modes + project lifetime endpoint*

**Context:** Multi-year projects double-count in "raw" mode because the same
project appears in multiple yearly workbooks. Added `poc` (scale by % complete)
and `closeout` (only count fully complete) modes so the customer can compare
views. Default stays `raw` to match the existing spreadsheet behavior.
Dashboard has a selector; project lifetime view exposes per-year breakdown for
any single job.

---

### 10. Parser rewritten for the customer's actual file format
**Commit:** `8117d68` — *Parser: handle real SCC Profit Summary file format*

**Context:** Real files are stacked monthly blocks (Jan→Dec) per workbook, with
header rows where col B = `JOB #`, col C = `PROJECT NAME`, and a monthly-totals
row terminating each block. Year is inferred from the filename
(`(?:19|20)\d{2}`). Multiple files for the same year (e.g., 2015 PS SCC.xlsx +
2015 PS SCC NEW.xlsx) are processed oldest-mtime-first so the newest revision
wins on duplicate job numbers. Template files are filtered out.

---

## Operational gotchas (no fix needed, but burned us once)

### Railway: local-disk storage is ephemeral
Without Cloudflare R2 configured, uploaded xlsx files land at
`/app/data/storage/...` inside the container. Every redeploy wipes the
filesystem, so the parser has nothing to read on the next snapshot run. The
Project rows in Postgres persist, but the source files don't. **Fix when
needed:** set `R2_ENDPOINT_URL` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` /
`R2_BUCKET` in Railway Variables and uploads automatically switch to R2.

### Railway: JWT keypair regenerated on every redeploy
`backend/app/security.py` falls back to an ephemeral RSA keypair when
`JWT_PRIVATE_KEY_PEM` / `JWT_PUBLIC_KEY_PEM` env vars are unset. Every
redeploy spawns a new process → new key → all existing session cookies
fail to verify (silently — they get treated as `invalid_token` 401). For
production, generate a real keypair once and set both PEM strings as
Railway Variables (multi-line value works).

### Railway: `SET LOCAL` quirk
See bug #4. Don't use `SET LOCAL` with bound parameters under asyncpg — use
`set_config(name, value, is_local)` function instead.

### `AUTO_SEED=true` runs the seed on every boot
The lifespan hook in `backend/app/main.py` re-runs the seed every time the
container starts. The seed is idempotent (tenant by `slug == "dev"`, user by
`(tenant_id, email)`), but it deletes-and-reinserts the bundled 2013 data on
every run. Once you have a real admin and don't need the demo data,
**remove the `AUTO_SEED` env var** from Railway.

### Tables created by the connecting Postgres user bypass RLS
Postgres `ENABLE ROW LEVEL SECURITY` is enforced for everyone *except* the
table owner, unless you also `ALTER TABLE ... FORCE ROW LEVEL SECURITY`. In
this deployment, Alembic creates tables as the same role the app connects
with, so the role effectively bypasses RLS. This is fine for the
single-tenant dev mode but **revisit before onboarding a second tenant**.

---

## Windows / Agent / PowerShell gotchas

### PowerShell 5.1 writes UTF-8 with BOM
`Set-Content -Encoding utf8` (in Windows PowerShell 5.1) adds a BOM at the
start of the file. Python's stdlib `tomllib` rejects BOM with
`tomllib.TOMLDecodeError: Invalid statement (at line 1, column 1)`.

**Workarounds:**
- Pure-ASCII configs: use `-Encoding ASCII` (no BOM, no special chars).
- Non-ASCII content: PowerShell 7+ supports `-Encoding utf8NoBOM`. For 5.1:
  ```powershell
  [System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
  ```

### Microsoft Store python.exe shim hijacks `python`
A fresh Windows install ships a stub `python.exe` in `%LOCALAPPDATA%\Microsoft\WindowsApps`
that opens the Store when you run it. Symptom: every `python ...` command
prints "Python was not found; run without arguments to install from the
Microsoft Store" even after you install Python.

**Fix:** Install Python from <https://python.org> with **"Add python.exe to
PATH"** checked, then *close every PowerShell window* and reopen. If
`where.exe python` still shows a `WindowsApps\python.exe` first, disable the
alias: Settings → Apps → Advanced app settings → App execution aliases →
toggle off `python.exe` / `python3.exe`.

### Venv activation needs `RemoteSigned` execution policy
`.\.venv\Scripts\Activate.ps1` fails with "running scripts is disabled on this
system" by default.

**Fix once:**
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### `pip install ...` vs `python -m pip install ...`
On systems where multiple Pythons are on PATH (or a user-site install was made
before the venv was activated), `pip` and `python` may resolve to different
installations. `pip install x` succeeds but `python -c "import x"` fails.

**Always use** `python -m pip install <pkg>` — it forces the matching python.

### Agent state DB prevents re-uploads
The agent stores per-file sha256 in `%PROGRAMDATA%\SCCAgent\state.db`. After a
Railway redeploy (which wipes server-side files), the agent thinks everything
is already synced and uploads nothing. To force a full re-upload:
```powershell
Remove-Item "$env:PROGRAMDATA\SCCAgent\state.db"
python -m scc_agent run
```

### API key secret is shown only once
`POST /api/admin/api-keys` returns `full_key` exactly once; only its sha256 is
stored. If it scrolls off the terminal, you can't recover it — revoke and
re-issue. Use `Set-Clipboard` to keep it out of scrollback:
```powershell
$new = Invoke-RestMethod -Method POST ... -WebSession $session
$new.full_key | Set-Clipboard
```

### Pasting the key in chat
Twice now the full API key (key_id + secret) ended up in the conversation log.
**Treat any string that appears in a terminal or screenshot as compromised.**
Revoke immediately via `DELETE /api/admin/api-keys/<id>` and re-issue.

---

## Things still to do

- [ ] Wire up Cloudflare R2 so uploaded xlsx files survive Railway redeploys.
- [ ] Set persistent `JWT_PRIVATE_KEY_PEM` / `JWT_PUBLIC_KEY_PEM` so user
      sessions don't get invalidated on every redeploy.
- [ ] Remove `AUTO_SEED` env var (and the seed bundle) once a real admin user
      exists.
- [ ] Add `FORCE ROW LEVEL SECURITY` to RLS tables, or create a separate
      lower-privilege app role, before multi-tenant onboarding.
- [ ] Build the agent as a standalone `.exe` via `agent/build.py` and install
      it as the `SCCAgent` Windows service on the customer's PC.
