---
name: stock-analysis
description: |
  上市公司财务分析与估值研究。输入公司名和中间格式目录路径，自动完成三阶段分析：
  财报数据深度分析 → 网络调研（券商研报/行业分析/雪球讨论/新闻公告，使用 kimi-webbridge 控制真实浏览器）→ 综合研判并输出两份报告（综合专题报告 + 估值分析报告）。
  触发场景：(1) "分析XX公司" "给XX做个分析" "综合评价XX"；(2) "给XX估值" "XX估值分析"；(3) 任何对上市公司的投研需求。
---

# 上市公司财务分析与估值研究

## 管道概览

```
原始财报（中间格式MD）──→ Phase 1 财报分析 ──→ Phase 2 网络调研 ──→ Phase 3 综合研判
                                    │                      │                    │
                                    ▼                      ▼                    ▼
                              财务数据摘要           调研日志+截图      {公司}_综合专题报告.md
                                                                          {公司}_估值分析.md
```

## 前置条件

1. **公司名称**（如"博敏电子"）
2. **中间格式目录路径**（如 `F:\BaiduSyncdisk\13.投资\财报\半导体\_中间格式\博敏电子\`）
3. **kimi-webbridge 可用**（用于 Phase 2 网络调研）

## Phase 0: 环境准备

1. 确认中间格式目录存在且包含必备文件（5张财务表MD + 至少1份年报MD）
2. 运行 `~/.kimi-webbridge/bin/kimi-webbridge status` 确认健康
3. 确认公司名/股票代码

## Phase 1: 财报分析

**目标**：从中间格式 MD 中提取所有财务数据，结构化分析公司经营状况。

**数据源**：
- `{公司}_主要财务指标.md` — 核心指标时间序列
- `{公司}_利润表.md` — 完整利润表
- `{公司}_现金流量表.md` — 现金流明细
- `{公司}_资产负债表.md` — 资产负债结构
- `{公司}_自定义指标.md` — 自定义比率
- `{公司}_2025年度报告.md` — 年报全文文本
- `{公司}_2025半年度报告.md` — 半年报全文
- `{公司}_2026Q1报告.md` — 最新季报全文

**执行步骤**：

1. 运行解析脚本提取结构化数据：
```bash
python "C:\Users\Kevin\.claude\skills\stock-analysis\scripts\parse_financial_statements.py" \
  "{中间格式目录}" --company "{公司名}"
```
输出 `{公司}_financial_data.json`，含指标时间序列和年报文本摘要。

2. 阅读解析结果，重点分析：
   - **成长性**：近5年营收/净利润趋势、同比增长率、CAGR
   - **盈利能力**：毛利率、净利率、ROE变化趋势及驱动因素
   - **财务安全**：资产负债率、流动比率、有息负债率、经营现金流覆盖
   - **盈利质量**：扣非 vs 净利润差异、经营现金流/净利润比值
   - **运营效率**：周转指标、费用率趋势

3. 从年报文本中提取管理层讨论、竞争力分析、风险因素、研发投入等关键信息。

4. 生成财务分析摘要（结构化要点，用于 Phase 3 综合研判）。

> **详细方法论**：见 [references/financial-analysis.md](references/financial-analysis.md)
> **财务指标速查**：见 [references/financial-ratios-reference.md](references/financial-ratios-reference.md)

## Phase 2: 网络调研

**目标**：通过 kimi-webbridge 控制用户真实浏览器（保留登录态），搜索收集外部信息。

**调研清单（按优先级）**：

| # | 类型 | 目标网站 | 搜索关键词 |
|---|------|---------|-----------|
| 1 | 券商研报 | 东方财富研报中心 | `{公司名}` |
| 2 | 行业分析 | 搜索引擎/行业网站 | `{行业} 行业分析报告 2026` |
| 3 | 雪球讨论 | 雪球个股页 | `{股票代码}` |
| 4 | 新闻公告 | 巨潮资讯/搜索引擎 | `{公司名} 公告 2026` |

**执行流程**：

1. 健康检查 → 创建独立 session `stock-research-{公司拼音}`
2. 按优先级依次搜索，每步用 `snapshot` 读取页面内容，`evaluate` 提取关键数据
3. 记录所有信息来源（URL + 日期 + 摘要）到调研日志
4. 关键页面截图保存到 `{中间格式目录}/_research_screenshots/`
5. 调研结束调用 `close_session` 清理标签页

> **完整调研流程与 kimi-webbridge 调用规范**：见 [references/web-research-workflow.md](references/web-research-workflow.md)

## Phase 3: 综合研判与报告生成

**目标**：整合 Phase 1 财务数据 + Phase 2 外部信息，生成两份结构化报告。

**研判步骤**：

1. **交叉验证**：将财报事实与研报预测、市场情绪对照，标注一致性
2. **多空因素分析**：列出利好/利空因素，按确定性和影响程度排优先级
3. **估值分析**：
   - 历史PE/PB区间（从财务数据计算）
   - 同业估值对比（从调研获取可比公司数据）
   - DCF估值（如数据充分）
   - 股息估值（如公司有稳定分红历史）
4. **撰写报告**：按模板输出两份报告

> **综合研判方法论**：见 [references/synthesis-framework.md](references/synthesis-framework.md)
> **估值方法详解**：见 [references/valuation-methods.md](references/valuation-methods.md)

### Report 1: 综合专题报告

保存为 `{中间格式目录}/{公司}_综合专题报告.md`

报告结构：
1. 公司概况与行业地位
2. 核心技术优势与壁垒
3. 财务健康度分析（成长性/盈利能力/运营效率/财务安全/盈利质量）
4. 未来增长前景
5. 风险与挑战
6. 当前估值水平概述
7. 市场情绪与关注焦点
8. 综合结论

> **完整模板**：见 [references/report-template-comprehensive.md](references/report-template-comprehensive.md)

### Report 2: 估值分析报告

保存为 `{中间格式目录}/{公司}_估值分析.md`

报告结构：
1. 历史估值区间（PE/PB/PS Band）
2. 同业估值对比
3. 绝对估值参考（DCF + 敏感性分析 + 情景分析）
4. 股息估值（如适用）
5. 综合估值结论（多方法加权 + 合理价格区间 + 安全边际）

> **完整模板**：见 [references/report-template-valuation.md](references/report-template-valuation.md)

## 验证检查清单

每份报告生成后必须确认：

- [ ] 财务数据经二次核对（与原始报表交叉验证，至少抽查3个关键指标）
- [ ] 所有网络信息来源均已记录URL和日期
- [ ] 正面因素与负面因素均有充分呈现（至少各3条）
- [ ] 不确定性已明确标注（`[确定性高]` / `[需要跟踪]` / `[推测]` / `[分歧大]`）
- [ ] 估值多方法覆盖（至少3种方法）
- [ ] 敏感性分析覆盖合理参数范围
- [ ] 免责声明已添加

## 跨技能引用

| 技能 | 用途 | 阶段 |
|------|------|------|
| kimi-webbridge | 浏览器控制、网页浏览搜索、截图 | Phase 2 |
| document-ingest | 如遇新增原始PDF/XLS需转换为中间格式 | Phase 1(可选) |
| deep-research | 深度多源研究（可选增强 Phase 2/3） | Phase 2+3(可选) |

## 输出位置

所有输出文件保存在**中间格式目录**（即输入目录）下：

```
{中间格式目录}/
├── {公司}_综合专题报告.md      ← Report 1
├── {公司}_估值分析.md          ← Report 2
├── {公司}_financial_data.json  ← Phase 1 中间产物
├── {公司}_research_log.md      ← Phase 2 调研日志
└── _research_screenshots/      ← Phase 2 截图
```
