# Claude Code settings.json 配置完全指南

> 基于官方文档 + GitHub 社区最佳实践 + 实战踩坑经验
> 最后更新: 2026-05-16

---

## 一、配置架构概览

### 1.1 配置文件层级

```
优先级从高到低:
  Managed Settings (企业 IT 推送)  ← 最高
  CLI 参数 (--flag)                  ← 临时覆盖
  settings.local.json                ← 个人敏感信息，不提交 Git
  .claude/settings.json              ← 项目级配置
  ~/.claude/settings.json            ← 用户全局配置

注：settings.local.json 不会被 git 跟踪（在 .gitignore 中），
    适合存放 API Token、个人权限覆盖等敏感配置。
```

### 1.2 配置目录结构

```
~/.claude/
  ├── settings.json          ← 主配置（权限、env、hooks、插件）
  ├── settings.local.json    ← 本地覆盖（不入 Git）
  ├── CLAUDE.md              ← 全局行为准则
  ├── .mcp.json              ← MCP 服务器定义
  ├── plugins/               ← 插件缓存
  ├── skills/                ← 全局 Skills
  └── knowledge/             ← 文档/最佳实践（本报告所在位置）
```

---

## 二、settings.json 完整字段说明

### 2.1 权限系统 (permissions)

```
permissions 是 settings.json 最核心的配置部分。
规则执行顺序：deny → ask → allow，先匹配生效。
```

```json
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Edit",
      "Write",
      "mcp__server-name__tool-name",
      "mcp__server-name__*"
    ],
    "deny": [
      "Bash(curl:*)",
      "WebSearch"
    ],
    "ask": [
      "Bash(rm *)",
      "Bash(sudo *)"
    ],
    "defaultMode": "default",
    "additionalDirectories": [
      "/path/to/extra/dir"
    ]
  }
}
```

#### 权限目标语法（官方支持的格式）

| 格式 | 示例 | 说明 |
|------|------|------|
| `ToolName` | `Read` `Write` `Edit` `Bash` | 精确工具名 |
| `ToolName(*)` | `Bash(*)` | 该工具的所有操作 |
| `Bash(pattern)` | `Bash(curl:*)` `Bash(npm:*)` | 匹配命令前缀 |
| `mcp__<server>__<tool>` | `mcp__github__create-issue` | 精确 MCP 工具 |
| **`mcp__<server>__*`** | `mcp__playwright__*` | MCP 服务器所有工具（官方文档支持） |
| `mcp__*` | `mcp__*` | **未在官方文档中出现，实际效果不稳定** |

#### `deny` 列表 — 永远禁止（最高优先级）

```
deny 里被拒绝的工具，即使在 ask 或 allow 里也不会被准许。
适用于：敏感文件访问、危险命令模式等。
```

社区推荐 deny 项：
- `Bash(curl:*)` + `Bash(wget:*)` — 防止数据外泄
- `Bash(ssh:*)` — SSH 凭证保护
- `Bash(eval:*)` — 防止代码注入
- `Read(**/*.env)` — 环境变量文件保护
- `Read(**/*secret*)` — 凭证文件保护

#### `ask` 列表 — 使用前询问

```
ask 列表是安全与效率的平衡层。
适合放那些"可能合法但不常用"的操作。
```

当前 Kevin 配置的 ask 列表：
- `mcp__mongodb__drop-database` / `drop-collection` / `delete-many` / `drop-index`
- `mcp__sqlite__delete_records`
- `mcp__ssh__sftp_rm`
- `mcp__git__git-reset` / `git-rebase`
- `Bash(rm *)` / `Bash(del *)` / `Bash(rmdir *)` / `Bash(taskkill *)`

#### `allow` 列表 — 直接允许

```
allow 列表遵循"宽泛授权 + ask 兜底"原则：
- 通配符覆盖常用工具和 MCP 服务
- 破坏性操作留在 ask 中
```

#### `defaultMode` 参数

```
值: "default" | "acceptEdits" | "bypassPermissions" | "plan"

"default" — 标准模式，遵循 permissions 配置
"acceptEdits" — 自动接受文件编辑（不用逐个确认）
"bypassPermissions" — 跳过所有权限检查（dangerous mode）
"plan" — 只读模式，仅允许 Read/Grep/Glob
```

#### `additionalDirectories` 参数

```
扩展 Claude Code 可以访问的目录（超出项目工作目录）。

重要：这些额外目录只在当前会话级别生效。
VS Code 环境默认只能访问项目 workspace，需要用此参数扩展。
```

当前 Kevin 配置：
```json
"additionalDirectories": [
  "c:\\Users\\Kevin\\AppData\\Roaming\\Trae\\User",
  "C:\\Users\\Kevin\\.claude",
  "C:\\Users\\Kevin\\.claude\\skills"
]
```

#### 权限匹配规则（重要！）

```
deny  →  ask  →  allow（按此顺序判定）
第一个匹配的规则决定命运。

示例：
  deny:  ["Bash(curl:*)"]     → curl 完全不能执行
  allow: ["Bash(*)"]           → 本应允许所有 Bash，但 deny 先生效

通配符匹配逻辑：
  Bash(*) 匹配任何 Bash 命令
  Bash(npm:*) 匹配 npm install, npm test 等，不匹配 npm（无参数时）
  mcp__server__* 匹配该服务器的所有工具
```

### 2.2 环境变量 (env)

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    "ANTHROPIC_SMALL_FAST_MODEL": "claude-haiku-4-5-20251001",
    "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_FEEDBACK_COMMAND": "1",
    "DISABLE_ERROR_REPORTING": "1"
  }
}
```

**关键约束：env 变量必须写在 `"env"` 对象内部。JSON schema 会拒绝顶级的环境变量。**

常用 env 变量：
| 变量 | 作用 |
|------|------|
| `ANTHROPIC_BASE_URL` | API 端点（可指向代理/第三方 API） |
| `ANTHROPIC_AUTH_TOKEN` | API 认证 Token |
| `ANTHROPIC_MODEL` | 默认模型 |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | 轻量模型（Agent 工具等使用） |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | 中等模型 |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | 旗舰模型 |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub API Token |
| `DISABLE_TELEMETRY` | 设为 "1" 禁用遥测 |
| `DISABLE_FEEDBACK_COMMAND` | 设为 "1" 禁用反馈提示 |
| `DISABLE_ERROR_REPORTING` | 设为 "1" 禁用错误报告 |
| `NO_PROXY` | 代理绕过列表 |
| `HTTP_PROXY` / `HTTPS_PROXY` | HTTP/HTTPS 代理 |

### 2.3 Hooks 系统

```json
{
  "hooks": {
    "PreToolUse": [{ "matcher": "...", "hooks": [...] }],
    "PostToolUse": [{ "matcher": "...", "hooks": [...] }],
    "Notification": [{ "matcher": "...", "hooks": [...] }],
    "Stop": [{ "matcher": "...", "hooks": [...] }],
    "UserPromptSubmit": [{ "matcher": "...", "hooks": [...] }],
    "SessionStart": [{ "matcher": "...", "hooks": [...] }],
    "PreCompact": [{ "matcher": "...", "hooks": [...] }]
  }
}
```

**Hook 事件说明：**
| 事件 | 触发时机 | 典型用途 |
|------|----------|----------|
| `PreToolUse` | 工具执行前 | 拦截危险命令、代码审查、规则检查 |
| `PostToolUse` | 工具执行后 | 自动格式化、日志记录 |
| `Notification` | 权限请求等通知 | 自定义权限通知处理 |
| `Stop` | 会话结束时 | 播放提示音、保存状态 |
| `UserPromptSubmit` | 用户提交消息时 | 注入上下文、预处理 |
| `SessionStart` | 会话开始时 | 初始化、加载配置 |
| `PreCompact` | 上下文压缩前 | 保存关键信息 |

**Hook 配置结构：**
```json
{
  "matcher": "Bash",        // 工具名匹配器（空字符串匹配所有）
  "hooks": [{
    "type": "command",       // 类型：command（目前唯一支持的类型）
    "command": "python3 /path/to/script.py",
    "timeout": 15000,        // 超时（毫秒），默认 60000
    "statusMessage": "🔍",   // 执行中的状态提示
    "async": true            // 异步执行（不阻塞工具调用）
  }]
}
```

**当前 Kevin 配置的 Hooks：**

1. **Stop Hook** — 会话完成时播放提示音：
```json
{
  "matcher": "",
  "hooks": [{
    "type": "command",
    "command": "powershell -STA -File \"C:/Users/Kevin/claude-code-config/sounds/play-mp3.ps1\" -Path \"C:/Users/Kevin/claude-code-config/sounds/command-complete-fantasy_ui_button.mp3\"",
    "timeout": 15,
    "statusMessage": "🔊",
    "async": true
  }]
}
```

2. **PermissionRequest Hook** — 权限请求时播放提示铃：
```json
{
  "hooks": [{
    "type": "command",
    "command": "powershell -STA -File \"C:/Users/Kevin/claude-code-config/sounds/play-mp3.ps1\" -Path \"C:/Users/Kevin/claude-code-config/sounds/permission-prompt-ship-bell-two-chimes.mp3\"",
    "timeout": 10,
    "statusMessage": "🔔",
    "async": true
  }]
}
```

**VS Code 扩展注意事项：**
- `PermissionRequest` hook 在 VS Code 中会阻塞在权限对话框之后，造成死锁
- 解决方案：PermissionRequest hook 只做声音提醒，不做权限判断
- 权限判断逻辑用 `PreToolUse` hook 实现

### 2.4 声音系统

```
Windows PowerShell MediaPlayer 方案：
- 脚本路径: C:\Users\Kevin\claude-code-config\sounds\play-mp3.ps1
- 使用 Windows.Media.MediaPlayer API
- 必须使用 -STA (Single Threaded Apartment) 模式
- 脚本自动等待播放完成后退出
```

play-mp3.ps1 核心逻辑：
```powershell
param([string]$Path)
Add-Type -AssemblyName PresentationCore
$player = New-Object System.Windows.Media.MediaPlayer
$player.Open($Path)
# 等待加载 → 播放 → 等待完成 → 关闭
```

可用的音效文件：
- `command-complete-fantasy_ui_button.mp3` — Stop hook 使用
- `permission-prompt-ship-bell-two-chimes.mp3` — PermissionRequest hook 使用

### 2.5 插件系统 (enabledPlugins)

```json
{
  "enabledPlugins": {
    "plugin-name@claude-plugins-official": true,
    "plugin-name@claude-plugins-official": false
  }
}
```

当前 Kevin 启用 17 个插件：
- `frontend-design` — 前端 UI 设计与组件开发
- `context7` — 实时文档查询
- `github` — GitHub API 集成
- `playwright` — 浏览器自动化测试
- `commit-commands` — Git 提交工作流
- `feature-dev` — 功能开发流程（code-architect, code-explorer, code-reviewer）
- `code-review` — 代码审查
- `code-simplifier` — 代码简化重构
- `security-guidance` — 安全指导
- `code-modernization` — 代码现代化迁移
- `pr-review-toolkit` — PR 审查工具集
- `hookify` — Hook 规则创建与管理
- `session-report` — 会话报告
- `chrome-devtools-mcp` — Chrome DevTools MCP
- `superpowers` — Skills 自动加载
- `skill-creator` — Skill 创建工具
- `claude-md-management` — CLAUDE.md 管理

### 2.6 其他配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `model` | string | 默认模型 (`sonnet`, `opus`, `haiku`) |
| `cleanupPeriodDays` | number | 会话保留天数（默认 30） |
| `includeCoAuthoredBy` | bool | 是否在 commit 中包含 Co-Authored-By（默认 true） |
| `skipDangerousModePermissionPrompt` | bool | 跳过 `/dangerous` 模式的确认弹窗 |
| `language` | string | 界面语言（`chinese` 等） |
| `theme` | string | 主题（`dark`, `light`） |
| `showTokensCounter` | bool | 是否显示 Token 计数器 |
| `autoCompactThreshold` | number | Token 压缩触发阈值 |
| `sandbox` | object | 沙箱配置（Bash 隔离级别） |
| `statusLine` | object | 状态栏配置 |

### 2.7 `skipDangerousModePermissionPrompt` 详解

```
这个参数 ONLY 控制 /dangerous 模式切换时的确认弹窗。
设置为 true: 执行 /dangerous 时不再弹出确认对话框。
设置为 false: 每次切换到 bypass-permissions 模式都弹窗确认。

它不影响日常工具权限弹窗（那些由 permissions.ask 控制）。
```

---

## 三、MCP 操作权限体系

### 3.1 MCP 权限通配符（官方文档 vs 实际行为）

**官方文档明确支持的格式：**
```
mcp__<server-name>__<tool-name>     精确匹配某个工具
mcp__<server-name>__*               匹配某 MCP 服务的所有工具
```

**官方文档未出现的格式：**
```
mcp__*                              匹配所有 MCP 工具（未文档化）
```

**实际行为差异（VS Code 扩展 vs CLI）：**
| 环境 | `mcp__server__*` 生效 | `mcp__*` 生效 |
|------|:---:|:---:|
| CLI 终端 | ✅ | ✅（未确认） |
| VS Code 扩展 | ✅ | ❌ 可能不生效 |
| Web 版 | ✅ | 未测试 |

**踩坑结论：** `mcp__*` 在 VS Code 扩展中可靠性不足，某些 MCP 工具即使在 allow 中有 `mcp__*` 仍然弹窗。GitHub Issue #3428 报告了类似的通配符问题。

**实践方案（当前 Kevin 配置）：**
```json
// 方案：mcp__* 作为顶层宽泛兜底
//      + mcp__<server>__* 针对每个 MCP 服务单独授权
//      + 已确认会弹窗的特定工具也加入 allow（防御性编程）

"allow": [
  "mcp__*",                                    // 顶层通配（CLI 环境稳定）
  "mcp__filesystem__*",                        // 16 个 MCP 服务的 service 级通配
  "mcp__shell__*",
  "mcp__git__*",
  "mcp__http__*",
  "mcp__mongodb__*",
  "mcp__sqlite__*",
  "mcp__excel__*",
  "mcp__playwright__*",
  "mcp__ssh__*",
  "mcp__librarian__*",
  "mcp__rapid-ocr__*",
  "mcp__pdf2md__*",
  "mcp__docker__*",
  "mcp__pandoc__*",
  "mcp__chrome-devtools__*",
  "mcp__sequential-thinking__*",
  "mcp__serena__*",
  "mcp__plugin_context7_context7__*",
  "mcp__plugin_playwright_playwright__*"
]
```

### 3.2 Kevin 配置的 17 个 MCP 服务

| MCP 服务 | 运行时 | 功能 |
|----------|--------|------|
| filesystem | `npx` | 文件系统操作 |
| shell | `uvx` | Shell 终端控制（Desktop Commander） |
| git | `uvx` | Git 版本控制 |
| http | `uvx` | HTTP 请求 |
| mongodb | `uvx` | MongoDB 数据库操作 |
| sqlite | `uvx` | SQLite 数据库操作 |
| excel | `uvx` | Excel 文件读写 |
| playwright | `npx` | 浏览器自动化 |
| ssh | `npx` | SSH 远程连接 |
| librarian | `python` | 知识管理/记忆（FeynmanLibrary） |
| rapid-ocr | `python` | OCR 图片文字识别 |
| pdf2md | `uvx` | PDF 转 Markdown |
| docker | `uvx` | Docker 容器管理 |
| pandoc | `uvx` | 文档格式转换 |
| chrome-devtools | `npx` | Chrome DevTools 协议 |
| sequential-thinking | `npx` | 结构化思维链 |
| serena | `uvx` | 代码理解与重构 |

---

## 四、安全与放权平衡策略

### 4.1 三层防御体系（社区最佳实践）

```
第一层: CLAUDE.md 规则
  - 用自然语言约束行为准则
  - 不需要技术实现，最简单

第二层: .claude/rules/ 目录
  - 结构化规则文件（MD/YAML）
  - 按文件/模块/语言约束

第三层: permissions 配置
  - 技术级硬约束
  - deny → ask → allow 链条
```

### 4.2 权力分级策略

**Level 1: 最小权限（适合：团队共用、CI/CD）**
```json
"allow": ["Read", "Grep", "Glob", "WebSearch"],
"ask": ["Edit", "Write", "Bash(*)"],
"deny": ["Bash(curl:*)", "Bash(wget:*)", "Bash(ssh:*)"]
```

**Level 2: 编程友好（适合：日常开发）**
```json
"allow": [
  "Read", "Grep", "Glob", "Edit", "Write",
  "Bash(git:*)", "Bash(npm:*)", "Bash(npx:*)",
  "WebSearch", "WebFetch"
],
"ask": [
  "Bash(rm *)", "Bash(docker:*)", "Bash(kubectl:*)",
  "Bash(curl:*)", "Bash(pip:*)"
]
```

**Level 3: 最大自主（适合：高级用户单人开发）**
```json
"allow": [
  "Bash(*)", "Edit", "Write", "Read", "Grep", "Glob",
  "WebSearch", "WebFetch", "Skill(*)", "Agent",
  "mcp__*",
  "mcp__filesystem__*", "mcp__shell__*", "mcp__git__*",
  "mcp__playwright__*", "... 各 MCP 服务通配"
],
"ask": [
  "mcp__mongodb__drop-database",
  "mcp__mongodb__drop-collection",
  "mcp__mongodb__delete-many",
  "Bash(rm *)", "Bash(del *)", "Bash(rmdir *)",
  "Bash(taskkill *)"
]
```

Kevin 当前配置采用的正是 Level 3（最大自主），通过 ask 列表保留对破坏性操作的确认。

### 4.3 关键安全原则

1. **deny 永远优先** — 先写 deny，再写 allow
2. **Bash 安全策略** — 用 `Bash(rm *)` 而不是 `Bash(rm*)`（带空格的精确匹配）
3. **敏感文件保护** — `Read(**/*.env)` 放入 deny 或 ask
4. **凭证保护** — 不要把 API Token 直接写在项目的 settings.json 中
5. **定期审计** — 查看 `~/.claude/auto-approve-safe-tools.ps1` 等自动生成的脚本

### 4.4 GitHub 社区参考仓库

| 仓库 | 亮点 |
|------|------|
| `dwillitzer/claude-settings` | 900+ 权限模式，全面的 deny/ask/allow 示例 |
| `hnts/claude-code-security-snippets` | 安全导向配置，共享敏感文件检测 |
| `shanraisshan/claude-code-best-practice` | 最佳实践合集，含 hooks 示例 |
| `ZacheryGlass/.claude` | 完整 `.claude` 配置可供参考 |
| `FlorianBruniaux/claude-code-ultimate-guide` | 终极指南，含多场景配置模板 |

---

## 五、当前 Kevin 配置分析

### 5.1 配置概览

```
安全级别: Level 3（最大自主 + 破坏操作确认）
权限模式: default（标准模式，走 deny→ask→allow 链）
模型: opus（deepseek-v4-pro 代理）
MCP 服务: 20 个（17 原生 + 3 插件）
Hooks: Stop（声音）+ PermissionRequest（声音）
插件: 17 个（全部启用）
```

### 5.2 配置亮点

- **MCP 权限覆盖完整** — 20 个 MCP 服务各有独立 `__*` 通配 + 顶层 `mcp__*` 兜底
- **破坏性操作有确认** — 数据库删除、文件删除、进程终止等留在 ask 列表
- **声音提醒系统** — Stop + PermissionRequest 双音效，交互体验好
- **凭证通过 env 管理** — API Token 集中在 `env` 字段
- **additionalDirectories 精确配置** — 只扩展必要的目录访问权限

### 5.3 改进建议

1. **考虑添加 `deny` 列表**：
   ```json
   "deny": [
     "Read(**/.env)",        // 保护 .env 文件
     "Read(**/*secret*)",    // 保护包含 secret 的文件
     "Read(**/*credential*)" // 保护凭证文件
   ]
   ```

2. **考虑添加 `settings.local.json`**：
   将 Token 类敏感信息移入 `settings.local.json`（不提交 Git），settings.json 只保留结构配置。

3. **PreToolUse hook 可选增强**：
   如需更细粒度的危险命令拦截（如 `git push --force`），可用 PreToolUse hook 做正则检查。

4. **定期检查 auto-approve 条目**：
   注意 settings.json 中是否被自动添加了新条目（Claude Code 有时会自动扩展 allow 列表）。

---

## 六、常见问题

### Q1: `mcp__*` 为什么不总是生效？

A: VS Code 扩展的权限系统与 CLI 有差异。`mcp__*` 是未文档化的通配符，虽然 CLI 环境可能工作，但 VS Code 扩展可能无法识别。可靠做法是为每个 MCP 服务添加 `mcp__<server>__*`。

### Q2: PermissionRequest hook 在 VS Code 中的行为？

A: VS Code 的权限对话框是模态的，会阻塞 Hook 执行。如果 PermissionRequest hook 有复杂逻辑，会形成死锁。建议 PermissionRequest hook 只做轻量操作（如播放声音），权限判断用 PreToolUse hook。

### Q3: `skipDangerousModePermissionPrompt` 影响日常使用吗？

A: 不影响。它只控制 `/dangerous` 命令的确认弹窗，与日常工具权限弹窗无关。

### Q4: 环境变量必须在 `env` 对象内吗？

A: 是的。JSON schema 验证会拒绝顶级的环境变量字段（`Unrecognized fields: ANTHROPIC_BASE_URL, ...`）。

### Q5: `additionalDirectories` 和 `permissions.allow` 的关系？

A: `additionalDirectories` 扩展 Claude Code 能访问的文件系统范围；`permissions.allow` 控制允许执行哪些操作。两者互补：目录访问靠前者，操作授权靠后者。

---

## 参考资源

- [Claude Code 官方设置文档](https://docs.anthropic.com/en/docs/claude-code/settings)
- [Claude Code 权限文档](https://docs.anthropic.com/en/docs/claude-code/permissions)
- [Hooks 官方指南](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [MCP 官方文档](https://modelcontextprotocol.io)
- GitHub 社区参考仓库（见第四章）
