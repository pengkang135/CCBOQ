# 记忆系统改进计划 — 进度审核报告

**审核日期**: 2026-05-18
**审核方式**: 实时系统状态验证（SQLite 直查 + Cron 文件读取 + 进程检查）
**上次审核**: [progress-review-2026-05-17.md](progress-review-2026-05-17.md)

---

## 总体结论

计划整体完成度约 **58%**（2026-05-17 报告为 48%，+10%）。最大亮点是**记忆积累突破**——memory_entries 从 8 条飙升至 19 条（+137.5%），sessions 从 0 到 3，CLAUDE.md 归档指令开始生效。但同时 5 个 Cron job 中有 4 个因 LLM API 网络故障而失败，形成数据层增长、触发层衰退的分化格局。

```
代码层: ████████████████████████ 95%  (不变，librarian MCP 稳定)
触发层: ██████████████████░░░░░░ 70%  (-20%，4/5 Cron job 因 deepseek API 网络错误失败)
数据层: ████████░░░░░░░░░░░░░░░░ 35%  (+15%，记忆 19 条、sessions 3、skills 5)
```

**核心指标**: memory_entries=19, sessions=3, skills=5, passage_vec=402, memory_vec=17。Cron job 除 vec_reindex 外全部因 LLM 网络故障失败。Gateway 持续运行。

---

## 逐项进度

| 方案 | 上次(5/17) | 本次(5/18) | 变化 | 关键状态 |
|------|:----:|:----:|:---:|------|
| 0. OpenClaw 接入 | 80% | **80%** | 0 | Gateway 持续运行，port 18789 LISTENING (PID 1256) |
| 1. 周期性自动维护 | 85% | **65%** | -20% | 4/5 Cron job 因 deepseek API 网络故障失败 |
| 2. 自主记忆策划 | 45% | **70%** | +25% | 记忆 8→19 条，sessions 0→3，归档指令开始生效 |
| 3. 通用知识库改造 | 85% | **90%** | +5% | skills 5 个（含实际内容），代码/venv 稳定 |
| 4. 时间衰减+频率 | 80% | **80%** | 0 | passages decay 已有分布(avg=0.40)，但 access_count 全为 0 |
| 5. 自改进循环 | 35% | **40%** | +5% | skills 从 3→5 个，但 hermes-pipeline 因网络故障未执行 |
| 6. Hermes 整合 | 25% | **25%** | 0 | hermes.py 存在，但 pipeline cron 全部失败 |
| 7. 三支柱联调 | 15% | **15%** | 0 | Gateway 稳定，数据积累中，但 Cron 大面积失败 |

---

## 关键变化（2026-05-17 → 2026-05-18）

### 正面进展

| 项目 | 上次 | 本次 | 说明 |
|------|------|------|------|
| memory_entries | 8 | **19** | +11 条 (+137.5%)，含配置知识、代码规范、偏好等 |
| sessions | 0 | **3** | 突破性进展：session 数据开始被捕获并存入 DB |
| skills | 3 (2 占位) | **5** | 含 memory-system-diagnostics、nightly-session-analysis 等实际 skill |
| passages decay | 未检测 | **avg=0.40** | 衰减公式已生效，分布范围 0.1-1.0 |
| memory decay 列 | 未检测 | **已部署** | 19 条记忆全部有 decay_score=1.0（新记忆未衰减） |
| Gateway 稳定性 | 24h+ | **48h+** | 跨天持续运行，无崩溃 |

### 新出现的问题

| 问题 | 严重程度 | 说明 |
|------|:---:|------|
| Cron 大面积失败 | **高** | 4/5 job 因 `FailoverError: LLM request failed: network connection error` 失败 |
| 衰减清理停滞 | 中 | maintenance-decay-cleanup 连续 1 次 error，过期记忆不会被清理 |
| 夜间分析停滞 | 中 | nightly-session-analysis + hermes-pipeline 均失败，session 数据无法自动转化 |
| access_count 全为 0 | 中 | 19 条记忆、116,056 条 passage 的 access_count 均为 0，访问计数未接线 |
| Windows 自启动缺失 | 低 | 未找到 OpenClaw 相关的计划任务，Gateway 可能是手动启动的 |
| knowledge/sessions/ 仍为空 | 低 | session 数据走 DB（session_messages 表），但文件系统目录从未被填充 |

### 仍在的问题（继承自上次）

| 问题 | 上次 | 本次 | 说明 |
|------|------|------|------|
| 记忆增长速度 | 慢 | **显著改善** | 1 天增 11 条 (8→19)，CLAUDE.md 归档指令开始生效 |
| Skills 生态 | 3 个（2 占位） | **已改善** | 5 个含实际内容 |
| Session 数据积累 | 几乎为零 | **已改善** | 3 sessions 已入库 |
| Hermes 实际运行 | 待首次 | **仍未运行** | 网络故障导致 |
| 13 条 stale 文档 | 未处理 | **未处理** | 仍待清理 |

---

## 分层详解

### 数据层 — 突破性增长（20% → 35%）

```
memory_entries:  8  →  19   (+137.5%)
sessions:        0  →   3   (从无到有)
skills:          3  →   5   (+2，含实际内容)
passages:    124.7k → 116k  (减少 8.6k，可能因数据清理)
passage_vec:    402 → 402   (不变)
memory_vec:      17 →  17   (不变，新记忆尚未编入向量索引)
```

记忆内容分布：配置知识（settings.json 层级、MCP 优先级）、代码规范（PS hook）、用户偏好、Hook 规范等。新记忆来自 grow_session 流程。

**衰减现状**：

| 表 | 条目数 | access>0 | decay avg | decay range |
|----|:---:|:---:|:---:|:---:|
| passages | 116,056 | 0 | 0.40 | 0.10-1.00 |
| memory_entries | 19 | 0 | 1.00 | 全部 1.00 |

passages 的衰减分布正常（0.1~1.0），说明上次 `maintenance-decay-cleanup` 成功执行过。但 access_count 全为 0——搜索/阅读的访问计数仍未接线。

### 触发层 — 显著退步（90% → 70%）

5 个 Cron job 全部存在、enabled，但 4 个因 LLM API 故障失败：

| Job | 上次状态 | 本次状态 | 上次耗时 | 错误 |
|------|:---:|:---:|------|------|
| maintenance-decay-cleanup | ok | **error** | 31810ms | LLM request failed: network connection error |
| maintenance-vec-reindex | ok | **ok** | 42972ms | 最后成功: 2026-05-17 |
| nightly-session-analysis | ok | **error** | 62802ms | LLM request failed: network connection error |
| librarian-decay-stale | ok | **error** | 30622ms | LLM request failed: network connection error |
| hermes-pipeline | 待首次 | **error** | 27205ms | LLM request failed: network connection error |

**共同特征**：所有 job 使用 `deepseek/deepseek-v4-flash` 模型，全部报 `FailoverError` + `network connection error`。根因指向 deepseek API 不可达，而非 OpenClaw Cron 机制问题。

hermes-pipeline Cron 的路径已确认正确：
```
C:/Users/Kevin/.claude/mcp-servers/librarian/.venv/Scripts/python.exe
C:/Users/Kevin/.claude/mcp-servers/librarian/librarian_mcp/hermes.py --apply
```
但由于 LLM 故障，pipeline 从未实际执行过 hermes.py。

### 代码层 — 稳定（95%）

无变化。所有 MCP tool、CLI 命令组、衰减公式保持 2026-05-17 状态。

---

## Skills 生态现状

| Skill | 状态 | 摘要 |
|-------|:---:|------|
| SkillDrafts | active | 自动生成的技能草案索引 |
| AgentSkills | active | 用户稳定使用的正式技能索引 |
| memory-system-diagnostics | **active** | 记忆系统诊断：检查 vec、统计、Cron、stale 文档、Gateway 状态 |
| memory-system-diagnostics | draft | 同上但旧 draft 版本未清理 |
| nightly-session-analysis | draft | Claude Code CLI session 夜间分析 |

相比上次的"2 个索引占位 + 1 draft"，现在 5 个 skill 中有 3 个 active 和有实质内容。

---

## Hermes Pipeline 状态

`hermes-pipeline` Cron job 的首次执行窗口为 2026-05-18 03:47 AM (Bangkok)，但实际执行失败（LLM network error）。

`hermes.py` 确认存在于 `C:\Users\Kevin\.claude\mcp-servers\librarian\librarian_mcp\hermes.py`（70 行），包含批处理 pipeline 代码，从历史 session 提取记忆并写入 librarian。

**问题**: hermes-pipeline 通过 OpenClaw Cron 启动 agentTurn，agent 调 `exec` 工具运行 hermes.py。但如果 LLM 不可达，整个流程断在第一步（agent 无法启动）。需要备选方案：
- 直接用 Windows 计划任务定时调 Python 脚本，绕过 LLM 依赖
- 或排查 deepseek API 为何不可达

---

## 不在计划内但已部署的项（继承）

| 新增项 | 状态 | 说明 |
|--------|:----:|------|
| 免疫系统 (watchdog) | 已部署 | Windows 计划任务每 5 分钟检测 port 18789 |
| 崩溃分析 (analyze-crash) | 已部署 | 崩溃时自动收集日志、生成报告 |
| 崩溃报告归档 | 已部署 | crash-reports/ 目录，最多保留 10 份 |

---

## 下一步行动建议

### 紧急（本周）

1. **排查 deepseek API 网络故障**。所有 4 个失败 Cron job 共享同一错误。检查 deepseek API key 是否过期、网络是否可达、是否需要切换模型。

2. **为 hermes-pipeline 增加绕过 LLM 的直连方案**。hermes.py 是纯 Python 批处理脚本，不需要 Agent 中转。创建 Windows 计划任务直接调 Python 脚本。

3. **接线 access_count**。当前 19 条记忆和 116k passages 的 access_count 全为 0，衰减公式完全依赖 access_count 和 last_access_at，没有访问数据衰减就是盲的。

### 短期（2-4 周）

4. **处理 13 条 stale 文档**（继承自上次，仍未处理）。

5. **补充 Windows 自启动**。Gateway 当前依赖手动或未知方式启动，系统重启后需要自动拉起。

6. **端到端测试微信通道**（继承自上次，仍未测试）。

### 中期（1-3 个月）

7. 等待 Cron 恢复 + 数据自然积累后，评估 Hermes 夜间分析的质量输出。
8. 在 access_count 接线后，重新评估方案 4（时间衰减）和方案 5（自改进）的有效性。

---

## 审核方法

- librarian DB: SQLite 直查 `F:\FeynmanLibrary\.library\library.db`
- memories: `SELECT COUNT(*), decay_score, access_count FROM memory_entries` → 19 条
- sessions: `SELECT * FROM sessions` → 3 条
- skills: `SELECT * FROM skills` → 5 条
- vec counts: `passage_vec_rowids`=402, `memory_vec_rowids`=17
- decay: passages avg=0.40 (range 0.1-1.0), memories all 1.0
- access_count: 全部为 0（接线未完成）
- stale: 上次 check_stale 报告 13 条，本次未重新检测
- OpenClaw gateway: `netstat -ano` → PID 1256, port 18789 LISTENING
- OpenClaw cron: `C:\Users\Kevin\.openclaw\cron\jobs.json` + `jobs-state.json` → 5 jobs, 4 error
- hermes.py: 确认存在于新位置（70 行）
- CLAUDE.md: 会话归档指令存在且未变更
- Windows 计划任务: 未找到 OpenClaw 自启动任务
