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
echo "[1/5] 配置 API 密钥和模型..."

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
echo "[2/5] 创建配置目录..."
mkdir -p "$CLAUDE_DIR"
echo "  目录: $CLAUDE_DIR"

# ========== 3. 安装 settings.json ==========
echo ""
echo "[3/5] 安装 settings.json..."

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

# ========== 4. 安装 .mcp.json ==========
echo ""
echo "[4/5] 安装 MCP 服务器配置..."

MCP_PATH="$CLAUDE_DIR/.mcp.json"
if [ -f "$MCP_PATH" ]; then
    cp "$MCP_PATH" "$MCP_PATH.backup.$(date +%Y%m%d%H%M%S)"
    echo "  已备份原有配置"
fi

sed "s|{{HOME}}|$HOME|g" "$SCRIPT_DIR/.mcp.json" > "$MCP_PATH"
echo "  已安装: $MCP_PATH"

# ========== 5. 更新 .claude.json ==========
echo ""
echo "[5/5] 更新 .claude.json 项目配置..."

if [ -f "$CLAUDE_JSON" ]; then
    cp "$CLAUDE_JSON" "$CLAUDE_JSON.backup.$(date +%Y%m%d%H%M%S)"
    echo "  已备份原有配置"

    # 使用 Python 更新 JSON (跨平台)
    python3 -c "
import json, os
home = os.environ['HOME']
with open('$CLAUDE_JSON', 'r') as f:
    config = json.load(f)
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
with open('$CLAUDE_JSON', 'w') as f:
    json.dump(config, f, indent=2)
" 2>/dev/null || echo "  警告: Python3 不可用，跳过 .claude.json 更新。首次启动 Claude Code 后重新运行此脚本。"
else
    echo "  未找到 .claude.json，跳过。首次启动 Claude Code 后重新运行此脚本。"
fi

# ========== 完成 ==========
echo ""
echo "========================================"
echo "  安装完成!"
echo "========================================"
echo ""
echo "已安装的 MCP 服务器:"
echo "  filesystem  - 文件系统操作"
echo "  shell       - 终端命令执行"
echo "  git         - Git 仓库管理"
echo "  http        - HTTP/API 请求"
echo "  mongodb     - MongoDB 数据库"
echo "  sqlite      - SQLite 数据库"
echo "  excel       - Excel/CSV 文件"
echo "  playwright  - 浏览器自动化"
echo "  ssh         - SSH 远程连接"
echo ""
echo "重启 Claude Code 后即可使用。首次启动会自动下载 MCP 依赖包。"
echo ""
