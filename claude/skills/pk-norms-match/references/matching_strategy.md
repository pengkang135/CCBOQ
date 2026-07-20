# 定额匹配算法详解 v2.0

## 架构概览

```
BOQ条目 → Phase 0: 三过滤(量/单位/标题) → Phase 1: 上下文限定 → Phase 2: 关键词检索 → Phase 3: 七维评分 → Phase 4: 单位换算 → MatchResult
              ↑                                  ↑                        ↑                        ↑
         空零/LS/标题跳过                category_map.json     SQLite in-memory index    scoring_config.json
```

**Phase 0 (前置过滤)**: 三类项目直接跳过，不参与匹配，不写入结果：
- **工程量为空/0/NaN**: `true_qty is None or true_qty == 0 or math.isnan(true_qty)`
- **概念单位条目**: LS/lot/项/lump sum/allow 等，经 unit_mapping.json 标准化后 canonical 为 `项` 的跳过。这类是管理费/开办费，不套施工定额。
- **标题/层级标记项**: 名称包含 `【】`/`《》`/`{}` 等 BOQ 层级标记符号的标题行跳过，非实体工程项目。

在 `matcher.py`（Phase 0 前置检查）、`match_quota.py`（load_ast）和 `coordinator.py`（load_boq_from_excel）三处统一过滤。

核心类: `MultiDBMatcher` (SGA主库 + SGB参考库) → `SingleDBMatcher` (单库匹配引擎)

## Agent 协同架构

大清单(>200项)启用多Agent并行模式:

```
                     Coordinator (coordinator.py)
                     • 读取BOQ，分类到Agent
                     • fastexcel读取Excel
                     • agent_config.json驱动分类
                            │
     ┌──────────────────────┼──────────────────────┐
     │                      │                      │
Agent 土石方            Agent 现浇砼           Agent 附属
SGA Ch1 + SGB Ch1       SGA Ch4 + SGB Ch3      SGA Ch6 + SGB Ch5
~387 BOQ items          ~203 BOQ items          ~240 BOQ items
     │                      │                      │
     └──────────────────────┼──────────────────────┘
                            │
                     Merger (merge_results)
                     • 按BOQ行号合并
                     • 输出 merged_results.json
                            │
                     verify_match.py → 统计报告
                     write_results.py → Excel(含公式)
```

## Phase 3: 七维评分

| # | 维度 | 权重范围 | 说明 |
|---|------|---------|------|
| 1 | 关键词命中 | +30/个 | category关键词在定额search_text中出现 |
| 2 | 章节匹配 | +15 | 定额章节在target_chapters中 |
| 3 | 单位匹配 | +30 ~ -100 | 精确=+30, 兼容=+20, 类型不符=-30, 硬不匹配=-100 |
| 4 | 人材机一致性 | +40/-50 | BOQ含"砼"则定额cost_item必须有混凝土材料 |
| 5 | 工序内容匹配 | +20 | work_content工序动词与BOQ描述重叠 |
| 6 | 属性层级匹配 | +10 | attr_level与BOQ规格描述(C40, 直径等)匹配 |
| 7 | 排除规则 | -50/排除词 | 排除关键词扣分; 土石方人力定额惩罚-30 |

### 人材机结构分析 (维度4)

- BOQ含"砼/混凝土" → 定额cost_item必须含"混凝土/水泥/砂/石" (命中+40, 缺失-50)
- BOQ含"钢筋" → 定额cost_item必须含"钢筋/钢丝/型钢" (命中+40, 缺失-50)
- BOQ含"模板" → 定额cost_item必须含"模板/木/板材" (命中+20, 缺失-30)
- BOQ含"钢结构" → 定额cost_item必须含"型钢/钢板/钢管" (命中+30, 缺失-40)

## SGA + SGB 双库策略

1. SGA (34024条) 为主，优先匹配
2. SGA最佳得分 < fallback_threshold (30分) 时，追加SGB (1898条) 检索
3. SGB结果标记 db_source='sgb'，编号前缀 SGB-
4. 工序链组合用 + 连接: SGA40012+SGB10

## 检查修正 (Step 5)

自动检测: 得分偏低(<60), 单位矛盾, 人材机矛盾, 工序缺失, 多候选接近(<10分差), 工序链候选

修正文件格式:
```json
[
  {"row": 45, "action": "replace", "new_code": "SGA40012"},
  {"row": 67, "action": "force_no_match", "reason": "无对应水工定额"},
  {"row": 89, "action": "split", "codes": ["SGA40012", "SGA50010"], "operator": "+"}
]
```
