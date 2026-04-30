#!/usr/bin/env bash
# Claude Code 配置一键安装脚本 (macOS / Linux)
# 使用方法: bash setup.sh

set -e

echo "========================================"
echo "  Claude Code 工程配置安装"
echo "========================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
CLAUDE_JSON="$HOME/.claude.json"

# ========== 1. 收集用户配置 ==========
echo "[1/6] 配置 API 密钥和模型..."

read -p "API Base URL (默认: https://api.anthropic.com): " ANTHROPIC_BASE_URL
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"

read -p "API Auth Token (必填): " ANTHROPIC_AUTH_TOKEN
if [ -z "$ANTHROPIC_AUTH_TOKEN" ]; then
    echo "错误: API Auth Token 不能为空!"
    exit 1
fi

read -p "默认模型 (默认: claude-sonnet-4-6): " ANTHROPIC_MODEL
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-4-6}"

read -p "Haiku 模型 (默认: claude-haiku-4-5-20251001): " HAIKU_MODEL
HAIKU_MODEL="${HAIKU_MODEL:-claude-haiku-4-5-20251001}"

read -p "Sonnet 模型 (默认: claude-sonnet-4-6): " SONNET_MODEL
SONNET_MODEL="${SONNET_MODEL:-claude-sonnet-4-6}"

read -p "Opus 模型 (默认: claude-opus-4-7): " OPUS_MODEL
OPUS_MODEL="${OPUS_MODEL:-claude-opus-4-7}"

read -p "界面语言 (默认: chinese): " LANGUAGE
LANGUAGE="${LANGUAGE:-chinese}"

read -p "主题 light/dark (默认: dark): " THEME
THEME="${THEME:-dark}"

# ========== 2. 创建目录 ==========
echo ""
echo "[2/6] 创建配置目录..."
mkdir -p "$CLAUDE_DIR"
echo "  目录: $CLAUDE_DIR"

# ========== 3. 安装 settings.json ==========
echo ""
echo "[3/6] 安装 settings.json..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    STOP_HOOK='afplay /System/Library/Sounds/Glass.aiff'
else
    STOP_HOOK='echo "Claude Code 已停止"'
fi

SETTINGS_PATH="$CLAUDE_DIR/settings.json"
if [ -f "$SETTINGS_PATH" ]; then
    cp "$SETTINGS_PATH" "$SETTINGS_PATH.backup.$(date +%Y%m%d%H%M%S)"
    echo "  已备份原有配置"
fi

sed \
    -e "s|{{ANTHROPIC_BASE_URL}}|$ANTHROPIC_BASE_URL|g" \
    -e "s|{{ANTHROPIC_AUTH_TOKEN}}|$ANTHROPIC_AUTH_TOKEN|g" \
    -e "s|{{ANTHROPIC_MODEL}}|$ANTHROPIC_MODEL|g" \
    -e "s|{{ANTHROPIC_DEFAULT_HAIKU_MODEL}}|$HAIKU_MODEL|g" \
    -e "s|{{ANTHROPIC_DEFAULT_SONNET_MODEL}}|$SONNET_MODEL|g" \
    -e "s|{{ANTHROPIC_DEFAULT_OPUS_MODEL}}|$OPUS_MODEL|g" \
    -e "s|{{LANGUAGE}}|$LANGUAGE|g" \
    -e "s|{{THEME}}|$THEME|g" \
    -e "s|{{EFFORT_LEVEL}}|high|g" \
    -e "s|{{STOP_HOOK_COMMAND}}|$STOP_HOOK|g" \
    "$SCRIPT_DIR/settings.json.template" > "$SETTINGS_PATH"
echo "  已安装: $SETTINGS_PATH"

# ========== 4. 安装全局 .mcp.json ==========
echo ""
echo "[4/6] 安装全局 MCP 服务器配置..."

MCP_PATH="$CLAUDE_DIR/.mcp.json"
if [ -f "$MCP_PATH" ]; then
    cp "$MCP_PATH" "$MCP_PATH.backup.$(date +%Y%m%d%H%M%S)"
    echo "  已备份原有配置"
fi

sed "s|{{HOME}}|$HOME|g" "$SCRIPT_DIR/.mcp.json" > "$MCP_PATH"
echo "  已安装 (全局): $MCP_PATH"

# ========== 5. 安装项目级 .mcp.json ==========
echo ""
echo "[5/6] 安装项目级 MCP 配置 (供 claude mcp list 读取)..."

PROJECT_MCP_PATH="$(pwd)/.mcp.json"
if [ -f "$PROJECT_MCP_PATH" ]; then
    cp "$PROJECT_MCP_PATH" "$PROJECT_MCP_PATH.backup.$(date +%Y%m%d%H%M%S)"
    echo "  已备份原有配置"
fi
cp "$MCP_PATH" "$PROJECT_MCP_PATH"
echo "  已安装 (项目级): $PROJECT_MCP_PATH"
echo "  (如需在其他项目使用，运行: cp ~/.claude/.mcp.json ./)"

# ========== 6. 更新 .claude.json (含 mcpServers) ==========
echo ""
echo "[6/6] 更新 .claude.json (mcpServers + enabledMcpjsonServers)..."

if [ -f "$CLAUDE_JSON" ]; then
    cp "$CLAUDE_JSON" "$CLAUDE_JSON.backup.$(date +%Y%m%d%H%M%S)"
    echo "  已备份原有配置"

    export CLAUDE_JSON
    python3 << 'PYEOF' 2>/dev/null && echo "  已更新 (含 mcpServers): $CLAUDE_JSON" || echo "  警告: Python3 不可用，请手动运行 claude mcp add 命令添加服务器。"
import json, os
home = os.environ['HOME']
claude_dir = home + '/.claude'

with open(os.environ['CLAUDE_JSON'], 'r') as f:
    config = json.load(f)

servers = {
    'filesystem': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@modelcontextprotocol/server-filesystem', home],
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
        'args': ['-y', 'mcp-sqlite', claude_dir + '/data.db'],
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

if 'projects' not in config:
    config['projects'] = {}
config['projects'][home] = {
    'enabledMcpjsonServers': [
        'filesystem', 'shell', 'git', 'http', 'mongodb',
        'sqlite', 'excel', 'playwright', 'ssh'
    ],
    'disabledMcpjsonServers': [],
    'hasTrustDialogAccepted': True
}

with open(os.environ['CLAUDE_JSON'], 'w') as f:
    json.dump(config, f, indent=2)
PYEOF
else
    echo "  未找到 .claude.json，跳过。首次启动 Claude Code 后重新运行此脚本。"
fi

# ========== 完成 ==========
echo ""
echo "========================================"
echo "  安装完成!"
echo "========================================"
echo ""
echo "已安装的 MCP 服务器 (共 9 个):"
echo "  filesystem  - 文件系统操作"
echo "  shell       - 终端命令执行"
echo "  git         - Git 仓库管理 (29 个操作)"
echo "  http        - HTTP/API 请求"
echo "  mongodb     - MongoDB 数据库 (需本地运行 mongod)"
echo "  sqlite      - SQLite 数据库"
echo "  excel       - Excel/CSV 文件读写"
echo "  playwright  - 浏览器自动化"
echo "  ssh         - SSH 远程连接"
echo ""
echo "重启 Claude Code 后即可使用。首次启动会自动下载 MCP 依赖包。"
echo "验证: claude mcp list"
echo ""
