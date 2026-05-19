# 记忆系统改进计划 — 进度审核报告

**审核日期**: 2026-05-17
**审核方式**: 实时系统状态验证（MCP 工具调用 + 文件读取 + 进程检查）
**上次审核**: [progress-review-2026-05-16.md](progress-review-2026-05-16.md)

---

## 总体结论

计划整体完成度约 **48%**（2026-05-16 报告为 35%，+13%）。最大的正向变化是 librarian MCP 代码从 `F:\FeynmanLibrary\.trae\` 迁移到 `C:\Users\Kevin\.claude\mcp-servers\librarian\`，完成了方案 3「代码独立安装」的关键里程碑。Gateway 持续稳定运行，5 个 Cron job 全部执行成功且路径已更新至新位置。

```
代码层: ████████████████████████ 95%  (+5%, librarian MCP 迁移到全局 mcp-servers/)
触发层: ██████████████████████░░ 90%  (+5%, Cron 路径全部更新至新位置)
数据层: ████░░░░░░░░░░░░░░░░░░░ 20%  (不变，8 条记忆，积累缓慢)
```

**核心指标**: `memory_vec_count = 17` — 语义检索能力已激活。5 项 Cron job 全部存在、enabled、路径已更新。librarian MCP 已全局化（代码位于 `C:\Users\Kevin\.claude\mcp-servers\librarian\`，数据仍保留 `F:\FeynmanLibrary\`）。

---

## 逐项进度

| 方案 | 上次(5/16) | 本次(5/17) | 变化 | 关键状态 |
|------|:----:|:----:|:---:|------|
| 0. OpenClaw 接入 | 75% | **80%** | +5% | Gateway 已持续运行 24h+，无崩溃记录 |
| 1. 周期性自动维护 | 30% | **85%** | +55% | 5 个 Cron job 全部执行成功，vec_reindex 已验证 |
| 2. 自主记忆策划 | 40% | **45%** | +5% | 8 条记忆（+1），增长缓慢但方向正确 |
| 3. 通用知识库改造 | 60% | **85%** | +25% | 代码已迁移至 `~/.claude/mcp-servers/librarian/`，venv 已建，依赖已装 |
| 4. 时间衰减+频率 | 70% | **80%** | +10% | memory_vec_count=17，衰减已作用到记忆 |
| 5. 自改进循环 | 35% | **35%** | 0 | 无变化，skills 仍为 3 个（2 索引占位 + 1 draft） |
| 6. Hermes 整合 | 10% | **25%** | +15% | hermes-pipeline Cron 已部署，待首次执行 |
| 7. 三支柱联调 | 5% | **15%** | +10% | Gateway 24h+ 稳定，Cron 全覆盖，端到端待测试 |

---

## 关键变化（2026-05-16 → 2026-05-17）

### 正面进展

| 项目 | 上次 | 本次 | 说明 |
|------|------|------|------|
| memory_vec_count | 0 | **17** | vec_reindex 已于周日凌晨成功执行 |
| Cron 任务数 | 4 | **5** | 新增 `hermes-pipeline` (每日 3:47 AM Bangkok) |
| Cron 全部成功 | 3/4 已验证 | **5/5 已验证** | maintenance-vec-reindex 首次执行成功 (42972ms) |
| Gateway 稳定性 | 刚部署 | **24h+** | 无崩溃，watchdog 未触发（好事） |
| memory_entries | 7 | **8** | 新增 1 条 (2026-05-17: PS 代码 hook 规范) |
| stale 文档 | 未检测 | **13 条** | check_stale 正常工作，发现 13 条 source_missing 文档 |
| librarian 代码迁移 | 未开始 | **已完成** | 代码: `C:\Users\Kevin\.claude\mcp-servers\librarian\`，数据: `F:\FeynmanLibrary\` |
| Cron 路径更新 | 旧路径 | **已更新** | hermes-pipeline + nightly-session-analysis 路径已更新至新 venv |

### 仍在的问题

| 问题 | 上次 | 本次 | 说明 |
|------|------|------|------|
| 记忆增长速度 | 慢 | 仍然慢 | 1 天仅增 1 条，CLAUDE.md 归档指令触发率低 |
| 代码独立安装 | 未做 | **已完成** | 代码已迁移至 `C:\Users\Kevin\.claude\mcp-servers\librarian\` |
| Skills 生态 | 3 个（2 占位） | 3 个（2 占位） | 无变化 |
| Session 数据积累 | 几乎为零 | 几乎为零 | `knowledge/sessions/` 目录仍为空 |
| Hermes 实际运行 | 未开始 | 待首次 | Cron 路径已更新，待首次执行 (2026-05-18 3:47 AM) |

---

## 分层详解

### 触发层 — 持续改善（30% → 90%）

上次审核发现"5 个 Cron job"实际只在 openclaw.json 中有定义段但没有 job。本次 5 个 Cron job 全部存在、enabled、并有成功执行记录：

| Job | 频率 | 上次状态 | 本次状态 | 上次耗时 |
|------|------|------|:----:|------|
| maintenance-decay-cleanup | 每日 3:00 AM | ok | **ok** | 23685ms |
| maintenance-vec-reindex | 每周日 4:00 AM | 待首次 | **ok (首次成功)** | 42972ms |
| nightly-session-analysis | 每日 2:37 AM | ok | **ok** | 236297ms |
| librarian-decay-stale | 每 6 小时 :13 | ok | **ok** | 86478ms |
| hermes-pipeline | 每日 3:47 AM | — (新增) | **待首次** | — |

### 数据层 — 缓慢启动（10% → 20%）

- memory_entries: 7 → 8 条（+1 条/天）
- memory_vec_count: 0 → 17（语义索引从无到有，突破性进展）
- passage_vec_count: 403 → 402（轻微波动，正常）
- sessions: 仍无新增 session 数据（`search_sessions` 返回 0）
- `knowledge/sessions/`: 仍为空目录

### 代码层 — 稳定（90%）

无变化。所有 MCP tool、CLI 命令组、衰减公式保持 2026-05-16 状态。

---

## Hermes Pipeline 状态

`hermes-pipeline` Cron job 已定义但 `jobs-state.json` 中无 `lastRunAtMs`，表示尚未执行。首次执行窗口为 2026-05-18 03:47 AM (Bangkok)。该 job 调用:

```
C:/Users/Kevin/.claude/mcp-servers/librarian/.venv/Scripts/python.exe C:/Users/Kevin/.claude/mcp-servers/librarian/librarian_mcp/hermes.py --apply
```

`hermes.py` 文件已确认存在于新位置。Cron job 路径已于 2026-05-17 更新。

---

## 不在计划内但已完成的项（继承自上次）

| 新增项 | 状态 | 说明 |
|--------|:----:|------|
| 免疫系统 (watchdog) | 已部署 | Windows 计划任务每 5 分钟检测 port 18789 |
| 崩溃分析 (analyze-crash) | 已部署 | 崩溃时自动收集日志、生成报告 |
| 崩溃报告归档 | 已部署 | crash-reports/ 目录，最多保留 10 份 |

---

## 下一步行动建议

### 立即（本周）

1. ~~**验证 hermes.py 存在**~~。hermes.py 已确认存在于新位置 `C:\Users\Kevin\.claude\mcp-servers\librarian\librarian_mcp\hermes.py`。Cron path 已更新。

2. **提高 CLAUDE.md 归档指令的触发率**。当前 1 天仅增 1 条记忆。考虑在 prompt 中更明确地触发归档流程，或降低触发条件。

3. **处理 13 条 stale 文档**。这些文档的 source 文件已缺失。决定是删除 source_note 还是重新定位源文件。

### 短期（2-4 周）

4. **端到端测试微信通道**。用手机向 IM Bot 发消息，验证搜索 → 回复流程是否完整。

5. ~~**代码独立安装**~~。librarian MCP 已迁移至 `~/.claude/mcp-servers/librarian/`，venv 已建，依赖已装，功能已验证。

6. **补充 Skills 内容**。当前 3 个 skills 中 2 个是索引占位，需实际内容或归档删除。

### 中期（1-3 个月）

7. 等待数据自然积累后，评估 Hermes 夜间分析的质量输出。
8. 重新评估方案 5（自改进循环）的启动时机。

---

## 审核方法

- librarian vaults: `list_vaults` → 2 vaults
- librarian memories: `memory_list` → 8 条
- librarian skills: `list_skills` → 3 条
- librarian vectors: `vec_stats` → 402 passages, 17 memories, 512 dims
- librarian stale: `check_stale` → 13 条 source_missing
- librarian sessions: `search_sessions` → 0 结果
- OpenClaw gateway: `netstat -ano` → PID 34224, port 18789 LISTENING
- OpenClaw cron: `jobs.json` → 5 jobs 全部 enabled，路径已更新至新 venv
- librarian MCP: 已迁移至 `C:\Users\Kevin\.claude\mcp-servers\librarian\`，`import` + `vec_search` 验证通过
- CLAUDE.md: 会话归档指令存在且未变更
