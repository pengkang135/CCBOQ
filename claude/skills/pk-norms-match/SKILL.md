---
name: pk-norms-match
description: "BOQ清单套定额：Claude语义理解匹配。构建定额池 → 拆分为Agent批次 → 并行派发子Agent做语义匹配 → 合并结果 → 写入Excel。适用于任何定额库和清单。"
---

# BOQ清单套定额

> **禁止用 Excel COM 处理表格**（BOQ 技能族硬规则）：不准启动 Excel 来读写、标记、插行、刷新或校验表格，`win32com` 和 COM 版 `excel` MCP 都不行 —— 它会抢占用户正开着的 Excel 实例、逼用户关文件等脚本、还比纯脚本慢。读值用 `fastexcel`，公式文本和保留格式改单元格用 `openpyxl`，插列/插行/搬 sheet/透视表这类结构操作走 zip+XML 层。这是**全局硬规则**（见 `~/.claude/CLAUDE.md` 的「Excel/AI 加速工具集」硬前置），不限 BOQ；BOQ 场景的具体替代做法见 [pk-boq/SKILL.md](../pk-boq/SKILL.md)。


将BOQ清单Excel中的项目逐一匹配到定额数据库，基于Claude语义理解而非关键词计数。适用于任何定额标准（港口、公路、房建、市政等），替换数据库路径和章节映射即可。

## 核心原则

- **匹配由 Claude 语义理解完成**，不使用脚本做关键词匹配。脚本只负责确定性操作：定额池构建、数据库查询、结果合并、Excel写入
- **定额编号默认填完整编码**：`{章节完整编码}.{定额子目编码}`（如 `A.01.02.001.BJ12.1-7`），用 `.` 连接。章节完整编码取 chapter.chap_Name 的编码部分（含册前缀，如 `A.01.02.001`），定额子目编码取 Norm.norm_Code 原值（如 `BJ12.1-7`）。构建定额池时直接拼接，Agent 原样输出
- **优先利用分类字段缩小搜索范围**：如果 BOQ 已带 Discipline/Category/Subcategory（由 pk-boq-classify 产出），直接用分类字段定位对应章节，在该章节内做精准匹配，不重新从全库搜索
- **定额库通过 `config/db_config.json` 配置，支持单库或多库联合检索**

## 整体流程

```
BOQ.xlsx → ⓿档位选档(册路由→候选池定位→冲突排除→打分) → ①构建定额池 → ②拆分Agent批次
                                                                     ↓
                                                        ③并行派发子Agent语义确认
                                                                     ↓
                                                             各Agent写入结果.txt
                                                                     ↓
                                                           ④合并脚本解析 → merged.json
                                                                     ↓
                                                          ⑤ write_results.py → Excel
                                                           ⑥ verify_match.py → 验证报告
```

本技能是 `pk-boq-ai-team` 8 阶段流水线模式 B 的实例化。不同环节由不同模型把关（设计 Opus / 执行 Haiku-Sonnet / 审核 Sonnet / 仲裁 Opus），换模型 = 独立信号，防止 AI 自己说服自己。

## 各阶段说明

### 阶段零：前期准备

**套定额只用企业定额 A~E 五册**，五册是唯一引用源（原 JTS/T 276 的 2524 个定额编号已
全部并入 D 册）。`config/db_config.json` 的 `enterprise_volumes` 段登记五册路径与来源。

| 册 | 专业 | 主候选池 | source_lib | 入口 |
|---|---|---:|---|---|
| A | 建筑装饰 | 5072 | **必填**（BJ12/BJ21/PK 三套） | 清单编码 |
| B | 通用安装 | 12410 | 可省（单一来源） | 清单编码，须上退 1~2 级 |
| C | 市政园林 | 13901 | **必填**（BJ12/BJ21 两套） | 清单编码 |
| D | 水运工程 | 3684 | 可省（JTS） | 清单编码 |
| E | 房屋修缮 | 13154 | 可省 | **必须给 chap_code**（无清单层） |

已移除 JTS(PDF schema) 路径，原因与影响见 `db_config.json` 的 `_removed_jts` 段。
`scripts/match_quota.py` 与 `matcher.py` 的 `MultiDBMatcher`/`SingleDBMatcher` 是该路径的
遗留入口，**五册模式下不再调用**；`matcher.py` 本身不能删 —— `coordinator.py` 与
`write_results.py` 仍用它的 `has_title_markers` / `CONCEPTUAL_UNITS_RAW` 两个工具函数。

### 阶段⓿：档位选档

**这是五册候选池的唯一来源**，不是可选的前置增强。

**要解决的问题**：同一章节内 6 条「机挖土方」文本相似度接近 100%，差别只在两个数字
（槽深 5m/13m/13m以外 × 运距 1km/15km），关键词分不开、向量更分不开，而选错档价格差
可达数倍。原七维评分的第 6 维「属性层级」是纯字符串包含且权重仅 `+10`——清单「槽深6m」
对定额「槽深13m以内」得 **0 分**，档位几乎不起作用。故档位选档取代它。

**做法**：册路由 → chapter 子树定位候选池（**不做文本检索**）→ 档位解析 → 冲突排除 →
打分排序，输出 ≤3 条候选交 Agent 确认。`dimension_prefilter.enabled=false` 仅用于故障
降级，那样 Agent 会拿到整个 chapter 子树（B 册最大 822 条）而非 3 条，风险显著上升。

```bash
cd E:/Code/Norms-AI && python src/dimensions/prefilter.py in.json -o out.json -V A --source-lib BJ12
```

输入 `[{"id","desc","ei_code" 或 "chap_code"}]`，输出每条的候选池、冲突排除清单（含排除理由）、
命中理由、warning。实测效果：13 条候选池排除 6 条后剩 3 条送 Agent。

**四条硬约束**（与 Norms-AI 档位模块一致，违反会选错）：

1. **册（volume）必须显式指定，不猜。**「土石方」在 A.01 房建 / C.01 市政 / D.04 水运
   都有同名 division，选错册后选档再准也无意义。`src/dimensions/route.py` 只给建议，
   `need_confirm=True` 时必须由人确认，不得取 candidates[0] 继续。
2. **A/C 册的 `source_lib` 必填**（A 册混有北京2012/北京2021/PK土建三套、C 册两套），
   B/D/E 册单来源可省略。别名 `BJ12`/`BJ21`/`JTS`/`PK`。
3. **入口须给清单编码或章节码**。候选池靠 chapter 子树定位，无入口时前置过滤会如实
   输出 `need_entry` 而非凭描述硬猜。E 册无清单层，必须给 `chap_code`。
4. **依赖派生表** `norm_dim` / `norm_dim_flag`。改过定额库或档位字典后须重建：
   `for v in A B C D E; do python src/dimensions/tag_norms.py -v $v && python src/dimensions/extract_residual.py -v $v; done`

输出的 `excluded` 清单应转达给 Agent 作为负面约束（这些已被档位冲突排除，不要再选），
`warnings`（如「清单未给开挖深度」）应提示人工确认，不要静默放行。

### 阶段一：构建定额池

由 matcher.py 的 `SingleDBMatcher._build_index()` 自动完成：从 SQLite 加载全部定额条目到内存索引，提取完整定额编号、名称、单位、章节归属、人材机、工序内容。

如果 BOQ 已带分类字段，在构建前按 Subcategory 裁剪章节范围，Agent 拿到的池从「全库几千条」缩小到「相关章节几十条」。

### 阶段二：拆分与派发

运行 `coordinator.py --mode split`：
- 按工程专业划分 Agent，每个 Agent 只携带相关章节的定额池
- 条目数上限 150/Agent，超限自动按 Subcategory 原子拆批
- 并发上限 5 个 Agent，超 5 时分波次执行
- 输出 dispatch JSON 到 `output/split/`

### 阶段三：并行语义匹配（核心）

每个子 Agent 拿到 BOQ 条目 + 裁剪后的定额池，按 `references/agent_prompt_template.md` 的结构化流程执行：

1. 利用分类字段定位章节（有分类则跳过「判断专业」步骤）
2. 检查工程量与单位（零工程量/概念单位跳过）
3. 在定额池中语义查找（理解工序实质，非关键词计数）
4. 单位兼容性验证（兼容→匹配；不兼容但内容相似→降级匹配黄色标记；都不行→无对应定额）
5. 结合定额子目内容深入判断（work_content、attr_level、cost_item）
6. 输出判定（五种类型：匹配/匹配[单位不兼容]/需其他章节/无对应定额/跳过）

Agent 直接写入结果 .txt 文件，防止上下文压缩丢失。

### 阶段四：合并结果

运行 `coordinator.py --mode merge`：
- 解析所有 Agent 的 .txt 结果文件
- 处理编码变体（CJK 异体字标准化）和格式差异
- 定额编号已在阶段一拼接为完整格式，直接原样使用
- 输出 `merged_semantic_final.json`

### 阶段五：验证与写入

验证分两层：
- **完整性检查（脚本层）**：每 Agent 输出行数 = 输入条目数，每行格式可解析
- **抽样审核（Agent 层）**：随机抽取 10% 条目逆向验证，通过率 <80% 的 Agent 全部标记为「需人工复核」（橙色背景）
- **Opus 仲裁（限量）**：只仲裁冲突/单位降级/疑似漏配项，不做常规匹配

写入：`python scripts/write_results.py merged.json source.xlsx -o output.xlsx`

只写 A列（定额编号）和 B列（定额名称）。未匹配项清空。`匹配[单位不兼容]` 行黄色背景标记。

## 职责边界（到此为止）

本技能**止于产出 `_matched.xlsx`**。往下不做，由人工处理：

- **不回写主清单**。目标清单的定额列在哪、要不要覆盖已有值、透视表怎么刷，都因文件而异，脚本猜不准。人工复核后自己搬。
- **不填定额工程量**。`write_results.py` 的换算公式与工程量列（L/M/N/O/P）是注释状态，注释原文「位置待确认」—— 列位置定不下来就不写，不留半对半错的数。
- `pk-norms-apply` 不是本技能的下游。它是独立的人工工具，只在明确要求"同步/定额回写"时才用，且它按列名定位（`Norm Code2` 等），与本技能硬编码的 A/B 列不通用。

### 打分：档位选档（已取代原七维评分）

五册的候选排序由档位选档产生（Norms-AI 的 `src/dimensions/matcher.py`）：

| 项 | 规则 |
|---|---|
| 冲突排除 | 施工方式/部位/深度档等不相容 → **直接踢出候选池**，不靠打分压低 |
| 数值档命中 | 权重高于枚举档（数值区间是定额分档主轴） |
| 最紧档 | 多档同时命中取上界最小者；仅在清单给点值时生效 |
| 区间匹配质量 | 上下界都相等=1.0、清单区间被包含=0.4~0.8、仅相交=0.25 |
| 章内标识 | 同章残余差分自举提取，按命中比例计分，`penalize` 级不硬排除 |
| 清单缺维度 | 降权 + warning，不静默放行 |
| 同分歧义 | 显式提示 top1 仅由编号排序决定 |

> **原七维评分（`config/scoring_config.json`）已停用**。它的第 6 维「属性层级」是纯字符串
> 包含且权重仅 `+10`：清单「槽深6m」对定额「槽深13m以内」得 0 分，而关键词命中是 `+30/个`,
> 档位几乎不起作用。该配置随 `scripts/matcher.py` 的评分部分一并成为遗留，不再参与五册流程。

## 匹配易错点（微调）

- **单位不兼容不放弃**：单位对不上时按常规尺寸换算后继续填（门宽×高、桩 π×r²、栏杆按长度、kg→t×0.001），换算系数填 Excel 公式（如 `=1.11*2.3`）而非数值，可追溯换算过程。
- **装配式优先**：预制混凝土构件先套装配式构件（如楼梯 BJ21.5-83），不是一般预制「其他构件」；但装配式柱梁、其他构件是空章节，须回退一般预制。
- **章节有定义 ≠ 有定额**：须确认章节下确有 Norm 子目。检测类钻芯/抗拔/勘探、白蚁防治处理等是空章节；白蚁防治 L.b.01.001 实际挂在防腐涂料 12.03.003 下，按实际挂靠用。
- **主材未计价标注**：主材/设备/预制构件在价格包中常未计价，rate 偏低属正常，Reason 标注「主材未计价」，勿当异常价。

## 混凝土标号换算（定额换算）

清单同一个构件会按标号分列（C30 / C35 / C50…），而定额子目只按构件形状分（矩形柱、直形墙…），消耗量里写死一个标号（北京定额典型是 C30）。**匹配阶段不做标号区分** —— 同一子目被多个标号引用是正常的，不要为此另找子目；标号换算在导出阶段统一做。

- **口径**：清单里的欧标写法 `C50/60`、`C35/45`、`C28/35` 取**第一个数**（圆柱体强度，对齐中国 C 标号）→ `C50 / C35 / C28`。
- **换什么**：消耗量里的混凝土（`预拌混凝土 / 预拌水下混凝土 / 预拌豆石混凝土 / 商砼 / 混凝土 Cxx`，单位 m³；砌块、垫块、桩头等排除）连同 `同混凝土等级砂浆` 一起换成目标标号；**原行保留**，另追加 `编号+c50`、名称 `…换C50`、工程量取该标号的清单量。
- **生成映射**（前置脚本，产出 `--concrete-map` 的输入）：
  ```bash
  python scripts/build_concrete_map.py UniqueShot.xlsx --sheet UniqueShot \
      --code-col CODE --desc-col CleanDescription --qty-col "求和项:Qty" \
      --code-map code_map.json -o concrete_map.json
  ```
  输出 `{"A.04.03.006.BJ21.5-10": [{"grade":"35","qty":7742.9},{"grade":"50","qty":5676.0}]}`。
  **必须喂换算前的表**（编号不带 `cXX` 后缀），否则会叠加换算（脚本会打 WARNING）。跨册零散编号用 `--code-map` 指定完整编号（如 `{"JTS.SGB81":"D.05.02.001.SGB81"}`）。
- **落地到综合单价**：交给 `pk-norms-export --concrete-map concrete_map.json`，综合单价多出换算行，人材机自动补出目标标号的混凝土/砂浆行（库里没基价的标 `待询价`、单价留空待填）。
- **编号一致性**：换算后要把清单侧（UniqueShot）的 `CODE/Name` 同步为换算后的编号/名称（带 `cXX` 后缀），保证与综合单价逐条对得上；`Rate` 等待询价单价填好后按「原基价 − 原混凝土/砂浆金额 + 新混凝土/砂浆金额」回算。

## 关键约束

| 约束 | 值 | 原因 |
|------|-----|------|
| 每 Agent 条目上限 | 150 | 注意力衰减 |
| 并发 Agent 上限 | 5 | 系统资源 + API 限速 |
| 得分阈值 | 30 | 低于此分标记为「得分不足」 |

## 适配新定额库

新库须是**企业定额 schema**（有 `Norm` 表）：登记到 `config/db_config.json` 的
`enterprise_volumes` 段，并在 Norms-AI 侧的 `src/dimensions/volumes.json` 注册该册
（结构差异如 chap_code 是否带册前缀、有无清单层，都集中在那里）。

1. 更新 `config/db_config.json`：数据库路径、来源别名
2. 更新 `config/agent_config.json`：章节分配到 Agent 的映射、分类关键词
3. 更新 `data/category_map.json`：英文关键词→中文检索词映射
4. matcher.py、coordinator.py、write_results.py 无需改动

## 文件结构

| 文件 | 用途 |
|------|------|
| `SKILL.md` | 本文件 — 工作流概述 |
| `references/agent_prompt_template.md` | 子 Agent 语义匹配提示词模板 |
| `scripts/coordinator.py` | BOQ加载、分类、拆分、合并调度 |
| `scripts/verify_match.py` | 验证报告（统计+抽样+得分分布） |
| `scripts/write_results.py` | Excel 回写（定额编号+名称+公式） |
| `scripts/build_concrete_map.py` | 混凝土标号换算映射（套定额前置，产 `--concrete-map` 输入） |
| `config/db_config.json` | 五册登记 + 档位选档配置 |
| `config/agent_config.json` | Agent 分派（`volume_agents` 按册分组） |
| `config/unit_mapping.json` | 单位标准化映射 |
| `data/category_map.json` | 英文关键词→中文检索词映射（188 条目） |

**候选池与打分不在本技能内**，由 Norms-AI 的档位模块提供：

| 文件 | 用途 |
|------|------|
| `E:/Code/Norms-AI/src/dimensions/prefilter.py` | 批量入口：BOQ 条目 → 候选池 + 排除清单 + warning |
| `E:/Code/Norms-AI/src/dimensions/route.py` | 册路由（提示 + 冲突拦截） |
| `E:/Code/Norms-AI/src/dimensions/README.md` | 设计约束 16 条、维护提醒、评测口径 |

**JTS 路径遗留（五册模式不调用）**：

| 文件 | 状态 |
|------|------|
| `scripts/matcher.py` | 评分部分停用；但 `has_title_markers`/`CONCEPTUAL_UNITS_RAW` 仍被 coordinator 与 write_results 使用，**不能删** |
| `scripts/match_quota.py` | 停用（其角色由 `prefilter.py` 取代） |
| `config/scoring_config.json` | 停用（七维评分权重） |
