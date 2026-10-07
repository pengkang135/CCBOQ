# pk-boq-db-match Scripts

## 执行顺序

```
01_pull_rate_pool.py       ─┐
02_extract_boq.py          ─┼─ Stage 1 数据准备
03_dedup_pool.py           ─┘
04_cluster_retrieve.py     ── Stage 2 检索 + 候选池构建
05_split_packages.py       ── Stage 3 分包给 Matcher

  [dispatch Haiku Matchers ×N via Agent tool]  ── Stage 3 LLM 执行
  [dispatch Sonnet Reviewer via Agent tool]    ── Stage 4 LLM 复核
  [dispatch Sonnet Compare+Auditor via Agent]  ── Stage 5-6 比对+补搜
  [dispatch Opus Arbitrator via Agent tool]    ── Stage 7 仲裁

07_report_and_bqcode_json.py ─── Stage 8a 汇总产物
06_writeback_by_code.py       ── Stage 8b 写 _AI版.xlsx
```

## 适配新项目

脚本内路径都是**当前项目占位符**，用前需改：

| 变量 | 替换成 |
|---|---|
| `ROOT` | 你的项目根 |
| `SRC` | 源 xlsx 完整路径 |
| `DST` | 目标 _AI版 xlsx 完整路径 |
| `REPORT_DIR` | 报告输出目录（**与被修改的目标文件同目录**，如 `4 BQ\2026-7-29 第二版\temp\`） |
| `TEMP` | 中间文件目录 (`{PROJECT}/temp`) |
| `CONN` | MongoDB 连接串（默认 `mongodb://127.0.0.1:37117/cost_data_platform`） |
| `country` / `currency` | 过滤条件（如 `country="泰国"`, `currency="THB"`） |

01 脚本的 `EXCLUDE_SPECIALTY` 可按项目调（默认剔除"码头工程/间接费"）。

## 中间产物文件命名（约定）

| 文件 | 说明 |
|---|---|
| `temp/rate_pool_thb.json` | 池原始 (Stage 1) |
| `temp/v2_rate_pool_dedup.json` | 池去重后 (Stage 1) |
| `temp/boq_items.json` | 提取的 AI-todo BOQ 项 (Stage 1) |
| `temp/v2_glossary.json` | 术语表 + 家族触发词 (拷自 references/) |
| `temp/v2_auto_matched.json` | 规则自动分类的 skip/construction_only |
| `temp/v2_hard_items.json` | 需 Matcher 处理的疑难项 |
| `temp/v2_pkg_A_civil.json` / `_B_finish.json` / `_C_special.json` | 3 个 Matcher 包 |
| `temp/v2_matcher_A.json` / `_B.json` / `_C.json` | Matcher 输出 |
| `temp/v2_audit_input.json` | Auditor 输入 (no_match 按家族分组) |
| `temp/v2_auditor_out.json` | Auditor 输出 (redo/downgrade 记录) |
| `{REPORT_DIR}/V2_results_by_bqcode_{ts}.json` | 最终结果 (BQ Code 索引) |
| `{REPORT_DIR}/BQ匹配报告_V2_{ts}.html` | HTML 报告 |

## LLM Agent 派发（伪代码）

主 Orchestrator 在 Stage 4 后：

```python
# 通过 Agent 工具派发 3 个 Sonnet Matcher（并行）
for pkg in ['A_civil', 'B_finish', 'C_special']:
    dispatch_agent(
        subagent_type='general-purpose',
        model='sonnet',
        prompt=render_matcher_prompt(pkg),  # 见 references/matcher_prompt.md
        run_in_background=True,
    )

# 等 3 Matcher 全部完成通知后，收集 no_match 项按家族分组
build_audit_input()

# 派发 1 个 Sonnet Auditor（家族批搜）
dispatch_agent(
    subagent_type='general-purpose',
    model='sonnet',
    prompt=render_auditor_prompt(),  # 见 references/auditor_prompt.md
    run_in_background=True,
)
```

## 复用现有资产

- 术语表 + 家族触发词：`references/glossary_and_families.json`
- Matcher / Auditor 提示词模板：`references/matcher_prompt.md` / `auditor_prompt.md`
