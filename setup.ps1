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
Write-Host "[1/6] 配置 API 密钥和模型..." -ForegroundColor Yellow

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
Write-Host "[2/6] 创建配置目录..." -ForegroundColor Yellow
if (-not (Test-Path $ClaudeDir)) {
    New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
    Write-Host "  已创建: $ClaudeDir"
} else {
    Write-Host "  目录已存在: $ClaudeDir"
}

# ========== 3. 安装 settings.json ==========
Write-Host ""
Write-Host "[3/6] 安装 settings.json..." -ForegroundColor Yellow

$stopHookCmd = 'powershell -c \"[System.Media.SystemSounds]::Hand.Play()\"'

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

# ========== 4. 安装全局 .mcp.json ==========
Write-Host ""
Write-Host "[4/6] 安装全局 MCP 服务器配置..." -ForegroundColor Yellow

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
Write-Host "  已安装 (全局): $mcpPath"

# ========== 5. 安装项目级 .mcp.json ==========
Write-Host ""
Write-Host "[5/6] 安装项目级 MCP 配置 (供 claude mcp list 读取)..." -ForegroundColor Yellow

$projectMcpPath = "$(Get-Location)\.mcp.json"
if (Test-Path $projectMcpPath) {
    $backup = "$projectMcpPath.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Copy-Item $projectMcpPath $backup
    Write-Host "  已备份原有配置: $backup"
}
Set-Content -Path $projectMcpPath -Value $mcpContent -Encoding UTF8
Write-Host "  已安装 (项目级): $projectMcpPath"
Write-Host "  (如需在其他项目使用，运行: copy ~/.claude/.mcp.json ./)"

# ========== 6. 更新 .claude.json (含 mcpServers) ==========
Write-Host ""
Write-Host "[6/6] 更新 .claude.json (mcpServers + enabledMcpjsonServers)..." -ForegroundColor Yellow

if (Test-Path $ClaudeJson) {
    $backup = "$ClaudeJson.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Copy-Item $ClaudeJson $backup
    Write-Host "  已备份原有配置: $backup"

    # 使用 Python 以确保 JSON 格式和转义正确
    $homePathPy = $env:USERPROFILE -replace '\\', '\\\\'
    $claudeDirPy = "$homePathPy\\\\.claude"
    $pythonScript = @"
import json

with open(r'$ClaudeJson', 'r', encoding='utf-8') as f:
    config = json.load(f)

servers = {
    'filesystem': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@modelcontextprotocol/server-filesystem', r'$env:USERPROFILE'],
        'env': {}
    },
    'shell': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@wonderwhy-er/desktop-commander'],
        'env': {}
    },
    'git': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '-p', 'github-mcp-server', 'github-mcp-server-mcp'],
        'env': {}
    },
    'http': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', 'mcp-fetch-server'],
        'env': {}
    },
    'mongodb': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', 'mongodb-mcp-server'],
        'env': {'MONGODB_URI': 'mongodb://localhost:27017'}
    },
    'sqlite': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', 'mcp-sqlite', r'$env:USERPROFILE\\.claude\\data.db'],
        'env': {}
    },
    'excel': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@negokaz/excel-mcp-server'],
        'env': {}
    },
    'playwright': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@playwright/mcp@latest'],
        'env': {}
    },
    'ssh': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', 'mcp-server-ssh'],
        'env': {}
    }
}

config['mcpServers'] = servers

home_key = r'$env:USERPROFILE'.replace('\\\\', '/')
if 'projects' not in config:
    config['projects'] = {}
config['projects'][home_key] = {
    'enabledMcpjsonServers': [
        'filesystem', 'shell', 'git', 'http', 'mongodb',
        'sqlite', 'excel', 'playwright', 'ssh'
    ],
    'disabledMcpjsonServers': [],
    'hasTrustDialogAccepted': True
}

with open(r'$ClaudeJson', 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print('OK')
"@
    $pythonResult = python -c $pythonScript 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  已更新 (含 mcpServers): $ClaudeJson"
    } else {
        Write-Host "  警告: Python 执行失败，尝试 PowerShell 回退..." -ForegroundColor Yellow
        # 回退：至少设置 enabledMcpjsonServers
        $claudeConfig = Get-Content $ClaudeJson -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $claudeConfig.projects) { $claudeConfig.projects = @{} }
        $homeKey = $env:USERPROFILE
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
        Write-Host "  已更新 (仅 enabledMcpjsonServers): $ClaudeJson"
    }
} else {
    Write-Host "  未找到 .claude.json，跳过。首次启动 Claude Code 后重新运行此脚本即可。"
}

# ========== 完成 ==========
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  安装完成!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "已安装的 MCP 服务器 (共 9 个):" -ForegroundColor White
Write-Host "  filesystem  - 文件系统操作"
Write-Host "  shell       - 终端命令执行"
Write-Host "  git         - Git 仓库管理 (29 个操作)"
Write-Host "  http        - HTTP/API 请求"
Write-Host "  mongodb     - MongoDB 数据库 (需本地运行 mongod)"
Write-Host "  sqlite      - SQLite 数据库"
Write-Host "  excel       - Excel/CSV 文件读写"
Write-Host "  playwright  - 浏览器自动化"
Write-Host "  ssh         - SSH 远程连接"
Write-Host ""
Write-Host "重启 Claude Code 后即可使用。首次启动会自动下载 MCP 依赖包。" -ForegroundColor Gray
Write-Host "验证: claude mcp list"
Write-Host ""
