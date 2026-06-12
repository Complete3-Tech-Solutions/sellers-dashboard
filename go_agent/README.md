# SCC Agent (Go)

A Go port of the Python `agent/`. Watches a folder of job-cost Excel files and
uploads changes to the SCC Profitability SaaS, signing every request with HMAC.
Ships as a **single static binary** that is its own **native Windows service**
(no PyInstaller, no NSSM).

## Why Go

- One self-contained `scc-agent.exe` — no embedded Python runtime, far fewer
  antivirus false positives than a PyInstaller bundle.
- Native Windows service via `golang.org/x/sys/windows/svc` — NSSM is gone.
- Pure-Go SQLite (`modernc.org/sqlite`) — no CGo, so it cross-compiles cleanly.
- Cross-compile the Windows binary from macOS/Linux: `make windows`.

## Layout

```
cmd/scc-agent/        single exe: settings GUI + CLI + service (manifest.xml elevates)
internal/version/     build version
internal/config/      config.toml + %PROGRAMDATA%\SCCAgent paths
internal/creds/       API key storage — DPAPI (Windows) / dev XOR (other)
internal/state/       SQLite record of uploaded files (modernc, pure Go)
internal/uploader/    HMAC signing, multipart upload, retry/backoff, heartbeat
internal/watcher/     fsnotify + poll, debounced
internal/sync/        disk-vs-state diff → snapshot
internal/app/         wiring + heartbeat loop (the run loop)
internal/service/     native Windows service host + install/uninstall
internal/arp/         Add/Remove Programs (Apps & features) registration
installer/            install.ps1 / uninstall.ps1 (thin wrappers over the exe)
```

Everything ships as **one `scc-agent.exe`**: double-click → settings GUI; the
SCM runs it as the service; `uninstall` does headless removal.

This mirrors the Python module names 1:1 (`config`, `creds`, `state`,
`uploader`, `watcher`, `sync`) so the two are easy to diff.

## Build

```bash
make tidy     # resolve go.mod (needs network once)
make test     # unit tests (signing parity, uuid format)
make build    # host binary -> dist/scc-agent
make windows  # dist/scc-agent.exe (the single shipping binary)
```

`make windows` runs `goversioninfo` to embed `cmd/scc-agent/manifest.xml` (UAC
`requireAdministrator` + common controls) and builds as a GUI-subsystem app, so
double-clicking shows the settings window with no console flash. Drop an
`icon.ico` at `cmd/scc-agent/icon.ico` to brand the exe + shortcuts.

## CLI

```
scc-agent                              # no args: open the settings GUI (Windows)
scc-agent run                          # watch + upload (used by the service / foreground)
scc-agent install -key <k> -watch <folder> [-url <api>]   # headless install (Windows)
scc-agent uninstall                    # full removal (service, shortcuts, ARP, data)
scc-agent store-key <scc_live_x.y>     # persist a key via DPAPI
scc-agent version
```

The legacy `--store-key <key>` flag (used by the old installer) is still
accepted. Config lives at `%PROGRAMDATA%\SCCAgent\config.toml`; logs rotate at
`%PROGRAMDATA%\SCCAgent\logs\agent.log` (5 MB × 5).

## Install on the customer PC

Ship the **single `scc-agent.exe`**. The operator double-clicks it — Windows
shows the UAC prompt (manifested `requireAdministrator`), then a small window:

```
API Key:       [ scc_live_xxxx.yyyy            ]
Watch Folder:  [ C:\SCC\Reports      ] [Browse…]
API Base URL:  [ https://sellers-dashboard-production.up.railway.app ]
                                       [ Install ]
```

On **Install** it writes `config.toml`, stores the key via DPAPI, registers +
starts the `SCCAgent` service (auto-start on boot, auto-restart on crash), and
drops **"SCC Agent Settings"** shortcuts in the Start Menu and on the Desktop.
Because it runs elevated, any local folder can be chosen.

### Reboot & restart behaviour

- **System reboot** → the service is `Automatic (Delayed Start)`, so Windows
  starts it on boot. It reads the saved `config.toml`, so the same folder/URL/key
  are used — no re-setup.
- **Crash** → recovery actions restart it (5s, 5s, then 30s).
- **Re-open the app** → it pre-loads the saved settings.

### Changing settings later

Open the **SCC Agent Settings** icon (Start Menu / Desktop) — it's the same exe
with no args. It pre-loads the current folder and URL; the button becomes
**Save & Restart**. Change the folder (or paste a rotated key — leave the key
blank to keep the current one) and save; it rewrites the config and restarts the
service so the change takes effect.

The CLI still works for scripted/headless installs:

```powershell
scc-agent.exe install -key "scc_live_x.y" -watch "C:\SCC\Reports"
```

The server still never pushes to the agent — a rotated key reaches the machine
only by re-entering it in the settings UI (or `store-key`).

### Uninstalling

The installer registers an **Apps & features** entry ("SCC Profitability
Agent"), so it uninstalls the native Windows way: **Settings → Apps → SCC
Profitability Agent → Uninstall**. That runs `scc-agent.exe uninstall`
(elevated), which stops + removes the service, deletes the shortcuts, drops the
Apps & features entry, and purges `%PROGRAMDATA%\SCCAgent`.

Equivalent from the command line / scripts:

```powershell
scc-agent.exe uninstall    # full removal (service, shortcuts, ARP, data)
.\uninstall.ps1            # wrapper around the above
```

## Parity notes

- Signature is over `METHOD\nPATH\nTS\nNONCE\nSHA256(body)`, identical to
  `scc_agent/uploader.py`; covered by `uploader_test.go`.
- Heartbeat (`POST /api/snapshot/heartbeat`) → `{"sync": true}` triggers a
  forced full re-upload, matching agent `0.2.0`.
- DPAPI uses `CRYPTPROTECT_LOCAL_MACHINE` (0x4), same scope as the Python agent,
  so the SYSTEM service account can read a key written at install time.
- Template / Excel-temp files (`~$*`, `*.tmp`, `*template*`) are skipped, same
  as the Python watcher.
```
