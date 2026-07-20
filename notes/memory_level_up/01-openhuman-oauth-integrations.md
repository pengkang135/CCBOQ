# OpenHuman 118+ OAuth 集成清单

> 研究日期: 2026-05-20
> 数据来源: GitHub 源码、README、Composio 官方目录、多篇技术深度解析

---

## 概述

OpenHuman 的 118+ 个第三方集成并非自行开发，而是构建在 **Composio** 集成平台之上。Composio 是一个面向 AI Agent 的工具集成 SDK，提供 250~1000+ 个预构建的工具集（toolkits），支持 OAuth2、API Key、Bearer Token 等多种认证方式。

OpenHuman 的集成架构：

```
118+ 服务 → Composio OAuth 层 → 标准化为 Markdown → Memory Tree
                ↓ 每 20 分钟 auto-fetch
```

---

## 已确认的集成清单（基于公开资料交叉验证）

### 邮件 & 日历
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Gmail | OAuth2 | README |
| Google Calendar | OAuth2 | README |
| Microsoft Outlook | OAuth2 | Composio 目录 |
| Microsoft Exchange | OAuth2 (beta) | Composio 目录 |

### 即时通讯
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Slack | OAuth2 | README |
| Discord | OAuth2 | 技术解析文章 |
| WhatsApp | - | pyshine 技术分析 |
| Telegram | - | pyshine 技术分析 |
| Microsoft Teams | OAuth2 | Composio 目录 |
| Google Chat | OAuth2 (beta) | Composio 目录 |

### 代码托管 & 开发
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| GitHub | OAuth2 | README |
| GitLab | OAuth2 | 技术解析文章 |
| Bitbucket | OAuth2 | 技术解析文章 |
| Azure DevOps | OAuth2 (beta) | Composio 目录 |

### 文档 & 知识管理
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Notion | OAuth2 | README |
| Google Drive | OAuth2 | README |
| Google Docs | OAuth2 | Composio 目录 |
| Google Sheets | OAuth2 | Composio 目录 |
| Google Slides | OAuth2 (beta) | Composio 目录 |
| OneDrive | OAuth2 | 技术解析文章 |
| Confluence | OAuth2 | 技术解析文章 |
| Dropbox | OAuth2 | 技术解析文章 |
| Figma | OAuth2 | 技术解析文章 |
| SharePoint | OAuth2 | Composio 目录 |

### 项目管理
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Jira | OAuth2 | README |
| Linear | OAuth2 | README |
| Asana | OAuth2 | 技术解析文章 |
| Trello | OAuth1 | 技术解析文章 |
| ClickUp | OAuth2 | Composio 目录 |
| Wrike | OAuth2 | Composio 目录 |

### CRM & 销售
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| HubSpot | OAuth2 | 技术解析文章 |
| Salesforce | OAuth2 | 技术解析文章 |
| Pipedrive | OAuth2 | Composio 目录 |
| Attio | OAuth2 | Composio 目录 |
| Zoho CRM | OAuth2 | Composio 目录 |
| Apollo | API Key | Composio 目录 |

### 支付 & 电商
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Stripe | API Key | README |
| Shopify | OAuth2 | Composio 目录 |
| WooCommerce | API Key (beta) | Composio 目录 |

### 视频会议
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Google Meet | OAuth2 | README (原生支持，AI 吉祥物可加入会议) |
| Zoom | OAuth2 | Composio 目录 |
| Microsoft Teams | OAuth2 | 同时属于即时通讯类 |

### 邮件营销
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Mailchimp | OAuth2 | Composio 目录 |
| SendGrid | API Key | Composio 目录 |
| Klaviyo | OAuth2 | Composio 目录 |
| Brevo (Sendinblue) | API Key | Composio 目录 |

### 社交媒体
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Twitter/X | OAuth2 | Composio 目录 |
| LinkedIn | OAuth2 (beta) | Composio 目录 |
| Reddit | OAuth2 | Composio 目录 |
| YouTube | OAuth2 | Composio 目录 |
| Facebook Pages | OAuth2 (beta) | Composio 目录 |
| Instagram | OAuth2 (beta) | Composio 目录 |

### 客服 & 工单
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Zendesk | OAuth2 | Composio 目录 |
| Freshdesk | Basic Auth | Composio 目录 |
| PagerDuty | OAuth2 | Composio 目录 |
| Intercom | OAuth2 | Composio 目录 |

### 其他工具
| 服务 | 认证方式 | 确认来源 |
|------|---------|---------|
| Airtable | OAuth2 | 技术解析文章 |
| Canva | OAuth2 | Composio 目录 |
| Calendly | OAuth2 | Composio 目录 |
| ElevenLabs | API Key | 内置 TTS |
| HeyGen | API Key | Composio 目录 |
| Spotify | OAuth2 | Composio 目录 |
| DocuSign | OAuth2 | Composio 目录 |
| PeopleDataLabs | API Key | Composio 目录 |
| SerpAPI | API Key | Composio 目录 |
| Firecrawl | API Key | Composio 目录 |
| Supabase | API Key | Composio 目录 |
| PostHog | API Key | Composio 目录 |
| Neon | API Key | Composio 目录 |
| Mem0 | API Key | Composio 目录 |

### 本地/内置工具（非 OAuth）
| 工具 | 类别 | 说明 |
|------|------|------|
| Web Search | 搜索 | DuckDuckGo / Brave Search |
| Web Scraper | 爬虫 | Firecrawl 集成 |
| Filesystem | 系统 | 文件读写 |
| Git | 开发 | Git 操作 |
| Lint/Test/Grep | 开发 | 代码分析 |
| STT | 语音 | 本地语音转文字 |
| ElevenLabs TTS | 语音 | 文字转语音 |
| Google Meet Agent | 会议 | 吉祥物加入会议 |
| Ollama | 本地模型 | 本地推理 |

---

## Composio 已弃用的 60 个工具集（2025-12-19）

以下工具集已被 Composio 弃用（无可用 actions），OpenHuman 中对应的集成可能受影响：

Adobe, Atlassian, Auth0, Braintree, Deel, Epic Games, Fitbit, Front, GoToWebinar, LastPass, RingCentral, Rippling, Sage, Salesforce Marketing Cloud, Twitch, Zoho Desk 等。

---

## 关键发现

1. **"118"这个数字来自 Composio 的集成目录总量**，不是 OpenHuman 独有。OpenHuman 通过 Composio SDK 继承了这些集成的 OAuth 接入能力。

2. **完整清单未公开**。README 和文档只列举了最受欢迎的 ~15 个。完整列表需查看：
   - `https://composio.dev/tools`（Composio 官方目录）
   - OpenHuman 源码 `src/openhuman/` 目录下的集成注册代码
   - 桌面应用内的 OAuth 连接设置界面

3. **对国内用户的实用价值有限**。118 个服务中绝大部分是欧美 SaaS（Gmail、Slack、Notion、HubSpot 等），**不支持微信、飞书、钉钉、企业微信**等国内平台。

4. **每个集成都变成了一个 typed tool**。连接后，agent 可以直接调用 Gmail 发邮件、在 GitHub 创建 Issue、查 Notion 文档等——不需要手动写 API 调用。

5. **auto-fetch 是真正的差异化能力**。每 20 分钟自动拉取全部已连接服务的最新数据，而不仅仅是手动触发。这是你当前架构完全没有的能力。

---

## 你当前架构可对标的部分

| OpenHuman 集成 | 你是否有 | 差距 |
|---------------|---------|------|
| Gmail | 无 | 可通过 MCP 接入 |
| GitHub | 无（但 Claude Code 有 git 工具） | 较小 |
| Slack/Discord/Telegram | 无 | 可通过 MCP 接入 |
| 微信 | OpenHuman 也没有 | 你是独有的 |
| Google Calendar | 无 | 可通过 MCP 接入 |
| Notion/Confluence | 无 | 可通过 MCP 接入 |
| 本地工具（文件/Git/搜索） | Claude Code 已有 | 无差距 |
| **auto-fetch** | **完全没有** | **核心差距** |

---

## 参考来源

- [OpenHuman GitHub](https://github.com/tinyhumansai/openhuman)
- [Composio 官方工具目录](https://composio.dev/tools)
- [Composio API 文档](https://docs.composio.dev/reference/api-reference/toolkits/getToolkits)
- [OpenHuman 深度技术解析 (cnblogs)](https://www.cnblogs.com/chemanlau/p/20017653)
- [OpenHuman 开源项目详解 (pyshine)](http://pyshine.com/OpenHuman-Personal-AI-Super-Intelligence/)
