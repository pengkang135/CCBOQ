# Claude Code 全量配置一键安装脚本 (Windows PowerShell)
# 使用方法: .\setup.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Claude Code 全量配置安装" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeDir = "$env:USERPROFILE\.claude"
$ClaudeJson = "$env:USERPROFILE\.claude.json"

# ========== 1. 收集用户配置 ==========
Write-Host "[1/2] 配置 API 密钥和模型..." -ForegroundColor Yellow

$ANTHROPIC_BASE_URL = Read-Host "API Base URL"
if ([string]::IsNullOrWhiteSpace($ANTHROPIC_BASE_URL)) {
    $ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
}

$ANTHROPIC_AUTH_TOKEN = Read-Host "API Auth Token (必填)"
if ([string]::IsNullOrWhiteSpace($ANTHROPIC_AUTH_TOKEN)) {
    Write-Host "错误: API Auth Token 不能为空!" -ForegroundColor Red
    exit 1
}

$ANTHROPIC_MODEL = Read-Host "默认模型 (默认: deepseek-v4-pro)"
if ([string]::IsNullOrWhiteSpace($ANTHROPIC_MODEL)) {
    $ANTHROPIC_MODEL = "deepseek-v4-pro"
}

$HAIKU_MODEL = Read-Host "Haiku 模型 (默认: deepseek-v4-flash)"
if ([string]::IsNullOrWhiteSpace($HAIKU_MODEL)) {
    $HAIKU_MODEL = "deepseek-v4-flash"
}

$SONNET_MODEL = Read-Host "Sonnet 模型 (默认: deepseek-v4-pro)"
if ([string]::IsNullOrWhiteSpace($SONNET_MODEL)) {
    $SONNET_MODEL = "deepseek-v4-pro"
}

$OPUS_MODEL = Read-Host "Opus 模型 (默认: deepseek-v4-pro)"
if ([string]::IsNullOrWhiteSpace($OPUS_MODEL)) {
    $OPUS_MODEL = "deepseek-v4-pro"
}

# ========== 2. 安装全量配置 ==========
Write-Host ""
Write-Host "[2/2] 安装全量配置到 $ClaudeDir ..." -ForegroundColor Yellow

# 创建目录
if (-not (Test-Path $ClaudeDir)) {
    New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
}

# --- 2a. settings.json ---
Write-Host "  [2a] 安装 settings.json"
$settingsContent = Get-Content "$ScriptDir\settings.json.template" -Raw
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_BASE_URL}}', $ANTHROPIC_BASE_URL)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_AUTH_TOKEN}}', $ANTHROPIC_AUTH_TOKEN)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_MODEL}}', $ANTHROPIC_MODEL)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_DEFAULT_HAIKU_MODEL}}', $HAIKU_MODEL)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_DEFAULT_SONNET_MODEL}}', $SONNET_MODEL)
$settingsContent = $settingsContent.Replace('{{ANTHROPIC_DEFAULT_OPUS_MODEL}}', $OPUS_MODEL)
$settingsContent = $settingsContent.Replace('{{HOME}}', $env:USERPROFILE)

$settingsPath = "$ClaudeDir\settings.json"
if (Test-Path $settingsPath) {
    $backup = "$settingsPath.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Copy-Item $settingsPath $backup
    Write-Host "    已备份: $backup"
}
Set-Content -Path $settingsPath -Value $settingsContent -Encoding UTF8

# --- 2b. .mcp.json ---
Write-Host "  [2b] 安装 .mcp.json"
$mcpContent = Get-Content "$ScriptDir\.mcp.json" -Raw
$mcpContent = $mcpContent.Replace('{{HOME}}', $env:USERPROFILE)
$mcpPath = "$ClaudeDir\.mcp.json"
if (Test-Path $mcpPath) {
    Copy-Item $mcpPath "$mcpPath.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
}
Set-Content -Path $mcpPath -Value $mcpContent -Encoding UTF8

# --- 2c. CLAUDE.md ---
Write-Host "  [2c] 安装 CLAUDE.md"
Copy-Item "$ScriptDir\CLAUDE.md" "$ClaudeDir\CLAUDE.md" -Force

# --- 2d. auto-approve-safe-tools.ps1 ---
Write-Host "  [2d] 安装 auto-approve-safe-tools.ps1"
Copy-Item "$ScriptDir\auto-approve-safe-tools.ps1" "$ClaudeDir\auto-approve-safe-tools.ps1" -Force

# --- 2e. settings.local.json ---
Write-Host "  [2e] 安装 settings.local.json"
Copy-Item "$ScriptDir\settings.local.json" "$ClaudeDir\settings.local.json" -Force

# --- 2f. scripts/ ---
Write-Host "  [2f] 安装 scripts/"
$scriptsDst = "$ClaudeDir\scripts"
if (-not (Test-Path $scriptsDst)) { New-Item -ItemType Directory -Path $scriptsDst -Force | Out-Null }
Copy-Item "$ScriptDir\scripts\*" $scriptsDst -Recurse -Force

# --- 2g. skills/ ---
Write-Host "  [2g] 安装 skills/"
$skillsDst = "$ClaudeDir\skills"
if (-not (Test-Path $skillsDst)) { New-Item -ItemType Directory -Path $skillsDst -Force | Out-Null }
Copy-Item "$ScriptDir\skills\*" $skillsDst -Recurse -Force

# --- 2h. plugins/ 配置 ---
Write-Host "  [2h] 安装 plugins/ 配置"
$pluginsDst = "$ClaudeDir\plugins"
if (-not (Test-Path $pluginsDst)) { New-Item -ItemType Directory -Path $pluginsDst -Force | Out-Null }
Copy-Item "$ScriptDir\plugins\installed_plugins.json" $pluginsDst -Force
Copy-Item "$ScriptDir\plugins\known_marketplaces.json" $pluginsDst -Force

# --- 2i. mcp-servers/ ---
Write-Host "  [2i] 安装 mcp-servers/"
$mcpServersDst = "$ClaudeDir\mcp-servers"
if (-not (Test-Path $mcpServersDst)) { New-Item -ItemType Directory -Path $mcpServersDst -Force | Out-Null }
Copy-Item "$ScriptDir\mcp-servers\*" $mcpServersDst -Recurse -Force

# --- 2j. sounds/ ---
Write-Host "  [2j] 安装 sounds/"
$soundsDst = "$ClaudeDir\sounds"
if (-not (Test-Path $soundsDst)) { New-Item -ItemType Directory -Path $soundsDst -Force | Out-Null }
Copy-Item "$ScriptDir\sounds\*" $soundsDst -Recurse -Force

# --- 2k. .claude.json (mcpServers) ---
Write-Host "  [2k] 更新 .claude.json"
$partialPath = "$ScriptDir\.claude.json.partial"
if (Test-Path $partialPath) {
    $partial = Get-Content $partialPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (Test-Path $ClaudeJson) {
        Copy-Item $ClaudeJson "$ClaudeJson.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
        $config = Get-Content $ClaudeJson -Raw -Encoding UTF8 | ConvertFrom-Json
    } else {
        $config = @{}
    }

    if ($partial.mcpServers) {
        $config.mcpServers = $partial.mcpServers
    }
    if ($partial.project) {
        $homeKey = $env:USERPROFILE
        if (-not $config.projects) { $config.projects = @{} }
        if (-not $config.projects.$homeKey) {
            $config.projects | Add-Member -MemberType NoteProperty -Name $homeKey -Value @{}
        }
        $config.projects.$homeKey.enabledMcpjsonServers = $partial.project.enabledMcpjsonServers
        $config.projects.$homeKey.disabledMcpjsonServers = $partial.project.disabledMcpjsonServers
        $config.projects.$homeKey.hasTrustDialogAccepted = $partial.project.hasTrustDialogAccepted
    }
    $config | ConvertTo-Json -Depth 10 | Set-Content -Path $ClaudeJson -Encoding UTF8
    Write-Host "    已更新"
} else {
    Write-Host "    .claude.json.partial 不存在，跳过"
}

# ========== 完成 ==========
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  安装完成!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "已安装的配置:" -ForegroundColor White
Write-Host "  settings.json          — 权限 / hooks / 偏好"
Write-Host "  .mcp.json              — MCP 服务器会话配置"
Write-Host "  .claude.json           — 全局 MCP 定义"
Write-Host "  CLAUDE.md              — 用户行为准则"
Write-Host "  auto-approve-safe-tools.ps1 — 安全工具自动审批"
Write-Host "  scripts/               — 自定义脚本"
Write-Host "  skills/                — 自定义 Skills"
Write-Host "  plugins/               — 插件安装清单"
Write-Host "  mcp-servers/           — 自定义 MCP 服务器"
Write-Host "  sounds/                — 音效文件"
Write-Host ""
Write-Host "重启 Claude Code 后即可使用。" -ForegroundColor Gray
