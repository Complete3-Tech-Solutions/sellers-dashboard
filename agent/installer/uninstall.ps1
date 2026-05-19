<#
.SYNOPSIS
  Remove the SCCAgent service and (optionally) delete its data files.
#>
[CmdletBinding()]
param(
  [string]$InstallDir = $PSScriptRoot,
  [switch]$Purge
)

$ErrorActionPreference = "Stop"

$nssm = Join-Path $InstallDir "nssm.exe"
if (-not (Test-Path $nssm)) {
  $nssm = (Get-Command nssm.exe -ErrorAction SilentlyContinue)?.Source
}

if ($nssm -and (Get-Service -Name SCCAgent -ErrorAction SilentlyContinue)) {
  & $nssm stop SCCAgent confirm
  & $nssm remove SCCAgent confirm
} elseif (Get-Service -Name SCCAgent -ErrorAction SilentlyContinue) {
  Stop-Service SCCAgent -ErrorAction SilentlyContinue
  sc.exe delete SCCAgent | Out-Null
}

if ($Purge) {
  $progData = Join-Path $env:PROGRAMDATA "SCCAgent"
  if (Test-Path $progData) { Remove-Item -Recurse -Force $progData }
  Write-Host "Removed $progData"
} else {
  Write-Host "Service removed. Config and credentials left in %PROGRAMDATA%\SCCAgent."
}
