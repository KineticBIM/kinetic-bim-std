<#
.SYNOPSIS
    Install (or uninstall) the Kinetic BIM Standard extension for pyRevit.

.DESCRIPTION
    Deploys the Kinetic.extension folder into a private extensions directory,
    registers that directory with pyRevit, and clears the pyRevit caches so the
    Kinetic ribbon tab appears on the next Revit launch.

    pyRevit must already be installed. Revit must be CLOSED while this runs --
    pyRevit locks its cache files while Revit is open.

.PARAMETER Source
    Path to the Kinetic.extension folder. Defaults to the copy sitting next to
    this script (the layout produced inside the distributed zip).

.PARAMETER Uninstall
    Remove the installed extension and unregister its directory from pyRevit.

.EXAMPLE
    .\install.ps1
        Install from the Kinetic.extension folder beside this script.

.EXAMPLE
    .\install.ps1 -Uninstall
        Remove a previous install.
#>
[CmdletBinding()]
param(
    [string]$Source,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$ExtensionName = 'Kinetic.extension'
$InstallRoot   = Join-Path $env:APPDATA 'KineticBIM\extensions'
$InstallPath   = Join-Path $InstallRoot $ExtensionName
$ConfigPath    = Join-Path $env:APPDATA 'pyRevit\pyRevit_config.ini'
$PyRevitUrl    = 'https://github.com/pyrevitlabs/pyRevit/releases'

function Write-Step ($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Write-Ok   ($msg) { Write-Host "  $msg" -ForegroundColor Green }

# --- pyRevit config helpers (fallback when the CLI is unavailable) --------
# pyRevit stores its registered search directories as a JSON string array on
# the `userextensions` key under the [core] section, e.g.
#     userextensions = ["C:\\Users\\me\\ext","D:\\more"]
# We hand-build the JSON (escaping backslashes) so this works on both Windows
# PowerShell 5.1 and PowerShell 7 without relying on -AsArray.

function Format-PathArray ($paths) {
    $items = foreach ($p in $paths) { '"' + ($p -replace '\\', '\\') + '"' }
    return '[' + ($items -join ',') + ']'
}

function Read-UserExtensions ($lines) {
    foreach ($line in $lines) {
        if ($line -match '^\s*userextensions\s*=\s*(.+)$') {
            try { return @($matches[1].Trim() | ConvertFrom-Json) }
            catch { return @() }
        }
    }
    return @()
}

function Set-UserExtensions ($paths) {
    if (-not (Test-Path $ConfigPath)) {
        throw "pyRevit config not found at $ConfigPath; cannot register the " +
              "extensions path without the pyRevit CLI."
    }
    $lines = @(Get-Content -LiteralPath $ConfigPath)
    $newLine = 'userextensions = ' + (Format-PathArray $paths)
    $idx = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*userextensions\s*=') { $idx = $i; break }
    }
    if ($idx -ge 0) {
        $lines[$idx] = $newLine
    } else {
        # no userextensions key yet: place it under [core], or append a section
        $core = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '^\s*\[core\]\s*$') { $core = $i; break }
        }
        if ($core -ge 0) {
            $lines = $lines[0..$core] + $newLine + $lines[($core + 1)..($lines.Count - 1)]
        } else {
            $lines += @('', '[core]', $newLine)
        }
    }
    Set-Content -LiteralPath $ConfigPath -Value $lines -Encoding UTF8
}

function Add-PathToConfig ($Path) {
    $paths = @(Read-UserExtensions (Get-Content -LiteralPath $ConfigPath))
    if ($paths -notcontains $Path) { $paths += $Path }
    Set-UserExtensions $paths
}

function Remove-PathFromConfig ($Path) {
    if (-not (Test-Path $ConfigPath)) { return }
    $paths = @(Read-UserExtensions (Get-Content -LiteralPath $ConfigPath))
    $kept = @($paths | Where-Object { $_ -ne $Path })
    Set-UserExtensions $kept
}

# --- preconditions --------------------------------------------------------

$cli = Get-Command pyrevit -ErrorAction SilentlyContinue
$hasConfig = Test-Path $ConfigPath
if (-not $cli -and -not $hasConfig) {
    throw "pyRevit was not detected on this machine. Install pyRevit first " +
          "from $PyRevitUrl, then re-run this installer."
}

$revit = Get-Process -Name 'Revit' -ErrorAction SilentlyContinue
if ($revit) {
    $verb = if ($Uninstall) { 'uninstalling' } else { 'installing' }
    throw "Revit is currently running. Close all Revit windows before " +
          "$verb (pyRevit locks its cache while Revit is open), then re-run."
}

Write-Host ""
Write-Host "Kinetic BIM Standard installer" -ForegroundColor White

# --- uninstall ------------------------------------------------------------

if ($Uninstall) {
    if ($cli) {
        Write-Step "Unregistering extensions path from pyRevit..."
        & pyrevit extensions paths forget "$InstallRoot" 2>&1 | Out-Null
    } else {
        Remove-PathFromConfig -Path $InstallRoot
    }
    if (Test-Path $InstallPath) {
        Write-Step "Removing $InstallPath ..."
        Remove-Item $InstallPath -Recurse -Force
    }
    if ($cli) {
        Write-Step "Clearing pyRevit caches..."
        & pyrevit caches clear --all 2>&1 | Out-Null
    }
    Write-Ok "Kinetic BIM Standard uninstalled. Restart Revit to apply."
    return
}

# --- resolve source -------------------------------------------------------

if (-not $Source) {
    $Source = Join-Path $PSScriptRoot $ExtensionName
}
if (-not (Test-Path (Join-Path $Source 'extension.json'))) {
    throw "Could not find $ExtensionName at '$Source'. Pass -Source <path> " +
          "pointing at the Kinetic.extension folder."
}

# --- deploy ---------------------------------------------------------------

Write-Step "Installing to $InstallPath ..."
if (Test-Path $InstallPath) {
    Remove-Item $InstallPath -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Item -Path $Source -Destination $InstallPath -Recurse -Force

# --- register with pyRevit ------------------------------------------------

if ($cli) {
    Write-Step "Registering extensions path with pyRevit..."
    & pyrevit extensions paths add "$InstallRoot" 2>&1 | Out-Null
    Write-Step "Clearing pyRevit caches..."
    & pyrevit caches clear --all 2>&1 | Out-Null
} else {
    Write-Step "Registering extensions path (editing pyRevit config)..."
    Add-PathToConfig -Path $InstallRoot
    Write-Warning ("pyRevit CLI not found; registered via config edit. " +
                   "The cache will rebuild automatically on next Revit launch.")
}

Write-Host ""
Write-Ok "Kinetic BIM Standard installed."
Write-Host "  Start Revit - the 'Kinetic' ribbon tab will appear." -ForegroundColor Green
Write-Host "  Activate your licence from the Kinetic tab: Help > Activate." -ForegroundColor Green
Write-Host ""
