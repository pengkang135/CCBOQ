# Claude Code 工程配置

一键安装 9 个 MCP 服务器 + 完整的工程开发环境配置。

## 快速开始

### Windows (PowerShell)
```powershell
git clone https://github.com/你的用户名/claude-code-config.git
cd claude-code-config
.\setup.ps1
```

### macOS / Linux
```bash
git clone https://github.com/你的用户名/claude-code-config.git
cd claude-code-config
bash setup.sh
```

## 包含的 MCP 服务器

| MCP | 包名 | 功能 |
|---|---|---|
| filesystem | @modelcontextprotocol/server-filesystem | 文件系统安全操作 |
| shell | @wonderwhy-er/desktop-commander | 终端命令、diff/patch 编辑 |
| git | github-mcp-server | 29 个 Git 操作 + 工作流 |
| http | mcp-fetch-server | HTTP/API 请求、网页抓取 |
| mongodb | mongodb-mcp-server | MongoDB 官方 MCP |
| sqlite | mcp-server-sqlite-npx | SQLite 数据库 |
| excel | @negokaz/excel-mcp-server | Excel/CSV 读写 |
| playwright | @playwright/mcp@latest | 浏览器自动化 |
| ssh | mcp-server-ssh | SSH 远程连接 |

## 兼容的 Skills（安装后可用）

```bash
/review           # 代码审查
/security-review  # 安全审查
/simplify         # 代码简化和质量改进
/init             # 初始化新项目的 CLAUDE.md
```

## 更新配置

1. 修改本仓库中的模板文件
2. 提交并推送到 GitHub
3. 在目标机器上 `git pull` 后重新运行 setup 脚本

## 添加新 MCP 服务器

1. 编辑 [.mcp.json](.mcp.json)，添加新的 MCP 条目
2. 编辑 [.claude.json.partial](.claude.json.partial)，将服务器名加入 `enabledMcpjsonServers`
3. 提交并推送，其他机器 git pull 后重跑 setup

## 安全提醒

- **绝对不要**提交 `settings.json` 或任何包含 API Key 的文件
- setup 脚本会**交互式询问** API Key，不会写入模板文件
- `.gitignore` 已配置忽略敏感文件

## License

MIT
