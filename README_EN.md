# Claude Code Global Configuration

17 MCP Servers + 11 Skills + 17 Plugins + Notification Sound Hooks. One-command setup.

[中文](README.md) | English

## Getting Started

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

## MCP Servers (17)

### Files & Documents
| MCP | Runtime | Purpose |
|---|---|---|
| filesystem | npx | Safe file system operations (covers C:/E:/F:) |
| shell | npx | Terminal commands, file search, process management, PDF generation |
| excel | npx | Excel/CSV read/write and formatting |
| pdf2md | python (local) | PDF to Markdown (with OCR) |
| pandoc | uvx | Document format conversion (Markdown/PDF/DOCX/LaTeX etc.) |

### Database
| MCP | Runtime | Purpose |
|---|---|---|
| mongodb | npx | MongoDB official MCP |
| sqlite | npx | SQLite database (~/.claude/data.db) |
| librarian | python (local) | Project knowledge base ingestion & retrieval (FeynmanLibrary) |

### Web & Browser
| MCP | Runtime | Purpose |
|---|---|---|
| http | npx | HTTP requests, web scraping |
| playwright | npx | Browser automation |
| chrome-devtools | npx | Chrome DevTools debugging (performance / Lighthouse / memory) |

### Developer Tools
| MCP | Runtime | Purpose |
|---|---|---|
| git | npx | 29 Git operations + workflows |
| ssh | npx | SSH remote connection & SFTP |
| docker | uvx | Docker container management |
| sequential-thinking | npx | Step-by-step reasoning for complex problems |
| serena | uvx | Code symbol-level navigation & refactoring |

### OCR
| MCP | Runtime | Purpose |
|---|---|---|
| rapid-ocr | python (local) | Chinese OCR recognition |

## Skills (11)

| Skill | Purpose |
|---|---|
| docx / pdf / pptx / xlsx | Office document creation & editing |
| wx-cli | Local WeChat database queries (chats / contacts / groups) |
| pk-boq | Full-process construction cost BOQ handling |
| translation-agent | Engineering technical document translation |
| baoyu-format-markdown | Markdown formatting & typesetting |
| mcp-builder | Create MCP servers |
| skill-creator | Create and optimize skills |
| thinking-in-files | File-based thinking for complex tasks |

## Plugins (17)

| Plugin | Purpose |
|---|---|
| superpowers | Development workflow enhancement (TDD / planning / debugging / review) |
| frontend-design | Frontend design |
| feature-dev | Guided feature development |
| code-review / pr-review-toolkit | Code & PR review |
| code-simplifier | Code simplification & quality improvement |
| commit-commands | Git commit / PR shortcut commands |
| security-guidance | Security guidance |
| code-modernization | Code modernization & migration |
| context7 | Third-party library documentation lookup |
| github / playwright / chrome-devtools-mcp | UI enhancement for corresponding MCP |
| hookify | Hook rule engine (programmable behavior control) |
| session-report | Session reporting |
| skill-creator | Skill authoring tool |
| claude-md-management | CLAUDE.md configuration management |

## Hooks

| Hook | Trigger | Effect |
|---|---|---|
| Stop | Task completion | Play notification sound |
| PermissionRequest | Permission request popup | Play notification sound |

Sound files are located in the `sounds/` directory, played by `C:/Users/Kevin/claude-code-config/sounds/play-mp3.ps1`.

## Permission Model

`settings.json` uses an `allow` + `ask` dual-list approach:

- **allow (auto-allowed):** Read / Glob / Grep / Edit / Write / NotebookEdit, Bash(*), mcp__* (all MCP tools), WebSearch, WebFetch
- **ask (requires confirmation):** drop database/table, git reset/rebase, rm/del/taskkill, browser run_code_unsafe

## Configuration Architecture

```
C:\Users\Kevin\
  ├── claude-code-config/     ← This repository (Git version control)
  │   ├── settings.json.template
  │   ├── settings.local.json
  │   ├── .mcp.json            ← MCP server definitions (source)
  │   ├── .claude.json.partial
  │   ├── setup.ps1 / setup.sh
  │   └── sounds/              ← Hook notification sounds
  ├── .claude/                 ← Claude Code runtime configuration
  │   ├── settings.json
  │   ├── CLAUDE.md
  │   ├── skills/              ← Global skills
  │   ├── plugins/             ← Plugin cache
  │   └── mcp-servers/         ← Local MCP servers (rapid-ocr etc.)
  ├── .mcp.json                ← MCP servers (read by /mcp command)
  └── .claude.json             ← Claude Code runtime state
```

### MCP Three-File Sync Rule

When adding, removing, or modifying MCP services, three files must be kept in sync:

| File | Purpose |
|---|---|
| `C:\Users\Kevin\.mcp.json` | Source format definition |
| `C:\Users\Kevin\claude-code-config\.mcp.json` | Git template copy |
| `C:\Users\Kevin\.claude.json` → `mcpServers` | Runtime state (User + Local scopes) |

## Updating Configuration

1. Edit template files in this repository
2. Commit and push to GitHub
3. On other machines, `git pull` then re-run setup

## Security Notice

- **NEVER** commit `settings.json` or any files containing API keys / credentials
- The setup script **interactively asks** for sensitive information and does not write them to templates
- `.gitignore` excludes sensitive files

## License

MIT
