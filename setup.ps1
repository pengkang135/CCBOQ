# Claude Code 配置一键安装脚本 (Windows PowerShell)
# 使用方法: .\setup.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Claude Code 工程配置安装" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeDir = "$env:USERPROFILE\.claude"
$ClaudeJson = "$env:USERPROFILE\.claude.json"

# ========== 1. 收集用户配置 ==========
Write-Host "[1/5] 配置 API 密钥和模型..." -ForegroundColor Yellow

$ANTHROPIC_BASE_URL = Read-Host "API Base URL (默认: https://api.anthropic.com)"
if ([string]::IsNullOrWhiteSpace($ANTHROPIC_BASE_URL)) {
    $ANTHROPIC_BASE_URL = "https://api.anthropic.com"
}

$ANTHROPIC_AUTH_TOKEN = Read-Host "API Auth Token (必填)"
if ([string]::IsNullOrWhiteSpace($ANTHROPIC_AUTH_TOKEN)) {
    Write-Host "错误: API Auth Token 不能为空!" -ForegroundColor Red
    exit 1
}

$ANTHROPIC_MODEL = Read-Host "默认模型 (默认: claude-sonnet-4-6)"
if ([string]::IsNullOrWhiteSpace($ANTHROPIC_MODEL)) {
    $ANTHROPIC_MODEL = "claude-sonnet-4-6"
}

Write-Host "  Haiku 模型 (默认: claude-haiku-4-5-20251001)"
$HAIKU_MODEL = Read-Host ""
if ([string]::IsNullOrWhiteSpace($HAIKU_MODEL)) {
    $HAIKU_MODEL = "claude-haiku-4-5-20251001"
}

Write-Host "  Sonnet 模型 (默认: claude-sonnet-4-6)"
$SONNET_MODEL = Read-Host ""
if ([string]::IsNullOrWhiteSpace($SONNET_MODEL)) {
    $SONNET_MODEL = "claude-sonnet-4-6"
}

Write-Host "  Opus 模型 (默认: claude-opus-4-7)"
$OPUS_MODEL = Read-Host ""
if ([string]::IsNullOrWhiteSpace($OPUS_MODEL)) {
    $OPUS_MODEL = "claude-opus-4-7"
}

$LANGUAGE = Read-Host "界面语言 (默认: chinese)"
if ([string]::IsNullOrWhiteSpace($LANGUAGE)) {
    $LANGUAGE = "chinese"
}

$THEME = Read-Host "主题 light/dark (默认: dark)"
if ([string]::IsNullOrWhiteSpace($THEME)) {
    $THEME = "dark"
}

# ========== 2. 创建目录 ==========
Write-Host ""
Write-Host "[2/5] 创建配置目录..." -ForegroundColor Yellow
if (-not (Test-Path $ClaudeDir)) {
    New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
    Write-Host "  已创建: $ClaudeDir"
} else {
    Write-Host "  目录已存在: $ClaudeDir"
}

# ========== 3. 安装 settings.json ==========
Write-Host ""
Write-Host "[3/5] 安装 settings.json..." -ForegroundColor Yellow

$stopHookCmd = if ($IsWindows) {
    'powershell -c \"[System.Media.SystemSounds]::Hand.Play()\"'
} else {
    'echo "Claude Code 已停止"'
}

$settingsContent = Get-Content "$ScriptDir\settings.json.template" -Raw
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_BASE_URL}}', $ANTHROPIC_BASE_URL)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_AUTH_TOKEN}}', $ANTHROPIC_AUTH_TOKEN)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_MODEL}}', $ANTHROPIC_MODEL)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_DEFAULT_HAIKU_MODEL}}', $HAIKU_MODEL)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_DEFAULT_SONNET_MODEL}}', $SONNET_MODEL)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_DEFAULT_OPUS_MODEL}}', $OPUS_MODEL)
$settingsContent = $settingsContent.Replace('{{LANGUAGE}}', $LANGUAGE)
$settingsContent = $settingsContent.Replace('{{THEME}}', $THEME)
$settingsContent = $settingsContent.Replace('{{EFFORT_LEVEL}}', 'high')
$settingsContent = $settingsContent.Replace('{{STOP_HOOK_COMMAND}}', $stopHookCmd)

$settingsPath = "$ClaudeDir\settings.json"
if (Test-Path $settingsPath) {
    $backup = "$settingsPath.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Copy-Item $settingsPath $backup
    Write-Host "  已备份原有配置: $backup"
}
Set-Content -Path $settingsPath -Value $settingsContent -Encoding UTF8
Write-Host "  已安装: $settingsPath"

# ========== 4. 安装 .mcp.json ==========
Write-Host ""
Write-Host "[4/5] 安装 MCP 服务器配置..." -ForegroundColor Yellow

$homePath = $env:USERPROFILE -replace '\\', '\\'
$mcpContent = Get-Content "$ScriptDir\.mcp.json" -Raw
$mcpContent = $mcpContent.Replace('{{HOME}}', $homePath)

$mcpPath = "$ClaudeDir\.mcp.json"
if (Test-Path $mcpPath) {
    $backup = "$mcpPath.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Copy-Item $mcpPath $backup
    Write-Host "  已备份原有配置: $backup"
}
Set-Content -Path $mcpPath -Value $mcpContent -Encoding UTF8
Write-Host "  已安装: $mcpPath"

# ========== 5. 更新 .claude.json ==========
Write-Host ""
Write-Host "[5/5] 更新 .claude.json 项目配置..." -ForegroundColor Yellow

if (Test-Path $ClaudeJson) {
    $backup = "$ClaudeJson.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Copy-Item $ClaudeJson $backup
    Write-Host "  已备份原有配置: $backup"

    $claudeConfig = Get-Content $ClaudeJson -Raw -Encoding UTF8 | ConvertFrom-Json

    $homeKey = $env:USERPROFILE
    if (-not $claudeConfig.projects) {
        $claudeConfig.projects = @{}
    }
    if (-not $claudeConfig.projects.$homeKey) {
        $claudeConfig.projects | Add-Member -MemberType NoteProperty -Name $homeKey -Value @{}
    }

    $claudeConfig.projects.$homeKey.enabledMcpjsonServers = @(
        "filesystem", "shell", "git", "http", "mongodb",
        "sqlite", "excel", "playwright", "ssh"
    )
    $claudeConfig.projects.$homeKey.disabledMcpjsonServers = @()
    $claudeConfig.projects.$homeKey.hasTrustDialogAccepted = $true

    $claudeConfig | ConvertTo-Json -Depth 10 | Set-Content -Path $ClaudeJson -Encoding UTF8
    Write-Host "  已更新: $ClaudeJson"
} else {
    Write-Host "  未找到 .claude.json，跳过。首次启动 Claude Code 后重新运行此脚本即可。"
}

# ========== 完成 ==========
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  安装完成!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "已安装的 MCP 服务器:" -ForegroundColor White
Write-Host "  filesystem  - 文件系统操作"
Write-Host "  shell       - 终端命令执行"
Write-Host "  git         - Git 仓库管理"
Write-Host "  http        - HTTP/API 请求"
Write-Host "  mongodb     - MongoDB 数据库"
Write-Host "  sqlite      - SQLite 数据库"
Write-Host "  excel       - Excel/CSV 文件"
Write-Host "  playwright  - 浏览器自动化"
Write-Host "  ssh         - SSH 远程连接"
Write-Host ""
Write-Host "重启 Claude Code 后即可使用。首次启动会自动下载 MCP 依赖包。" -ForegroundColor Gray
Write-Host ""
