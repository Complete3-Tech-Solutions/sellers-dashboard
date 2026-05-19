# Customer install — SCC Profitability Agent

A small Windows service watches the folder where your job-cost Excel files live and uploads changes to the SCC Profitability dashboard. Once installed, you don't have to do anything — keep working in Excel the way you always have. The dashboard refreshes within ~15 seconds of every save.

## Requirements

- Windows 10 / 11 or Windows Server 2019+
- Administrator access to install a service
- Outbound HTTPS access to `https://api.scc-saas.com`
- An API key from your SCC dashboard admin (looks like `scc_live_xxxxxxx.yyyyyyyyyy`)

## Install (one-time, ~5 minutes)

1. Open the SCC Profitability dashboard and sign in.
2. Go to **Admin → API Keys → Create new key**. Copy the key that appears — **it is shown only once**.
3. Download `scc-agent-<version>.zip` from the link your contact provided. Extract it to a permanent location, e.g. `C:\Program Files\SCCAgent\`.
4. Right-click `install.ps1` → **Run with PowerShell as Administrator**. Or in an elevated PowerShell:

   ```powershell
   cd 'C:\Program Files\SCCAgent'
   # Local path:
   .\install.ps1 -ApiKey "scc_live_xxx.yyy" -WatchFolder "C:\SCC\Reports"
   # Or a UNC path to a network share:
   .\install.ps1 -ApiKey "scc_live_xxx.yyy" -WatchFolder "\\sgc-fs01\Company Files\Profit Summaries"
   ```

5. You should see `SCCAgent installed and started.` The service is now running and will restart automatically on reboot.

## File naming convention

The agent uploads any `.xlsx` / `.xlsm` it sees in the watch folder, with two exceptions:

- Excel lock files (`~$*.xlsx`) and temp files (`*.tmp`) are skipped.
- Any filename containing **`template`** (case-insensitive) is skipped — those are layout references, not data. E.g. `Profit_Summary_Template.xlsx` will stay local.

The fiscal year for each uploaded file is extracted from the first 4-digit year in the filename. The customer's standard naming `<year> PS SCC.xlsx` works as-is:

```
\\sgc-fs01\Company Files\Profit Summaries\
├── 2013 PS SCC.xlsx                  → fiscal year 2013
├── 2014 PS SCC.xlsx                  → fiscal year 2014
├── 2015 PS SCC.xlsx                  → fiscal year 2015 (older revision)
├── 2015 PS SCC NEW.xlsx              → fiscal year 2015 (overrides the older one)
├── 2016 PS SCC - 4.22.16.xlsx        → fiscal year 2016 (older revision)
├── 2016 PS SCC 7.27.16.xlsx          → fiscal year 2016 (latest)
└── Profit_Summary_Template.xlsx      → SKIPPED (template)
```

When more than one file maps to the same year, the parser processes them in modification-time order and the newest one wins on overlapping job numbers.

## Verify it's working

- Open the dashboard in a browser, leave it on a fiscal year you've recently edited.
- Open one of your job-cost Excel files, change a value, **save**.
- Within ~15 seconds, refresh the dashboard tab — the new numbers should appear.

Logs are at `C:\ProgramData\SCCAgent\logs\`.

## What it sends

The agent uploads only the Excel files in the folder you specified. Every upload is signed with the API key's secret (HMAC-SHA256) and transported over TLS 1.3. The server stores every version uploaded.

## Rotate the API key

If the key is ever exposed, your admin clicks **Revoke** in the dashboard and issues a new one. Re-run the installer with the new key:

```powershell
.\install.ps1 -ApiKey "scc_live_new.xxx" -WatchFolder "C:\SCC\Reports"
```

The old key stops working immediately.

## Uninstall

```powershell
.\uninstall.ps1               # leaves config + creds behind
.\uninstall.ps1 -Purge        # also wipes %PROGRAMDATA%\SCCAgent
```

## Troubleshooting

| Symptom | What to check |
|---|---|
| Service won't start | Check `C:\ProgramData\SCCAgent\logs\stderr.log` |
| Files aren't uploading | Confirm the `watch_folder` in `C:\ProgramData\SCCAgent\config.toml` matches your actual Excel folder |
| `401 invalid_key` in logs | API key was revoked or mistyped; ask your admin to issue a new one |
| Dashboard says "no data for year" | A snapshot uploaded but the parser couldn't recognize the sheet layout — open the **Admin → Snapshots** page and look for the error message |

Email `help@complete3tech.com` if you're stuck.
