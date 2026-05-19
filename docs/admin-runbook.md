# Admin runbook

Operational playbook for the people running the SaaS, not the customer.

## Daily

- Nothing. The system is unattended.

## Weekly

- Check Sentry for new error groups.
- Spot-check Better Stack / Logtail for unusual auth failure spikes.
- Skim `audit_log` for any unfamiliar `login.failed` patterns.

## Monthly

- Verify Postgres point-in-time backups by restoring last week's snapshot to a scratch database.
- Rotate Fly secret `JWT_PRIVATE_KEY_PEM` if it has been a year.

## Incident: customer says "dashboard is stale"

1. Get the tenant slug from the user's email.
2. `SELECT * FROM snapshots WHERE tenant_id = ... ORDER BY started_at DESC LIMIT 10;`
   - If the most recent row's status is `failed`, the parser couldn't read their files → see "Parser blew up" below.
   - If status is `committed` but never moves to `parsed`, the RQ worker is wedged → check the worker's machine and Sentry.
   - If nothing in the last hour, their agent isn't reporting → see "Agent not connecting" below.

## Incident: parser blew up on a snapshot

1. `SELECT id, error FROM snapshots WHERE status='failed' ORDER BY started_at DESC LIMIT 5;`
2. Pull the snapshot's files from R2: `tenants/{tenant_id}/snapshots/{snapshot_id}/`
3. Reproduce locally:
   ```python
   from app.services import parser; parser.parse_folder(pathlib.Path('local-copy'))
   ```
4. Patch `parser.py`, ship.
5. Re-trigger the job:
   ```python
   from app.workers.parse_snapshot import parse_snapshot_job
   parse_snapshot_job('<snapshot-id>')
   ```

## Incident: agent not connecting

Ask the customer to grab the tail of `C:\ProgramData\SCCAgent\logs\agent.log`. Most common causes:

| Log line                          | Cause                                                | Fix                                                                            |
| --------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------ |
| `401 invalid_key`                 | Key revoked or mistyped                              | Re-issue from Admin UI; re-run installer.                                      |
| `401 timestamp_out_of_range`      | Server clock skew > 5 min                            | Verify NTP is working on the customer's machine.                               |
| `401 nonce_replay`                | The agent re-used a request, almost always a network retry loop hitting cached responses | Restart the service; check for proxies that cache POSTs. |
| `403 ip_not_allowed`              | API key has an IP allowlist that doesn't include them | Update the allowlist in Admin → API Keys.                                      |
| `Connection refused` / DNS errors | Customer's firewall blocks `api.scc-saas.com`        | Have them whitelist the Cloudflare-fronted endpoint.                           |

## Onboarding a new tenant

1. Have the admin sign up at `/`, which creates the tenant + first admin user.
2. They issue an API key from **Admin → API Keys**.
3. They run `install.ps1` on the customer's reporting server with that key.
4. Watch the first few snapshot rows; if parsing fails on real data, iterate on `parser.py`.

## Key rotation (JWT)

1. Generate new keypair: `openssl genrsa -out priv.pem 2048 && openssl rsa -in priv.pem -pubout -out pub.pem`
2. `fly secrets set JWT_PRIVATE_KEY_PEM="$(cat priv.pem)" JWT_PUBLIC_KEY_PEM="$(cat pub.pem)"`
3. Restart the app. Existing sessions are invalidated — users sign back in.

## Useful psql

```sql
-- Disable RLS for a one-off debug query (run as the postgres superuser only)
SET app.tenant_id = '<uuid>';

-- Most recent uploads per tenant
SELECT t.slug, MAX(s.started_at)
FROM snapshots s JOIN tenants t ON t.id = s.tenant_id
GROUP BY t.slug ORDER BY 2 DESC;

-- Files that failed magic-byte check (will show as no row in snapshot_files)
SELECT s.id, s.error FROM snapshots s WHERE s.status='failed' ORDER BY started_at DESC LIMIT 20;
```
