# albedo-cfg — Personal Infrastructure Unified Configuration

This repository covers complete configuration for three systems, with one-click deployment to new machines.

## Coverage

| System | Runtime Path | Description |
|--------|-------------|-------------|
| **Claude Code** | `~/.claude/`, `~/.claude.json`, `~/.mcp.json` | 16 skills, 16 plugins, 13 MCP servers, hooks, permissions |
| **OpenClaw (Alice)** | `~/.openclaw/` | Desktop AI companion, WeChat + Telegram channels, memory-core system |
| **Librarian Knowledge Base** | `E:\Code\FeynmanLibrary\`, `~/.claude/knowledge/` | Vector search + full-text search knowledge base |

## Directory Structure

```
albedo-cfg/
├── claude/          → ~/.claude/   Claude Code runtime config
├── openclaw/        → ~/.openclaw/ OpenClaw full config
├── home/            → ~/           Root dotfiles
├── business-cards/  → ~/.claude/business-cards/  Contact cards
├── librarian/                      Vault registration info
├── notes/                          Configuration notes
├── deploy.ps1                      One-click deployment script
├── sync-public.ps1                 Public subset sync to CCBOQ
└── public-manifest.txt             CCBOQ public file manifest
```

## Repository Strategy

| Remote | Repository | Visibility |
|--------|-----------|------------|
| `origin` | `git@github.com:pengkang135/albedo-cfg.git` | Private (full) |
| `public` | `git@github.com:pengkang135/CCBOQ.git` | Public (subset) |

Same files, pushed to two repos. `sync-public.ps1` extracts the public subset per `public-manifest.txt` and pushes to CCBOQ.

## Quick Start

### New Machine Deployment

```powershell
git clone git@github.com:pengkang135/albedo-cfg.git $env:USERPROFILE\albedo-cfg
cd $env:USERPROFILE\albedo-cfg
.\deploy.ps1
```

deploy.ps1 interactively collects API tokens and completes full deployment.

### Existing Environment Sync

```powershell
cd $env:USERPROFILE\albedo-cfg
git pull
.\deploy.ps1   # incremental update
```

### Push to Public Repo

```powershell
.\sync-public.ps1
```

## Template Variables

All files containing `{{VAR}}` are expanded with values from env.ps1 during deploy.

| Variable | Description |
|----------|-------------|
| `{{ANTHROPIC_AUTH_TOKEN}}` | DeepSeek API key |
| `{{ANTHROPIC_BASE_URL}}` | API endpoint |
| `{{OPENCLAW_GATEWAY_TOKEN}}` | OpenClaw gateway auth token |
| `{{TELEGRAM_BOT_TOKEN}}` | Telegram Bot token |
| `{{TELEGRAM_OWNER_ID}}` | Telegram user numeric ID |
| `{{HOME}}` | Home directory (Unix style) |
| `{{HOME_WIN}}` | Home directory (Windows style) |
| `{{PYTHONW_PATH}}` | pythonw.exe path |
| `{{GITHUB_PERSONAL_ACCESS_TOKEN}}` | GitHub PAT |

## Config Architecture

```
C:\Users\Kevin\
├── albedo-cfg/           ← This repo (config source of truth)
├── .claude/              ← Claude Code runtime
├── .claude.json          ← Claude Code runtime state
├── .mcp.json             ← MCP server definitions
├── .openclaw/            ← OpenClaw runtime
└── CLAUDE.md             ← Global behavior guidelines
```

## MCP Servers (13)

| Server | Type | Runtime |
|--------|------|--------|
| filesystem | npx | mcp_launcher.py |
| shell | npx | mcp_launcher.py |
| git | npx | mcp_launcher.py |
| http | npx | mcp_launcher.py |
| mongodb | npx | mcp_launcher.py |
| sqlite | npx | mcp_launcher.py |
| excel | npx | mcp_launcher.py |
| playwright | npx | mcp_launcher.py |
| ssh | npx | mcp_launcher.py |
| chrome-devtools | npx | mcp_launcher.py |
| sequential-thinking | npx | mcp_launcher.py |
| docker | uvx | mcp_launcher.py |
| pandoc | uvx | mcp_launcher.py |
| serena | uvx | mcp_launcher.py |
| **librarian** | python | local venv |
| **rapid-ocr** | python | local venv |
| **pdf2md** | python | local venv |

## Skills (16)

baoyu-format-markdown / docx / excel-ast / material-price-inquiry / mcp-builder / pdf / pk-boq / pk-boq-inquiry / pk-boq-quotation / pptx / skill-creator / thinking-in-files / translation-agent / wx-cli / xlsx

## Plugins (16, all user scope)

frontend-design / context7 / github / playwright / commit-commands / feature-dev / code-review / code-simplifier / security-guidance / code-modernization / pr-review-toolkit / hookify / session-report / chrome-devtools-mcp / superpowers / skill-creator / claude-md-management

## OpenClaw Cron Jobs (6)

- `maintenance-decay-cleanup` — Daily 10:00 cleanup low-score entries
- `maintenance-vec-reindex` — Weekly Sunday 14:00 rebuild vector index
- `nightly-session-analysis` — Daily 10:37 Hermes memory extraction
- `librarian-decay-stale` — Every 6 hours decay calculation
- `hermes-pipeline` — Daily 11:47 Hermes pipeline
- `Memory Dreaming Promotion` — Daily 03:00 short-term memory promotion
