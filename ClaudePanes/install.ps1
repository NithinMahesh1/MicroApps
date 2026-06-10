<#
.SYNOPSIS
    Installs ClaudePanes to a user-local PATH directory.
.DESCRIPTION
    Copies claude_panes.py to a user-writable bin directory and creates a
    claude-panes.cmd wrapper so the tool can be invoked as `claude-panes`.
    Also creates the layouts config directory at ~/.config/claude-panes/layouts/.

    The script is conservative: it does NOT modify the PATH environment
    variable. If the install directory is not already on PATH, the script
    prints a copy-pasteable command for the user to run themselves.
.PARAMETER InstallPath
    Override the default install location ($env:USERPROFILE\.local\bin).
.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -InstallPath "C:\Tools\bin"
#>

[CmdletBinding()]
param(
    [string]$InstallPath = (Join-Path $env:USERPROFILE ".local\bin")
)

# --- 1. Python 3.11+ check ----------------------------------------------------

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Error "python was not found on PATH. Install Python 3.11+ from https://www.python.org/ and try again."
    exit 1
}

# `python --version` prints to stdout on modern Pythons and to stderr on older
# ones. Merge both streams so we can parse either case.
$versionOutput = & python --version 2>&1
$versionString = "$versionOutput"
$match = [regex]::Match($versionString, 'Python\s+(\d+)\.(\d+)\.(\d+)')
if (-not $match.Success) {
    Write-Error "Could not parse Python version from output: '$versionString'"
    exit 1
}

$major = [int]$match.Groups[1].Value
$minor = [int]$match.Groups[2].Value
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    Write-Error "Python 3.11+ is required. Detected: $($match.Value)"
    exit 1
}

Write-Host "Found $($match.Value)"

# --- 2. Resolve source script -------------------------------------------------

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceScript = Join-Path $scriptDir "claude_panes.py"
if (-not (Test-Path -LiteralPath $sourceScript -PathType Leaf)) {
    Write-Error "Could not find claude_panes.py next to install.ps1 (expected: $sourceScript)"
    exit 1
}

# --- 3. Ensure install directory exists ---------------------------------------

if (-not (Test-Path -LiteralPath $InstallPath -PathType Container)) {
    Write-Host "Creating install directory: $InstallPath"
    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
}

# --- 4. Copy script + create .cmd wrapper -------------------------------------

$targetScript = Join-Path $InstallPath "claude_panes.py"
$targetWrapper = Join-Path $InstallPath "claude-panes.cmd"

Copy-Item -LiteralPath $sourceScript -Destination $targetScript -Force
Write-Host "Installed: $targetScript"

# The wrapper invokes python against the sibling .py file. %~dp0 is the
# directory of the .cmd file (with trailing backslash) so the wrapper works
# regardless of the caller's current directory.
$wrapperContent = @'
@echo off
python "%~dp0claude_panes.py" %*
'@
Set-Content -LiteralPath $targetWrapper -Value $wrapperContent -Encoding ASCII
Write-Host "Installed: $targetWrapper"

# --- 5. PATH advisory (never mutate) ------------------------------------------

$pathEntries = $env:Path -split ';' | Where-Object { $_ -ne '' }
$normalizedInstall = (Resolve-Path -LiteralPath $InstallPath).Path.TrimEnd('\')
$onPath = $pathEntries | Where-Object { $_.TrimEnd('\') -ieq $normalizedInstall }

if (-not $onPath) {
    Write-Host ""
    Write-Host "NOTE: $InstallPath is not on your PATH."
    Write-Host "To add it to the user PATH (persistent), run this in PowerShell:"
    Write-Host ""
    Write-Host "    [Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';$InstallPath', 'User')"
    Write-Host ""
    Write-Host "Then open a new terminal so the change takes effect."
}

# --- 6. Layouts config directory ----------------------------------------------

$layoutsDir = Join-Path $env:USERPROFILE ".config\claude-panes\layouts"
if (-not (Test-Path -LiteralPath $layoutsDir -PathType Container)) {
    New-Item -ItemType Directory -Path $layoutsDir -Force | Out-Null
    Write-Host "Created layouts directory: $layoutsDir"
} else {
    Write-Host "Layouts directory already exists: $layoutsDir"
}

# --- 7. Success summary -------------------------------------------------------

Write-Host ""
Write-Host "ClaudePanes installed successfully."
Write-Host "  Script:   $targetScript"
Write-Host "  Wrapper:  $targetWrapper"
Write-Host "  Layouts:  $layoutsDir"
Write-Host ""
Write-Host "Smoke test (after PATH is set):"
Write-Host "    claude-panes --help"
