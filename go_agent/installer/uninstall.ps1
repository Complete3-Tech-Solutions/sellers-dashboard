<#
.SYNOPSIS
  Remove the SCCAgent service and all of its data.

.DESCRIPTION
  Runs `scc-agent.exe uninstall`, which stops + removes the service, deletes the
  shortcuts, drops the Apps & features entry, and purges %PROGRAMDATA%\SCCAgent.
  (You can also uninstall from Settings > Apps.)
#>
[CmdletBinding()]
param(
  [string]$InstallDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

$exe = Join-Path $InstallDir "scc-agent.exe"
if (Test-Path $exe) {
  Start-Process -FilePath $exe -Wait -ArgumentList "uninstall"
} elseif (Get-Service -Name SCCAgent -ErrorAction SilentlyContinue) {
  Stop-Service SCCAgent -ErrorAction SilentlyContinue
  sc.exe delete SCCAgent | Out-Null
}

Write-Host "Uninstall complete."
