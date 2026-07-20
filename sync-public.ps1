# sync-public.ps1 — Extract public subset from albedo-cfg and push to CCBOQ
# Usage: .\sync-public.ps1 [-CheckOnly]

param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestFile = Join-Path $ScriptDir "public-manifest.txt"
$TempDir = "$env:TEMP\albedo-public-sync"
$PublicRemote = "git@github.com:pengkang135/CCBOQ.git"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  albedo-cfg -> CCBOQ Public Sync" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Read manifest
if (-not (Test-Path $ManifestFile)) {
    Write-Host "Error: public-manifest.txt not found" -ForegroundColor Red
    exit 1
}
$lines = Get-Content $ManifestFile | Where-Object { $_ -notmatch '^\s*#' -and $_ -notmatch '^\s*$' }
$manifest = @()
foreach ($line in $lines) {
    $trimmed = $line.Trim()
    if ($trimmed) { $manifest += $trimmed }
}
Write-Host "Manifest: $($manifest.Count) entries" -ForegroundColor White

# Secret scanning function
function Test-Secrets($content) {
    $suspicious = @()
    if ($content -match 'sk-[a-zA-Z0-9]{20,}') { $suspicious += "Suspected API key: sk-*" }
    if ($content -match 'ghp_[a-zA-Z0-9]{20,}') { $suspicious += "Suspected GitHub PAT: ghp_*" }
    if ($content -match '[0-9]{8,10}:[a-zA-Z0-9_-]{30,}') { $suspicious += "Suspected Telegram Bot Token" }
    if ($content -match '-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----') { $suspicious += "Suspected private key" }
    return $suspicious
}

# Prepare temp directory
if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force
}

Write-Host ""
Write-Host "Cloning CCBOQ..." -ForegroundColor Yellow
git clone $PublicRemote $TempDir 2>&1 | Out-Null

# Clear worktree
Get-ChildItem $TempDir -Exclude ".git" | Remove-Item -Recurse -Force

# Copy files per manifest
Write-Host "Copying files per manifest..." -ForegroundColor Yellow
$allSecrets = @()
foreach ($entry in $manifest) {
    $src = Join-Path $ScriptDir $entry
    if ($entry.EndsWith("/*")) {
        $dirPath = $entry.Substring(0, $entry.Length - 2)
        $srcDir = Join-Path $ScriptDir $dirPath
        if (Test-Path $srcDir) {
            $dstDir = Join-Path $TempDir $dirPath
            New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
            Copy-Item "$srcDir\*" $dstDir -Recurse -Force
            Write-Host "  $entry" -ForegroundColor Green
        } else {
            Write-Host "  $entry (source not found, skipping)" -ForegroundColor Yellow
        }
    } else {
        if (Test-Path $src) {
            $dst = Join-Path $TempDir $entry
            $dstParent = Split-Path $dst -Parent
            New-Item -ItemType Directory -Force -Path $dstParent | Out-Null
            Copy-Item $src $dst -Force
            Write-Host "  $entry" -ForegroundColor Green
        } else {
            Write-Host "  $entry (source not found, skipping)" -ForegroundColor Yellow
        }
    }
}

# Security scan
Write-Host ""
Write-Host "Security scan..." -ForegroundColor Yellow
$scanFiles = Get-ChildItem $TempDir -Recurse -File -Exclude ".git" | Where-Object {
    $_.Extension -in ".json", ".ps1", ".sh", ".md", ".txt", ".py", ".template", ".yml", ".yaml"
}
foreach ($f in $scanFiles) {
    $content = Get-Content $f.FullName -Raw -ErrorAction SilentlyContinue
    if ($content) {
        $found = Test-Secrets $content
        foreach ($s in $found) {
            $msg = "$($f.FullName): $s"
            $allSecrets += $msg
            Write-Host "  Warning: $msg" -ForegroundColor Red
        }
    }
}

if ($allSecrets.Count -gt 0) {
    Write-Host ""
    if (-not $CheckOnly) {
        $confirm = Read-Host "Found $($allSecrets.Count) suspected secrets, continue anyway? (y/N)"
        if ($confirm -ne "y") {
            Write-Host "Cancelled." -ForegroundColor Yellow
            exit 1
        }
    } else {
        Write-Host "Check-only mode, found $($allSecrets.Count) issue(s)." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "  No secrets found." -ForegroundColor Green
}

if ($CheckOnly) {
    Write-Host "Check-only mode complete, no issues found." -ForegroundColor Green
    exit 0
}

# Commit and push
Write-Host ""
Write-Host "Committing and pushing..." -ForegroundColor Yellow
Push-Location $TempDir
try {
    git add -A 2>&1 | Out-Null
    $commitMsg = "sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm') from albedo-cfg"
    git commit -m $commitMsg --allow-empty 2>&1 | Out-Null
    git push origin main --force 2>&1 | Out-Null
    Write-Host "Pushed to CCBOQ." -ForegroundColor Green
} finally {
    Pop-Location
}

# Cleanup
Remove-Item $TempDir -Recurse -Force
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sync complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
