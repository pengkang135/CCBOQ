# 记忆系统改进计划 — 进度审核报告

**审核日期**: 2026-05-16
**审核方式**: 逐项对照计划文档 + 实时系统状态验证

---

## 总体结论

计划整体完成度约 **35%**（自报加权约 78%）。代码层（~75%）是唯一实质进展，触发层（~30%）和数据层（~10%）几乎空白。

```
代码层: ███████████████░░░░░  75%  (工具存在但部分未验证)
触发层: ██████░░░░░░░░░░░░░░  30%  (CLAUDE.md 归档指令存在，cron 自动化是空想)
数据层: ██░░░░░░░░░░░░░░░░░░  10%  (7 条记忆，0 条向量索引)
```

**核心指标**: `memory_vec_count = 0` — 记忆系统的语义检索能力尚未激活。

---

## 逐项差距

| 阶段              | 自报 | 实际 |      差距      | 关键问题                                                 |
| ----------------- | :--: | :--: | :------------: | -------------------------------------------------------- |
| 0. OpenClaw 接入  | 85% | 75% |      -10%      | Gateway 稳定性不足（刚崩溃），watchdog 今天才部署        |
| 1. 周期性自动维护 | 95% | 30% | **-65%** | openclaw.json 中零个 cron 定义，vec_reindex 从未完整执行 |
| 2. 自主记忆策划   | 90% | 40% | **-50%** | 仅 7 条记忆（5月15日审核时 18 条，不增反降）             |
| 3. 通用知识库     | 70% | 60% |      -10%      | 2 vaults 已注册但代码独立安装未做                        |
| 4. 时间衰减+频率  | 95% | 70% |      -25%      | memory_vec_count=0，记忆无向量索引                       |
| 5. 自改进循环     | 85% | 35% | **-50%** | 仅 3 个 skills（2 个是索引占位），无自动化循环运行       |
| 6. Hermes 整合    | 80% | 10% | **-70%** | 无进程运行，无数据积累，无夜间 pipeline                  |
| 7. 三支柱联调     | 30% |  5%  |      -25%      | 仅 OpenClaw + librarian 在线，端到端测试为零             |

---

## 三大根因

### 1. Cron 自动化全部停留在纸面上（Phase 1 最大差距）

计划写了"5 个 Cron job"，但 openclaw.json 的 cron 配置段中一条实际 job 定义都没有。`vec_reindex` 从未执行过（memory_vec_count=0 是铁证）。`check_stale`、`recalc_decay` 等维护工具全部存在但无人调用。

### 2. 记忆数量在倒退（Phase 2 核心问题）

上次审核（5月15日）memory_entries 从 14 增至 18。今天仅剩 7 条。可能是 reindex 时清理了重复条目，但无论如何，自主策划机制没有产生**净增长**。CLAUDE.md 的会话归档指令存在但触发率极低——大多数对话结束时 Agent 并未执行归档流程。

### 3. Hermes 完全缺席（Phase 6 未启动）

cli.py 代码写好了（9 个命令组），但没有 Hermes 进程在运行。session 数据没有积累，夜间分析 pipeline 不存在。三支柱实际只有一根半在运作（OpenClaw 不稳定 + librarian 功能可用）。

---

## 不在计划内但已完成的新增项

| 新增项                   |  状态  | 说明                                                                       |
| ------------------------ | :----: | -------------------------------------------------------------------------- |
| 免疫系统 (watchdog)      | 已部署 | Windows 计划任务每 5 分钟检测 port 18789，崩溃后自动重启 gateway           |
| 崩溃分析 (analyze-crash) | 已部署 | 崩溃时自动收集日志、进程快照，生成 crash report，调用 Claude Code 分析根因 |
| 崩溃报告归档             | 已部署 | crash-reports/ 目录，最多保留 10 份历史报告                                |

---

## 下一步行动建议（按优先级）

### 立即（本周）

1. [ ] **在 openclaw.json 中定义 Cron job**。至少先上 3 个：

    - [ ] `vec_reindex` — 每周日凌晨，解决 memory_vec_count=0
    - [ ] `recalc_decay` — 每日凌晨，激活衰减排序
    - [ ] `check_stale` — 每 6 小时，检测过期文档
2. [ ] **验证 CLAUDE.md 归档指令是否实际触发**。连续 3 次有实质内容的对话后检查 memory_entries 是否增长。如果不触发，排查原因（指令是否被忽略 / 工具调用是否失败）
3. [ ] **Gateway 稳定性**。等待一次真实崩溃，验证 watchdog + analyze-crash 端到端流程是否正常工作。

### 短期（2-4 周）

4. **积累 session 数据**。确保每次对话结束后 session 摘要写入 librarian。这是 Phase 6 Hermes 的前置条件。
5. **开始 Hermes 部署**。不需要等所有前置条件完美——先跑通夜间分析的最小 pipeline：读取 session → 建议记忆 → 人工审批 → 写入。
6. **清理 skills**。现有 3 个 skills 中 2 个是索引占位。要么归档删除，要么补充实际内容。

### 中期（1-3 个月）

7. 重新评估 Phase 3（代码独立安装）和 Phase 5（自改进循环）的启动时机——前提是 Phase 1/2 已经稳定运行。

---

## 审核方法

本次审核通过实时系统状态验证：

- librarian vaults: `list_vaults` → 2 vaults 确认
- librarian memories: `memory_list` → 7 条确认
- librarian skills: `list_skills` → 3 条确认（2 active, 1 draft）
- librarian vectors: `vec_stats` → 403 passages, **0 memories**, 512 dims
- OpenClaw gateway: `netstat -ano` → PID 44888, port 18789 LISTENING
- OpenClaw cron: 直接读取 `openclaw.json` → cron 段存在但无 job 定义
- Scheduled tasks: `schtasks` → OpenClawGateway (Running), OpenClawWatchdog (Ready)
