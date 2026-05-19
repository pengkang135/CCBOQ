# albedo-cfg one-click deployment script
# Usage: new machine full restore / existing environment incremental update
# Run: .\deploy.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HomeDir = $env:USERPROFILE
$ClaudeDir = "$HomeDir\.claude"
$OpenclawDir = "$HomeDir\.openclaw"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  albedo-cfg Full Environment Deploy" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ========== Phase 0: Environment Variables ==========
Write-Host "[0/7] Loading environment variables..." -ForegroundColor Yellow

$EnvFile = Join-Path $ScriptDir "env.ps1"
if (Test-Path $EnvFile) {
    Write-Host "  Loading from env.ps1..."
    . $EnvFile
    Write-Host "  Loaded." -ForegroundColor Green
} else {
    Write-Host "  env.ps1 not found, interactive collection:" -ForegroundColor Yellow
    Write-Host ""

    $ANTHROPIC_BASE_URL = Read-Host "API Base URL (default: https://api.deepseek.com/anthropic)"
    if ([string]::IsNullOrWhiteSpace($ANTHROPIC_BASE_URL)) { $ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic" }

    $ANTHROPIC_AUTH_TOKEN = Read-Host "API Auth Token (required)"
    while ([string]::IsNullOrWhiteSpace($ANTHROPIC_AUTH_TOKEN)) {
        $ANTHROPIC_AUTH_TOKEN = Read-Host "API Auth Token required, please re-enter"
    }

    $ANTHROPIC_MODEL = Read-Host "Default model (default: deepseek-v4-pro)"
    if ([string]::IsNullOrWhiteSpace($ANTHROPIC_MODEL)) { $ANTHROPIC_MODEL = "deepseek-v4-pro" }

    $DEFAULT_HAIKU_MODEL = Read-Host "Haiku model (default: deepseek-v4-flash)"
    if ([string]::IsNullOrWhiteSpace($DEFAULT_HAIKU_MODEL)) { $DEFAULT_HAIKU_MODEL = "deepseek-v4-flash" }

    $DEFAULT_SONNET_MODEL = Read-Host "Sonnet model (default: deepseek-v4-pro)"
    if ([string]::IsNullOrWhiteSpace($DEFAULT_SONNET_MODEL)) { $DEFAULT_SONNET_MODEL = "deepseek-v4-pro" }

    $DEFAULT_OPUS_MODEL = Read-Host "Opus model (default: deepseek-v4-pro)"
    if ([string]::IsNullOrWhiteSpace($DEFAULT_OPUS_MODEL)) { $DEFAULT_OPUS_MODEL = "deepseek-v4-pro" }

    $GITHUB_PERSONAL_ACCESS_TOKEN = Read-Host "GitHub PAT"

    $TELEGRAM_BOT_TOKEN = Read-Host "Telegram Bot Token (required)"
    while ([string]::IsNullOrWhiteSpace($TELEGRAM_BOT_TOKEN)) {
        $TELEGRAM_BOT_TOKEN = Read-Host "Telegram Bot Token required, please re-enter"
    }

    $TELEGRAM_OWNER_ID = Read-Host "Telegram Owner ID"

    $GIT_USER_NAME = Read-Host "Git user name (default: Kevin Peng)"
    if ([string]::IsNullOrWhiteSpace($GIT_USER_NAME)) { $GIT_USER_NAME = "Kevin Peng" }

    $GIT_USER_EMAIL = Read-Host "Git email"

    $save = Read-Host "Save as env.ps1? (y/n, default: y)"
    if ($save -ne "n") {
        $envContent = @"
`$ENV:ANTHROPIC_BASE_URL = "$ANTHROPIC_BASE_URL"
`$ENV:ANTHROPIC_AUTH_TOKEN = "$ANTHROPIC_AUTH_TOKEN"
`$ENV:ANTHROPIC_MODEL = "$ANTHROPIC_MODEL"
`$ENV:DEFAULT_HAIKU_MODEL = "$DEFAULT_HAIKU_MODEL"
`$ENV:DEFAULT_SONNET_MODEL = "$DEFAULT_SONNET_MODEL"
`$ENV:DEFAULT_OPUS_MODEL = "$DEFAULT_OPUS_MODEL"
`$ENV:GITHUB_PERSONAL_ACCESS_TOKEN = "$GITHUB_PERSONAL_ACCESS_TOKEN"
`$ENV:TELEGRAM_BOT_TOKEN = "$TELEGRAM_BOT_TOKEN"
`$ENV:TELEGRAM_OWNER_ID = "$TELEGRAM_OWNER_ID"
`$ENV:GIT_USER_NAME = "$GIT_USER_NAME"
`$ENV:GIT_USER_EMAIL = "$GIT_USER_EMAIL"
"@
        Set-Content -Path $EnvFile -Value $envContent
        Write-Host "  Saved to env.ps1 (gitignored)" -ForegroundColor Green
    }
}

# Auto-detect system paths
if (-not $HOME) { $HOME = $HomeDir }
if (-not $HOME_WIN) { $HOME_WIN = $HomeDir }
if (-not $PYTHONW_PATH) {
    $pythonPaths = @(
        "$HomeDir\AppData\Local\Programs\Python\Python313\pythonw.exe",
        "$HomeDir\AppData\Local\Programs\Python\Python312\pythonw.exe",
        "$HomeDir\AppData\Local\Programs\Python\Python311\pythonw.exe"
    )
    foreach ($p in $pythonPaths) {
        if (Test-Path $p) { $PYTHONW_PATH = $p; break }
    }
    if (-not $PYTHONW_PATH) {
        $found = Get-Command pythonw -ErrorAction SilentlyContinue
        if ($found) { $PYTHONW_PATH = $found.Source }
    }
}

# Auto-generate OpenClaw gateway token
if (-not $OPENCLAW_GATEWAY_TOKEN) {
    $OPENCLAW_GATEWAY_TOKEN = -join ((48..57) + (97..102) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
}

Write-Host ""

# ========== Helper: Template substitution ==========
function Expand-Template($content) {
    $result = $content
    $result = $result -replace '\{\{ANTHROPIC_BASE_URL\}\}', $ANTHROPIC_BASE_URL
    $result = $result -replace '\{\{ANTHROPIC_AUTH_TOKEN\}\}', $ANTHROPIC_AUTH_TOKEN
    $result = $result -replace '\{\{ANTHROPIC_MODEL\}\}', $ANTHROPIC_MODEL
    $result = $result -replace '\{\{ANTHROPIC_DEFAULT_HAIKU_MODEL\}\}', $DEFAULT_HAIKU_MODEL
    $result = $result -replace '\{\{ANTHROPIC_DEFAULT_SONNET_MODEL\}\}', $DEFAULT_SONNET_MODEL
    $result = $result -replace '\{\{ANTHROPIC_DEFAULT_OPUS_MODEL\}\}', $DEFAULT_OPUS_MODEL
    $result = $result -replace '\{\{GITHUB_PERSONAL_ACCESS_TOKEN\}\}', $GITHUB_PERSONAL_ACCESS_TOKEN
    $result = $result -replace '\{\{OPENCLAW_GATEWAY_TOKEN\}\}', $OPENCLAW_GATEWAY_TOKEN
    $result = $result -replace '\{\{TELEGRAM_BOT_TOKEN\}\}', $TELEGRAM_BOT_TOKEN
    $result = $result -replace '\{\{TELEGRAM_OWNER_ID\}\}', $TELEGRAM_OWNER_ID
    $result = $result -replace '\{\{HOME\}\}', $HOME
    $result = $result -replace '\{\{HOME_WIN\}\}', $HOME_WIN
    $result = $result -replace '\{\{PYTHONW_PATH\}\}', $PYTHONW_PATH
    return $result
}

# ========== Phase 1: Claude Code ==========
Write-Host "[1/7] Deploying Claude Code config..." -ForegroundColor Yellow

New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null

# settings.json
$template = Get-Content "$ScriptDir\claude\settings.json.template" -Raw
$expanded = Expand-Template $template
Set-Content -Path "$ClaudeDir\settings.json" -Value $expanded -NoNewline
Write-Host "  settings.json" -ForegroundColor Green

# Other config files
$claudeFiles = @(
    "settings.local.json",
    "CLAUDE.md",
    "keybindings.json",
    ".mcp.json",
    "hookify.warn-onedrive-delete.global.md"
)
foreach ($f in $claudeFiles) {
    $src = "$ScriptDir\claude\$f"
    if (Test-Path $src) {
        copy $src "$ClaudeDir\$f" -Force
        Write-Host "  $f" -ForegroundColor Green
    }
}

# skills
Write-Host "  Copying skills..."
New-Item -ItemType Directory -Force -Path "$ClaudeDir\skills" | Out-Null
$skillDirs = Get-ChildItem "$ScriptDir\claude\skills" -Directory
foreach ($skill in $skillDirs) {
    $dst = "$ClaudeDir\skills\$($skill.Name)"
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    Copy-Item $skill.FullName $dst -Recurse -Force
    Write-Host "    $($skill.Name)"
}
Write-Host "  Skills done." -ForegroundColor Green

# wx-cli symlink (requires prior install under ~/.agents/skills/)
if (-not (Test-Path "$ClaudeDir\skills\wx-cli")) {
    $wxTarget = "$HomeDir\.agents\skills\wx-cli"
    if (Test-Path $wxTarget) {
        New-Item -ItemType SymbolicLink -Path "$ClaudeDir\skills\wx-cli" -Target $wxTarget -Force | Out-Null
        Write-Host "  wx-cli symlink -> $wxTarget" -ForegroundColor Green
    } else {
        Write-Host "  wx-cli not installed, skipping" -ForegroundColor Yellow
    }
}

# plugins
Write-Host "  Copying plugin manifests..."
New-Item -ItemType Directory -Force -Path "$ClaudeDir\plugins" | Out-Null
copy "$ScriptDir\claude\plugins\installed_plugins.json" "$ClaudeDir\plugins\" -Force
copy "$ScriptDir\claude\plugins\known_marketplaces.json" "$ClaudeDir\plugins\" -Force -ErrorAction SilentlyContinue

# MCP servers
Write-Host "  Copying MCP servers..."
New-Item -ItemType Directory -Force -Path "$ClaudeDir\mcp-servers" | Out-Null
Copy-Item "$ScriptDir\claude\mcp-servers\*" "$ClaudeDir\mcp-servers\" -Recurse -Force
# Clean any accidentally copied venv/cache
Remove-Item "$ClaudeDir\mcp-servers\*\__pycache__" -Recurse -Force -ErrorAction SilentlyContinue

# scripts
Write-Host "  Copying scripts..."
New-Item -ItemType Directory -Force -Path "$ClaudeDir\scripts" | Out-Null
Copy-Item "$ScriptDir\claude\scripts\*" "$ClaudeDir\scripts\" -Force

# sounds
Write-Host "  Copying sounds..."
New-Item -ItemType Directory -Force -Path "$ClaudeDir\sounds" | Out-Null
Copy-Item "$ScriptDir\claude\sounds\*" "$ClaudeDir\sounds\" -Force

# knowledge
Write-Host "  Copying knowledge..."
New-Item -ItemType Directory -Force -Path "$ClaudeDir\knowledge" | Out-Null
Copy-Item "$ScriptDir\claude\knowledge\*" "$ClaudeDir\knowledge\" -Recurse -Force -ErrorAction SilentlyContinue

# business-cards
Write-Host "  Copying business-cards..."
New-Item -ItemType Directory -Force -Path "$ClaudeDir\business-cards" | Out-Null
Copy-Item "$ScriptDir\business-cards\*" "$ClaudeDir\business-cards\" -Recurse -Force -ErrorAction SilentlyContinue

# .claude.json merge
$claudeJsonPartial = "$ScriptDir\claude\.claude.json.partial"
if (Test-Path $claudeJsonPartial) {
    Write-Host "  Merging .claude.json..."
    $partial = Get-Content $claudeJsonPartial -Raw | ConvertFrom-Json
    $existing = @{}
    if (Test-Path "$HomeDir\.claude.json") {
        $existing = Get-Content "$HomeDir\.claude.json" -Raw | ConvertFrom-Json
    }
    foreach ($prop in $partial.PSObject.Properties) {
        $existing | Add-Member -NotePropertyName $prop.Name -NotePropertyValue $prop.Value -Force
    }
    $existing | ConvertTo-Json -Depth 10 | Set-Content "$HomeDir\.claude.json"
    Write-Host "  .claude.json merged" -ForegroundColor Green
}

# ========== Phase 2: OpenClaw ==========
Write-Host ""
Write-Host "[2/7] Deploying OpenClaw config..." -ForegroundColor Yellow

New-Item -ItemType Directory -Force -Path $OpenclawDir | Out-Null

# openclaw.json
$template = Get-Content "$ScriptDir\openclaw\openclaw.json.template" -Raw
$expanded = Expand-Template $template
Set-Content -Path "$OpenclawDir\openclaw.json" -Value $expanded -NoNewline
Write-Host "  openclaw.json" -ForegroundColor Green

# librarian-mcp.json
copy "$ScriptDir\openclaw\librarian-mcp.json" "$OpenclawDir\" -Force
Write-Host "  librarian-mcp.json" -ForegroundColor Green

# workspace
Write-Host "  Copying workspace..."
New-Item -ItemType Directory -Force -Path "$OpenclawDir\workspace" | Out-Null
Copy-Item "$ScriptDir\openclaw\workspace\*" "$OpenclawDir\workspace\" -Recurse -Force
Remove-Item "$OpenclawDir\workspace\__pycache__" -Recurse -Force -ErrorAction SilentlyContinue

# cron
copy "$ScriptDir\openclaw\cron\jobs.json" "$OpenclawDir\cron\" -Force -ErrorAction SilentlyContinue
Write-Host "  cron/jobs.json" -ForegroundColor Green

# plugins
New-Item -ItemType Directory -Force -Path "$OpenclawDir\plugins" | Out-Null
copy "$ScriptDir\openclaw\plugins\installs.json" "$OpenclawDir\plugins\" -Force -ErrorAction SilentlyContinue

# plugin-skills
New-Item -ItemType Directory -Force -Path "$OpenclawDir\plugin-skills" | Out-Null
Copy-Item "$ScriptDir\openclaw\plugin-skills\*" "$OpenclawDir\plugin-skills\" -Recurse -Force -ErrorAction SilentlyContinue

# skill-workshop
New-Item -ItemType Directory -Force -Path "$OpenclawDir\skill-workshop" | Out-Null
Copy-Item "$ScriptDir\openclaw\skill-workshop\*" "$OpenclawDir\skill-workshop\" -Recurse -Force -ErrorAction SilentlyContinue

# scripts (template-expand .ps1 files that contain {{VAR}})
Write-Host "  Copying OpenClaw scripts..."
New-Item -ItemType Directory -Force -Path "$OpenclawDir" | Out-Null
Get-ChildItem "$ScriptDir\openclaw\scripts\*" | ForEach-Object {
    $dest = "$OpenclawDir\$($_.Name)"
    if ($_.Extension -eq ".ps1") {
        $content = Get-Content $_.FullName -Raw
        if ($content -match '\{\{') {
            $content = Expand-Template $content
        }
        Set-Content -Path $dest -Value $content -NoNewline
    } else {
        Copy-Item $_.FullName $dest -Force
    }
}

# completions
New-Item -ItemType Directory -Force -Path "$OpenclawDir\completions" | Out-Null
Copy-Item "$ScriptDir\openclaw\completions\*" "$OpenclawDir\completions\" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "  OpenClaw done." -ForegroundColor Green

# ========== Phase 3: Home dotfiles ==========
Write-Host ""
Write-Host "[3/7] Deploying home dotfiles..." -ForegroundColor Yellow

$mcpTemplate = Get-Content "$ScriptDir\home\.mcp.json" -Raw
$expanded = Expand-Template $mcpTemplate
Set-Content -Path "$HomeDir\.mcp.json" -Value $expanded -NoNewline
Write-Host "  .mcp.json" -ForegroundColor Green

$gitconfigTemplate = Get-Content "$ScriptDir\home\.gitconfig" -Raw
$gitconfigTemplate = $gitconfigTemplate -replace 'name = .*', "name = $GIT_USER_NAME"
$gitconfigTemplate = $gitconfigTemplate -replace 'email = .*', "email = $GIT_USER_EMAIL"
Set-Content -Path "$HomeDir\.gitconfig" -Value $gitconfigTemplate -NoNewline
Write-Host "  .gitconfig" -ForegroundColor Green

# ========== Phase 4: Main CLAUDE.md ==========
Write-Host ""
Write-Host "[4/7] Deploying CLAUDE.md..." -ForegroundColor Yellow

if (Test-Path "$ScriptDir\README.md") {
    copy "$ScriptDir\README.md" "$HomeDir\CLAUDE.md" -Force
    Write-Host "  CLAUDE.md (from README.md)" -ForegroundColor Green
}

# ========== Phase 5: Python venvs ==========
Write-Host ""
Write-Host "[5/7] Rebuilding Python venvs..." -ForegroundColor Yellow

$pythonExe = $PYTHONW_PATH -replace 'pythonw\.exe$', 'python.exe'
if (-not (Test-Path $pythonExe)) { $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source }

if ($pythonExe) {
    $venvDirs = @(
        @{ Path = "$ClaudeDir\mcp-servers\librarian"; Req = "$ClaudeDir\mcp-servers\librarian\requirements.txt" },
        @{ Path = "$ClaudeDir\mcp-servers\rapid-ocr"; Req = "$ClaudeDir\mcp-servers\rapid-ocr\requirements.txt" },
        @{ Path = "$ClaudeDir\scripts\pdf2md"; Req = "$ClaudeDir\mcp-servers\pdf2md\requirements.txt" }
    )
    foreach ($v in $venvDirs) {
        if (Test-Path $v.Req) {
            Write-Host "  Creating venv: $($v.Path)"
            $venvPath = "$($v.Path)\.venv"
            if (-not (Test-Path $venvPath)) {
                & $pythonExe -m venv $venvPath
            }
            $pipExe = "$venvPath\Scripts\pip.exe"
            if (Test-Path $pipExe) {
                & $pipExe install -r $v.Req --quiet
                Write-Host "    $($v.Path) done." -ForegroundColor Green
            }
        }
    }
} else {
    Write-Host "  Python not detected, skipping venv rebuild" -ForegroundColor Yellow
}

# ========== Phase 6: Windows Scheduled Tasks ==========
Write-Host ""
Write-Host "[6/7] Registering Windows scheduled tasks..." -ForegroundColor Yellow

$installGatewayTask = "$OpenclawDir\install-gateway-task.ps1"
if (Test-Path $installGatewayTask) {
    Write-Host "  Gateway task..."
    & powershell -File $installGatewayTask
}

Write-Host ""

# ========== Phase 7: Validation ==========
Write-Host "[7/7] Validating..." -ForegroundColor Yellow

$errors = @()
if (-not (Test-Path "$ClaudeDir\settings.json")) { $errors += "settings.json missing" }
if (-not (Test-Path "$ClaudeDir\CLAUDE.md")) { $errors += "CLAUDE.md missing" }
if (-not (Test-Path "$OpenclawDir\openclaw.json")) { $errors += "openclaw.json missing" }
if (-not (Test-Path "$HomeDir\.mcp.json")) { $errors += ".mcp.json missing" }

$skillCount = (Get-ChildItem "$ClaudeDir\skills" -Directory).Count
Write-Host "  Skills: $skillCount/16" -ForegroundColor $(if ($skillCount -ge 15) { "Green" } else { "Yellow" })

if ($errors.Count -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Deploy complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Deployed:" -ForegroundColor White
    Write-Host "  Claude Code:  $ClaudeDir"
    Write-Host "  OpenClaw:     $OpenclawDir"
    Write-Host "  MCP config:   $HomeDir\.mcp.json"
    Write-Host "  Git config:   $HomeDir\.gitconfig"
} else {
    Write-Host ""
    Write-Host "Validation found $($errors.Count) issue(s):" -ForegroundColor Red
    foreach ($e in $errors) { Write-Host "  - $e" -ForegroundColor Red }
}
