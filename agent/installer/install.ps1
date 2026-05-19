<#
.SYNOPSIS
  Install the SCC profitability agent as a Windows service.

.DESCRIPTION
  Writes config.toml under %PROGRAMDATA%\SCCAgent, persists the API key via
  DPAPI (LocalMachine scope), and registers a service named "SCCAgent" via NSSM.

.PARAMETER ApiKey
  Full API key, of the form scc_live_xxxxxxxxx.yyyyyyyyyyyyyyyyy.

.PARAMETER WatchFolder
  Absolute path to the folder that holds the customer's job-cost Excel files.

.PARAMETER ApiBaseUrl
  Base URL of the SCC SaaS backend. Defaults to https://api.scc-saas.com.

.PARAMETER InstallDir
  Where the agent .exe lives. Defaults to the directory containing this script.

.EXAMPLE
  .\install.ps1 -ApiKey "scc_live_aB3xK9....abcdef" -WatchFolder "C:\SCC\Reports"
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ApiKey,
  [Parameter(Mandatory=$true)][string]$WatchFolder,
  [string]$ApiBaseUrl = "https://api.scc-saas.com",
  [string]$InstallDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $WatchFolder)) {
  throw "WatchFolder '$WatchFolder' does not exist."
}

$progData = Join-Path $env:PROGRAMDATA "SCCAgent"
$logsDir  = Join-Path $progData "logs"
New-Item -ItemType Directory -Force -Path $progData | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir  | Out-Null

$configPath = Join-Path $progData "config.toml"
$watchEsc   = $WatchFolder.Replace('\','\\')

@"
api_base_url  = "$ApiBaseUrl"
watch_folder  = "$watchEsc"
debounce_secs = 8
poll_interval = 30
log_level     = "INFO"
"@ | Set-Content -Encoding utf8 $configPath

$agentExe = Join-Path $InstallDir "scc-agent.exe"
if (-not (Test-Path $agentExe)) { throw "scc-agent.exe not found at $agentExe" }

# Persist the API key under the SYSTEM account (DPAPI LocalMachine scope).
& $agentExe --store-key $ApiKey
if ($LASTEXITCODE -ne 0) { throw "Failed to store API key" }

# Locate or auto-discover nssm.exe (bundled next to install.ps1).
$nssm = Join-Path $InstallDir "nssm.exe"
if (-not (Test-Path $nssm)) {
  $nssm = (Get-Command nssm.exe -ErrorAction SilentlyContinue)?.Source
}
if (-not $nssm) { throw "nssm.exe not found. Place nssm.exe next to install.ps1." }

# Remove existing service if present, then (re)install.
if (Get-Service -Name SCCAgent -ErrorAction SilentlyContinue) {
  & $nssm stop SCCAgent confirm
  & $nssm remove SCCAgent confirm
}

& $nssm install SCCAgent $agentExe run
& $nssm set SCCAgent AppDirectory $InstallDir
& $nssm set SCCAgent Start SERVICE_AUTO_START
& $nssm set SCCAgent AppStdout (Join-Path $logsDir "stdout.log")
& $nssm set SCCAgent AppStderr (Join-Path $logsDir "stderr.log")
& $nssm set SCCAgent AppRotateFiles 1
& $nssm set SCCAgent AppRotateBytes 5242880
& $nssm set SCCAgent AppExit Default Restart
& $nssm set SCCAgent AppRestartDelay 5000
& $nssm set SCCAgent Description "Uploads SCC job-cost Excel changes to the SCC Profitability SaaS"

Start-Service SCCAgent
Write-Host "SCCAgent installed and started. Logs: $logsDir"
