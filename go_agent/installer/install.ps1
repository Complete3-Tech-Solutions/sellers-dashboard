<#
.SYNOPSIS
  Headless install of the SCC profitability agent (single exe).

.DESCRIPTION
  Most operators just double-click scc-agent.exe and use the GUI. This script is
  for scripted/silent installs: it runs `scc-agent.exe install ...`, which writes
  config under %PROGRAMDATA%\SCCAgent, stores the API key via DPAPI, and
  registers + starts the native "SCCAgent" service (auto-start, crash-restart).
  The exe is manifested requireAdministrator, so this triggers a UAC prompt.

.PARAMETER ApiKey
  Full API key, of the form scc_live_xxxxxxxxx.yyyyyyyyyyyyyyyyy.

.PARAMETER WatchFolder
  Absolute path to the folder that holds the customer's job-cost Excel files.

.PARAMETER ApiBaseUrl
  Base URL of the SCC SaaS backend. Defaults to the Railway deployment.

.PARAMETER InstallDir
  Where scc-agent.exe lives. Defaults to the directory containing this script.

.EXAMPLE
  .\install.ps1 -ApiKey "scc_live_aB3xK9....abcdef" -WatchFolder "C:\SCC\Reports"
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ApiKey,
  [Parameter(Mandatory=$true)][string]$WatchFolder,
  [string]$ApiBaseUrl = "https://sellers-dashboard-production.up.railway.app",
  [string]$InstallDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

$exe = Join-Path $InstallDir "scc-agent.exe"
if (-not (Test-Path $exe)) { throw "scc-agent.exe not found at $exe" }
if (-not (Test-Path $WatchFolder)) { throw "WatchFolder '$WatchFolder' does not exist." }

$p = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @(
  "install", "-key", $ApiKey, "-watch", $WatchFolder, "-url", $ApiBaseUrl
)
if ($p.ExitCode -ne 0) { throw "Install failed (exit $($p.ExitCode))" }

Write-Host "SCCAgent installed and started. Logs: $env:PROGRAMDATA\SCCAgent\logs"
