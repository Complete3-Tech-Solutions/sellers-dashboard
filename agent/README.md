# SCC Profitability Agent

A small Windows service that watches a folder of job-cost Excel files and uploads changes to the SCC Profitability SaaS over HTTPS, signed with HMAC-SHA256.

It also sends a periodic heartbeat so the dashboard can show the connection is alive, and picks up admin-requested "sync now" commands on that same heartbeat. Communication stays one-directional — the agent always initiates; the server never connects to it.

## Run from source (dev)

```powershell
cd agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Store an API key (issued by the admin in the dashboard)
python -m scc_agent --store-key "scc_live_xxx.yyy"

# Or set up a config file manually under %PROGRAMDATA%\SCCAgent\config.toml:
#   api_base_url  = "https://api.scc-saas.com"
#   watch_folder  = "C:\\SCC\\Reports"
#   debounce_secs = 8     # wait this long after a file change before uploading
#   poll_interval = 30    # folder re-scan AND heartbeat cadence, in seconds
#   log_level     = "INFO"

python -m scc_agent
```

## How it syncs

- **On change** — a filesystem watcher detects edits to `.xlsx`/`.xlsm` files and uploads
  them after `debounce_secs` (default 8s). Templates and Excel temp files are ignored.
- **Safety re-scan** — every `poll_interval` (default 30s) the folder is re-scanned in case a
  filesystem event was missed. Only files whose SHA-256 changed (or were deleted) are sent, so
  an unchanged folder produces **no network traffic**.
- **Heartbeat** — every `poll_interval` the agent also pings `POST /api/snapshot/heartbeat`.
  This is what the dashboard's Agent page reads as "last seen" / connection-active, since an
  idle agent otherwise never contacts the server.
- **Sync on demand** — when an admin clicks **Request sync now** in the dashboard, the next
  heartbeat returns a flag and the agent performs a forced full re-upload of every current file
  (not just changed ones), guaranteeing the server holds the latest data. The agent typically
  responds within one `poll_interval`.

## Build the .exe

```powershell
pip install pyinstaller
python build.py
# Produces dist\scc-agent.exe
```

## Install as a Windows service

Bundle `scc-agent.exe`, `install.ps1`, `uninstall.ps1`, and `nssm.exe` (download from https://nssm.cc) into a folder, then run as Administrator:

```powershell
.\install.ps1 -ApiKey "scc_live_xxx.yyy" -WatchFolder "C:\SCC\Reports"
```

The service runs under LocalSystem so DPAPI LocalMachine credentials are readable by the service and nothing else.

## Upgrading

The heartbeat and **Request sync now** features require agent **v0.2.0 or later**. Older installs
keep uploading on change but never heartbeat, so the dashboard shows them as stale and "Request
sync" times out. To upgrade, rebuild the `.exe` and re-run `install.ps1` on the agent machine
(the stored API key and config are preserved).
