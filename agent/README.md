# SCC Profitability Agent

A small Windows service that watches a folder of job-cost Excel files and uploads changes to the SCC Profitability SaaS over HTTPS, signed with HMAC-SHA256.

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
#   debounce_secs = 8
#   poll_interval = 30
#   log_level     = "INFO"

python -m scc_agent
```

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
