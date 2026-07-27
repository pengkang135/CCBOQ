# 记忆系统改进方案进度审核报告

> 2026-05-15，对 [memory-system-improvement-plan.md](../memory-system-improvement-plan.md) 的逐项核查。

---

## 审核方法论

每项交付物均在文件系统/数据库/进程层面**实际验证**，而非仅检查文档声明。验证手段：

- `.openclaw/` 配置文件直接阅读
- `library.db` SQLite 数据表结构和数据抽样
- `service.py` / `server.py` / `cli.py` 源码 grep
- Cron job state 文件检查（实际执行状态和耗时）
- Windows 计划任务检查
- 设备配对记录审计
- Hookify 规则文件检查
- `knowledge/` 共享目录内容检查

---

## 方案 0：OpenClaw 手机接入

**文档声称: 95% | 实际: 85%**

| 检查项 | 状态 | 证据 |
|--------|:----:|------|
| `.openclaw/` 目录完整 | 通过 | agents/cron/devices/identity/logs/memory/workspace 等全部子目录就绪 |
| `openclaw.json` 配置 | 通过 | Gateway 本地模式 :18789, DeepSeek provider (deepseek-chat + deepseek-reasoner), 3 个 MCP (librarian + filesystem + sqlite), cron 启用 |
| Windows 计划任务 | 通过 | `OpenClawGateway` 已注册，State: Ready |
| 设备配对 | 通过 | CLI 设备 (`cli` mode) 和 Webchat UI 设备均已配对，授予完整 operator 权限 (admin/read/write/approvals/pairing) |
| WeChat 插件 | 部分 | 插件已启用，`openclaw-weixin/accounts.json` 有 bot 账户 `4eb0632d467d-im-bot`。**但 `paired.json` 中没有微信设备记录**——扫码绑定状态无法确认 |
| `file-librarian` Skill | 通过 | `workspace/skills/file-librarian/SKILL.md` 内容完整，包含 9 个命令组、搜索策略、回复格式规范、维护任务说明 |
| API Key | 通过 | `openclaw.json` 中 `deepseek.apiKey` 已写入实际值（不再是 `${DEEPSEEK_API_KEY}` 占位符） |

**差距**: WeChat 扫码绑定无法确认是否完成。`paired.json` 中只有 CLI 和 Webchat 设备，微信设备配对不在其中（可能存储在其他位置，也可能尚未完成）。

---

## 方案 1：周期性自动维护

**文档声称: 100% | 实际: 95%**

| 检查项 | 状态 | 证据 |
|--------|:----:|------|
| `maintenance-recalc-check` (每 6 小时) | 通过 | `cron/jobs-state.json`: lastRunStatus=ok, lastDurationMs=75596, consecutiveErrors=0 |
| `maintenance-decay-cleanup` (每日 3AM) | 通过 | lastRunStatus=ok, lastDurationMs=65422, consecutiveErrors=0 |
| `maintenance-vec-reindex` (每周日 4AM) | 待首次触发 | nextRunAtMs 已排期，尚未到首次执行时间 |
| `librarian-decay-stale` (每 6 小时 :13) | 通过 | lastRunStatus=ok, lastDurationMs=25949, consecutiveErrors=0 |
| 全部 job enabled | 通过 | 4 个 Cron job 的 `enabled: true` |

**注意**: 定时任务由 OpenClaw 内置 Cron（`cron/jobs.json`）管理，非 Claude Code `CronCreate`。CC CronCreate 为空是正确的——OpenClaw 独立负责维护调度。

**差距**: `maintenance-vec-reindex` 首个执行窗口尚未到达，无法验证向量索引重建是否正常。

---

## 方案 2：自主记忆策划

**文档声称: 100% | 实际: 75%**

| 检查项 | 状态 | 证据 |
|--------|:----:|------|
| `suggest_memories` MCP tool | 通过 | `service.py:1297` + `server.py:626`，支持 FTS5 去重检查 |
| `grow_session` MCP tool | 通过 | `service.py:1255` + `server.py:235`，支持 `apply_memory` + `apply_skill_draft` |
| CLI `session suggest` | 通过 | `cli.py:115-119`，OpenClaw agent 可通过 exec 调用 |
| Hookify 规则 `auto-memory-curation` | **缺失** | `~/.claude/hookify.*.global.md` 中仅有旧的 `warn-onedrive-delete`，无记忆策划规则 |
| 实际记忆数据 | 弱 | 14 条 memory_entries 全部 `access_count=0, decay_score=1.0`，缺乏使用痕迹 |
| 对话结束后自动触发 | **未实现** | 无 session_end/stop Hook 触发 `suggest_memories` |

**结论**: 工具层代码已到位，但**触发层完全缺失**。对话结束后不会自动调用记忆策划。14 条记忆中无任何来自 OpenClaw agent 的写入。

---

## 方案 3：通用知识库改造

**文档声称: 85% | 实际: 70%**

| 检查项 | 状态 | 证据 |
|--------|:----:|------|
| `register_vault` + `list_vaults` | 通过 | `service.py:1432/1457` + `server.py:660/683` |
| `vaults.json` 注册表 | 通过 | `F:\FeynmanLibrary\.library\vaults.json`，已注册 2 个 vault: Feynman Knowledge Vault + Kevin Knowledge Hub |
| `search_summaries` 跨 vault | 通过 | `path_prefixes` 参数已实现 |
| CLI `vault list/register` | 通过 | `cli.py:90-107` |
| 代码独立安装 | **未完成** | librarian 代码仍在 `F:\FeynmanLibrary\.trae\`，未复制到 `~/.claude/mcp-servers/librarian/` |
| Kevin Knowledge Hub vault | 空壳 | `~/.claude/knowledge/` 下仅有空的 `sessions/` 目录，无实质知识内容 |

**差距**: vault 注册机制就绪，但第二个 vault 是空的，且 librarian 代码未独立打包。

---

## 方案 4：时间衰减 + 访问频率

**文档声称: 100% | 实际: 95%**

| 检查项 | 状态 | 证据 |
|--------|:----:|------|
| DB 字段 | 通过 | `passages` 和 `memory_entries` 均有 `access_count INTEGER`, `last_access_at TEXT`, `decay_score REAL` |
| 全量衰减计算 | 通过 | 124,688 passages + 14 memory_entries 的 decay_score 均已填充 |
| Ebbinghaus 公式 | 通过 | `service.py:2790-2808`: `decay_score = priority_base * e^(-lambda * days) * (1 + alpha * log(1 + access_count))` |
| 搜索排序集成 | 通过 | `service.py:254`: `ORDER BY p.priority DESC, score DESC, p.decay_score DESC` |
| `recalc_decay` 方法 | 通过 | `service.py:2736`，支持 target=all/passages/memories，参数可调 |
| `decay_cleanup` 方法 | 通过 | `service.py:2840-2877`，按 decay_score 阈值清理，dry_run 模式 |
| Cron 自动重算 | 通过 | `maintenance-recalc-check` 每 6 小时调用，已成功执行 |
| `maintain recalc` 首次执行 | 通过 | `cli.py maintain recalc` 已成功更新 124,688 passages + 14 memories |
| 访问计数自动递增 | 待验证 | `get_excerpt` 中应有 `access_count += 1`，但无端到端调用来验证 |

**差距**: 访问计数递增逻辑需通过实际搜索/阅读操作来端到端验证。

---

## 方案 5：自改进循环

**文档声称: 100% | 实际: 65%**

| 检查项 | 状态 | 证据 |
|--------|:----:|------|
| `analyze_session` MCP tool | 通过 | `service.py:1334` + `server.py:645`，返回 patterns/wins/pitfalls/skill_suggestions/memory_suggestions |
| `grow_session` (含 save_session_note) | 通过 | `service.py:1255`，支持 `apply_memory` + `apply_skill_draft` |
| CLI `session analyze` | 通过 | `cli.py:120-124` |
| CLI `session grow` | 通过 | `cli.py:125-132` |
| `promote_skill` MCP tool | **缺失** | `server.py` 中不存在 `promote_skill`，skill draft 可生成但无 promote 通路 |
| Hookify 规则 `auto-skill-improvement` | **缺失** | 无 session_end/stop Hook 触发 `analyze_session` |
| 实际数据 | 弱 | 仅 2 个旧 sessions (2026-05-05)，4 条 session_messages，无自改进记录 |

**结论**: 分析工具已到位，但两处断裂：(1) `promote_skill` 未实现，(2) Hookify 触发规则缺失。

---

## 方案 6：三支柱整合

**文档声称: 85% | 实际: 70%**

采用 `exec + cli.py` 方案（非原生 MCP bundling），这是当前 OpenClaw v2026.5.7 兼容的方式。

| 检查项 | 状态 | 证据 |
|--------|:----:|------|
| CLI 9 个命令组 | 通过 | search/excerpt/list/memory/price/maintain/vault/session/vec 全部实现 |
| exec + cli.py 桥接 | 通过 | `SKILL.md` 含完整 exec 调用模板，全部 9 个子命令 |
| `suggest_memories` + `analyze_session` | 通过 | 已在 cli.py session 子命令中封装 |
| 共享目录 `~/.claude/knowledge/sessions/` | 通过(空) | 目录已创建，但无任何 session 摘要文件 |
| Session 自动保存 Hook | **缺失** | 无 Hookify 规则将对话摘要写入 sessions 目录 |
| 夜间深度分析 Cron | **缺失** | Cron 仅做维护 (recalc/stale/cleanup)，未配置 session 批量分析 |
| OpenClaw agent 实际查询 | 未验证 | sessions 表仅有 2 条 5月5日旧记录，OpenClaw agent 尚未产生新 session |

**差距**: 桥接通道已通，但 session 数据流的上下游都缺——没有自动写入，也没有定期分析消费。

---

## 方案 7：三支柱联调

**文档声称: 10% | 实际: 15%**

| 检查项 | 状态 |
|--------|:----:|
| Gateway 运行中 | 通过（多 node 进程，计划任务 Ready） |
| librarian 可被 Gateway 调用 | 通过（Cron exec `cli.py maintain recalc` 成功） |
| MCP 全部通过 cli.py 暴露 | 通过（9 个命令组，exec 调用路径） |
| Cron 维护任务已执行 | 通过（4 个 job 中有 3 个至少成功执行 1 次） |
| WeChat 端到端 | 未验证（无微信设备配对证据、无微信收发记录） |
| 24h 稳定性 | 未验证（所有基础设施均在 5月14日夜-15日凌晨搭建，不足 24h） |
| 记忆跨渠道可见 | 未验证（无多渠道对话历史） |

---

## 汇总

| 方案 | 文档声称 | 核验实际 | 差距 |
|------|:---:|:---:|------|
| 0. OpenClaw 接入 | 95% | **85%** | WeChat 扫码绑定未确认 |
| 1. 自动维护 | 100% | **95%** | vec_reindex 待首次周日执行 |
| 2. 自主记忆策划 | 100% | **75%** | Hookify 记忆策划规则缺失 |
| 3. 通用 KB 改造 | 85% | **70%** | 代码独立安装未做，第二 vault 为空壳 |
| 4. 时间衰减 | 100% | **95%** | 访问计数递增待端到端验证 |
| 5. 自改进循环 | 100% | **65%** | Hookify 改进规则 + promote_skill 缺失 |
| 6. 三支柱整合 | 85% | **70%** | Session 自动保存 + 夜间分析 Cron 缺失 |
| 7. 联调 | 10% | **15%** | 端到端测试无证据，稳定性不足 24h |

### 代码层 vs 触发层

```
代码层 (service.py + server.py + cli.py):  ████████████████████░  90%
  - 9 个 CLI 命令组全部实现
  - 4 个新增 MCP tool (suggest_memories/analyze_session/register_vault/list_vaults)
  - 衰减公式 + cleanup + recalc 全部就绪
  - vaults.json 注册表 + 跨 vault 搜索

触发层 (Hookify + Cron + 自动化):        ██████░░░░░░░░░░░░░░░░  30%
  - 4 个 Cron job 正常运行
  - auto-memory-curation 规则缺失
  - auto-skill-improvement 规则缺失
  - session 自动保存规则缺失
  - 夜间 session 深度分析缺失

数据层 (实际使用痕迹):                    █░░░░░░░░░░░░░░░░░░░░░   5%
  - sessions: 仅 2 条旧记录
  - memory_entries: 14 条，无访问记录
  - knowledge/sessions/: 空目录
```

### 优先修复建议（原版）

<details>
<summary>原始建议（点击展开）</summary>

1. **P0**: 创建 Hookify `auto-memory-curation` 规则
2. **P0**: 创建 Hookify `auto-session-save` 规则
3. **P1**: 创建 Hookify `auto-skill-improvement` 规则
4. **P1**: 新增 `promote_skill` MCP tool
5. **P2**: 验证 WeChat 扫码绑定
6. **P2**: 代码独立安装到 `~/.claude/mcp-servers/librarian/`
</details>

---

## 2026-05-15 Round 2：触发层补全

> 本阶段集中解决 P0 触发层缺失问题。

### 已完成

| 项目 | 状态 | 交付物 |
|------|:----:|--------|
| Hookify `auto-memory-curation` 规则 | 完成 | `.claude/hookify.auto-memory-curation.global.md` — stop 事件，提醒 agent 调用 suggest_memories |
| Hookify `auto-session-save` 规则 | 完成 | `.claude/hookify.auto-session-save.global.md` — stop 事件，提醒 agent 调用 grow_session 写入摘要 |
| Hookify `auto-skill-improvement` 规则 | 完成 | `.claude/hookify.auto-skill-improvement.global.md` — stop 事件，提醒 agent 调用 analyze_session |
| 夜间 session 分析 Cron | 完成 | `jobs.json` 新增 `nightly-session-analysis`，每日 2:37 AM (Bangkok)，扫描 sessions 目录并执行 analyze+suggest+apply |
| `promote_skill` MCP tool | 确认已存在 | server.py:406 + service.py:1076，审核报告误判为缺失 |
| `knowledge/sessions/` 目录 | 已创建 | `C:\Users\Kevin\.claude\knowledge\sessions\` 就绪 |

### WeChat 状态澄清

WeChat 集成方式为 **IM Bot**（Tencent WeChat IM Bot API），非个人微信扫码。已配置：
- 插件 `@tencent-weixin/openclaw-weixin` v2.4.3，enabled: true
- Bot 账户 `4eb0632d467d-im-bot`，token 已写入
- userId: `o9cq809SL1kDlRKihnesdJSmayZU@im.wechat`
- 该类型不使用 device pairing，因此 `paired.json` 中无微信设备记录是**预期行为**

### 更新后的分层完成度

```
代码层 (service.py + server.py + cli.py):  ████████████████████░  90%  (不变)
触发层 (Hookify + Cron + 自动化):        ████████████████░░░░░░  80%  (+50%)
  - 4 个 Cron job 正常运行
  + 3 个 Hookify stop 规则就位
  + 1 个夜间 session 分析 Cron 新增
  
数据层 (实际使用痕迹):                    █░░░░░░░░░░░░░░░░░░░░░   5%  (不变，需时间积累)
```

### 剩余待完成

- [ ] 代码独立安装到 `~/.claude/mcp-servers/librarian/`（方案 3 解耦，P2）
- [ ] 24h+ 稳定性验证（方案 7 联调，P2）
- [ ] 端到端测试：微信消息 → 搜索 → 回复（P2）
- [ ] 数据积累：等待新 session 和 memory 数据自然增长
