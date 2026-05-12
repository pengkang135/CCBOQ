# Claude Code 全局配置

17 个 MCP 服务器 + 11 个技能 + 17 个插件 + 声音提示 Hook，一键部署。

中文 | [English](README_EN.md)

## 快速开始

### Windows (PowerShell)
```powershell
git clone https://github.com/<username>/claude-code-config.git
cd claude-code-config
.\setup.ps1
```

### macOS / Linux
```bash
git clone https://github.com/<username>/claude-code-config.git
cd claude-code-config
bash setup.sh
```

## MCP 服务器 (17)

### 文件与文档
| MCP | 运行时 | 功能 |
|---|---|---|
| filesystem | npx | 文件系统安全操作（覆盖 C:/E:/F:） |
| shell | npx | 终端命令、文件搜索、进程管理、PDF 生成 |
| excel | npx | Excel/CSV 读写与格式化 |
| pdf2md | python (local) | PDF 转 Markdown（含 OCR） |
| pandoc | uvx | 文档格式互转（Markdown/PDF/DOCX/LaTeX 等） |

### 数据库
| MCP | 运行时 | 功能 |
|---|---|---|
| mongodb | npx | MongoDB 官方 MCP |
| sqlite | npx | SQLite 数据库（~/.claude/data.db） |
| librarian | python (local) | 项目知识库入库与检索（FeynmanLibrary） |

### 网络与浏览器
| MCP | 运行时 | 功能 |
|---|---|---|
| http | npx | HTTP 请求、网页抓取 |
| playwright | npx | 浏览器自动化 |
| chrome-devtools | npx | Chrome DevTools 调试（性能/Lighthouse/内存） |

### 开发工具
| MCP | 运行时 | 功能 |
|---|---|---|
| git | npx | 29 个 Git 操作 + 工作流 |
| ssh | npx | SSH 远程连接与 SFTP |
| docker | uvx | Docker 容器管理 |
| sequential-thinking | npx | 复杂问题分步推理 |
| serena | uvx | 代码符号级导航与重构 |

### OCR
| MCP | 运行时 | 功能 |
|---|---|---|
| rapid-ocr | python (local) | 中文 OCR 识别 |

## 技能 (11)

| 技能 | 用途 |
|---|---|
| docx / pdf / pptx / xlsx | Office 文档创建与编辑 |
| wx-cli | 本地微信数据库查询（聊天记录/联系人/群） |
| pk-boq | 工程造价 BOQ 全流程处理 |
| translation-agent | 工程技术文档翻译 |
| baoyu-format-markdown | Markdown 格式化排版 |
| mcp-builder | 创建 MCP 服务器 |
| skill-creator | 创建和优化技能 |
| thinking-in-files | 复杂任务文件化思考 |

## 插件 (17)

| 插件 | 用途 |
|---|---|
| superpowers | 开发工作流增强（TDD/计划/调试/审查） |
| frontend-design | 前端设计 |
| feature-dev | 功能开发引导 |
| code-review / pr-review-toolkit | 代码与 PR 审查 |
| code-simplifier | 代码简化与质量改进 |
| commit-commands | Git 提交/PR 快捷命令 |
| security-guidance | 安全指南 |
| code-modernization | 代码现代化迁移 |
| context7 | 第三方库文档查询 |
| github / playwright / chrome-devtools-mcp | 对应 MCP 的 UI 增强 |
| hookify | Hook 规则引擎（可编程行为控制） |
| session-report | 会话报告 |
| skill-creator | 技能创作工具 |
| claude-md-management | CLAUDE.md 配置管理 |

## Hooks

| Hook | 触发时机 | 行为 |
|---|---|---|
| Stop | 任务完成 | 播放提示音 |
| PermissionRequest | 权限请求弹窗 | 播放提示音 |

提示音文件位于 `sounds/` 目录，由 `~/claude-code-config/sounds/play-mp3.ps1` 播放。

## 权限模型

`settings.json` 采用 `allow` + `ask` 双重列表：

- **allow（自动允许）：** Read/Glob/Grep/Edit/Write/NotebookEdit、Bash(*)、mcp__*（所有 MCP 工具）、WebSearch/WebFetch
- **ask（需确认）：** 删库/删表（drop/delete）、git reset/rebase、rm/del/taskkill、浏览器 run_code_unsafe

## 配置架构

```
~
  ├── claude-code-config/     ← 本仓库（Git 版本控制）
  │   ├── settings.json.template
  │   ├── settings.local.json
  │   ├── .mcp.json            ← MCP 服务器定义（源）
  │   ├── .claude.json.partial
  │   ├── setup.ps1 / setup.sh
  │   └── sounds/              ← Hook 提示音
  ├── .claude/                 ← Claude Code 运行时配置
  │   ├── settings.json
  │   ├── CLAUDE.md
  │   ├── skills/              ← 全局技能
  │   ├── plugins/             ← 插件缓存
  │   └── mcp-servers/         ← 本地 MCP 服务器（rapid-ocr 等）
  ├── .mcp.json                ← MCP 服务器（供 /mcp 命令读取）
  └── .claude.json             ← Claude Code 运行时状态
```

### MCP 三文件同步规则

增删改 MCP 服务时，三个文件必须同步：

| 文件 | 用途 |
|---|---|
| `~/.mcp.json` | 源格式定义 |
| `~/claude-code-config/.mcp.json` | Git 模板副本 |
| `~/.claude.json` → `mcpServers` | 运行时状态（User + Local 两处） |

## 更新配置

1. 修改本仓库中的模板文件
2. 提交并推送到 GitHub
3. 在其他机器上 `git pull` 后重新运行 setup

## 安全提醒

- **绝对不要**提交 `settings.json` 或任何含 API Key/凭证的文件
- setup 脚本会**交互式询问**敏感信息，不写入模板
- `.gitignore` 已排除敏感文件

## License

MIT
