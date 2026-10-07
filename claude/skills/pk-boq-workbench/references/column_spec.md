# 报价工作台布局规格

报价工作台的工作簿结构（入口 `build_bench.py`，另一条路 `build_workbook.py`）。脚本不硬编码列位 —— 公式和样式都从 `pivot_template.xlsx` 的样板行实时提取，本文件是人读版规格。改模板不用改脚本，但改完要按末节的清单验一遍。

**本文列出的列字母是模板当前布局的快照，不是契约。** 模板改过好几版（`RFQPlan` → `CostSummary`、「入价」→「成本」、`合并报表` → `CombineBQ`、`Quantity` → `Qty`、`AI Rate` → `Norm/Ref Rate`、分组标签改成 `EXPORT`/`COST`/`AI`/`SUBCONTRACTOR`），每次改完这里都要重新对一遍。脚本和交付检查都从模板实时读，唯一事实源是 `pivot_template.xlsx` 本身。

## 装配方式：原始清单区只增不改

模板的 CombineBQ 分两段：**A 列 `Main Key` 是键列，B 列 `No.` 起是原始清单区**，`F` 列（`Factor`）开始到 `AI` 列（最后一个 `Amount`）是**报价脚手架**，由 r1 的四个分组标签划分成 EXPORT / COST / AI / SUBCONTRACTOR。

```
[Main Key][ 源清单原有列 ][ ←—————————— 整块插入的脚手架 ——————————→ ]
   左插        只增不改        EXPORT | COST |      AI      | SUBCONTRACTOR
                              Factor  Labor   Discipline..    Labor
                              Labor   ..      Element         ..
                              ..      Amount  BQ KEY          Amount
                              Amount          CleanDescription
                                              Norm/Ref Rate+Amount
```

分区边界靠 **r1 的分组标签**认，不是列字母。下面列布局表里的列字母只是当前模板的快照，用来对照核查，不能拿去写进代码或按它定位。

装配就是在原清单上**插入**列，不是把原清单的数据搬进模板：

- 原始清单区里已有的列、格式、公式、图片、drawing 一律保留，一个单元格都不改写；
- `Main Key` 插在最左，脚手架整块追加在原清单**最右侧**；
- 脚手架按**模板列序整块复刻**，不按列名挑列 —— `Labor` / `Material` / `Equipment` / `Rate` / `Amount` 在三组里各出现一次，按列名建字典只活得下来一个，会有一整组表头丢名；
- 组之间的空隔列（`L` / `AC` / `AD`）一起复刻，少了它们分组标签跨度和透视缓存字段序号都会错位；
- 公式里对源列（描述 / 单位 / 工程量）的引用，重定向到原清单实际的那几列，不假定 C/D/E。

**只有一种情形。** 原来分「原清单自带脚手架」和「原清单只到 Quantity」两种做法，现在统一成一律整块插入 —— 源清单只需提供 `No.` / `Description` / `Unit` / `Qty`（`Quantity` 也认，见 `layout.ALIASES`）。源清单本身已经带报价列时，脚手架仍然追加在它右侧，不复用它那几列。

## 工作簿结构

| Sheet | 性质 | 作用 |
|-------|------|------|
| CombineBQ | 数据主表 | Main Key + 源清单 + 四组脚手架（含分类五列、两个键列、Norm/Ref 套价列） |
| CostSummary | 透视表 | Discipline → SortKey → Category，各口径 Amount 横向对比 |
| MainQty | 透视表 | 加 Subcategory / Unit，出主要工程量汇总 |
| UniqueBQ | 透视表 | 到 Element / CleanDescription / Unit / BQ KEY 粒度，右侧 VLOOKUP 回引快照 |
| UniqueShot | 快照工作台 | 套价的实际作业面 |

三个透视表共用一个 pivotCache，数据源是定义名称「分类定义区」。装配时置 `refreshOnLoad="1"`，打开文件即按实际数据刷新。

`table1.xml`（原 `表1`）在模板这一版已经删掉，透视源从 table 改成了定义名称。

## CombineBQ 行结构

| 行 | 内容 | 生成方式 |
|----|------|---------|
| 1 | 分组标签：`EXPORT`（F 列）/ `COST`（M）/ `AI`（R）/ `SUBCONTRACTOR`（AE），各落在该组首列上方 | 装配时按模板复刻 |
| 2 | 放大系数行：`G2`/`H2`/`I2` = 1.23（EXPORT 人材机对 COST 的系数）、`AE2` = 1.05、`AG2` = 0.07 | 从模板继承，**值是项目相关的，用前必须确认** |
| 3 | 表头 | 按模板复刻 |
| 4 .. N | 数据行 | 第 4 行就是数据行（`Main Key` / `BQ KEY` 在这行已有公式），`layout.DATA_START = 4` |
| N+1 | 【TOTAL】 | 模板 r68；`build_workbook.py` 按实际数据范围重算 SUBTOTAL / SUMPRODUCT |

模板第 2 行的 `X2`（CleanDescription）也带公式，在表头行上方，取样板时会跳过（`col_at` 只扫表头行之后）。

## 列布局

下表的列字母是**当前模板的快照，仅供对照核查**，任何代码和操作都要按表头名（脚手架内按模板列序）定位。

| 列 | 表头 | 组 | 类型 | 内容 |
|----|------|----|------|------|
| A | Main Key | — | 公式 | `LET` 追溯最近的 `【】《》{}` 三级标题 + 描述/单位哈希 |
| B | No. | — | 源 | 源清单原编号 |
| C | Description | — | 源 | 源清单名称，含层级符号 |
| D | Unit | — | 源 | 源清单单位 |
| E | Qty | — | 源 | 源清单工程量（早先叫 `Quantity`，两种都认） |
| F | Factor | EXPORT | 人工 | 调整系数，参与 G-I 计算 |
| G-I | Labor / Material / Equipment | EXPORT | 公式 | `=PRODUCT(对应 COST 列 × 第2行系数, $F)` |
| J | Rate | EXPORT | 人工 | |
| K | Amount | EXPORT | 公式 | `=J×$E` |
| L | — | — | 空隔列 | |
| M-O | Labor / Material / Equipment | COST | 公式/人工 | `M=P×75%`，N/O 模板留空 |
| P | Rate | COST | 人工 | |
| Q | Amount | COST | 公式 | `=P×$E` |
| R | Discipline | AI | ai | 定额库分册英文全名（A=建筑装饰 / B=通用安装 / C=市政园林 / D=水运工程 / E=房屋修缮） |
| S | SortKey | AI | ai | 定额库 `division.code`（A.04、B.10），PRELIM 行填 `PRELIM` |
| T | Category | AI | ai | 定额库 L1 `division.name` 闭词表 |
| U | Subcategory | AI | ai | 定额库 L2 `sub_division.name` 闭词表 |
| V | Element | AI | ai | 定额库 L3 `enterprise_item` / `chapter` 闭词表 |
| W | BQ KEY | AI | 公式 | `SortKey`（S 列）+ `|` + `CleanDescription`（X 列）的哈希，形如 `A.01|64658`。**套价链路的连接键，依赖分类已填** |
| X | CleanDescription | AI | 公式 | 去掉编号前缀和末尾句号，`Qty<=0` 时返回空 |
| Y | Norm Rate | AI | 公式 | `VLOOKUP(W, UniqueShot!F:AJ, COLUMN(UniqueShot!AI:AI)-COLUMN(UniqueShot!F:F)+1, FALSE)` —— 偏移量用 `COLUMN()` 算，不写死 |
| Z | Norm Amount | AI | 公式 | `=Y×$E` |
| AA | Ref Rate | AI | 公式 | `VLOOKUP(W, UniqueShot!F:M, 5, FALSE)` —— **偏移量 5 写死**，快照页 `BQ KEY` 与该列之间增删列会断链 |
| AB | Ref Amount | AI | 公式 | `=AA×$E` |
| AC, AD | — | — | 空隔列 | |
| AE-AG | Labor / Material / Equipment | SUBCONTRACTOR | 人工 | |
| AH | Rate | SUBCONTRACTOR | 人工 | |
| AI | Amount | SUBCONTRACTOR | 公式 | `=AH×$E` |

`AI Rate` / `AI Amount` 已被 `Norm Rate`/`Norm Amount`（套定额结果）和 `Ref Rate`/`Ref Amount`（参考报价库）取代；`Misc` 和 `占比` 两列随本次改版删除。分组标签是 `EXPORT` / `COST` / `SUBCONTRACTOR` 这种通用名，**不再带分包商名字**，按分包商名找列的代码一律失效。

## 行类型与公式矩阵

行类型按 Description 的层级符号判定，与 `pk-boq-hierarchy` 一致：

| 类型 | 判据 | 公式列 |
|------|------|--------|
| L1 | 以 `【` 开头 | X + K、Q、AB、AI（`XMATCH` 找下一个 `【`，跨度 5000，`SUBTOTAL` 求和） |
| L2 | 以 `《` 开头 | 同上，改用 `跨度 500` 找下一个标题 |
| L3 / 说明文字 | 以 `{` 开头，或无量的普通行 | 只有 X（CleanDescription） |
| 明细 | 其余且 `Qty>0` | A、W、X + G-I、K、M、Q、Y、Z、AA、AB、AI |
| TOTAL | 描述为 `【TOTAL】` | K、Q、AB、AE、AI（`SUBTOTAL(9,…)` / `SUMPRODUCT`） |

标题行**没有** `Main Key` / `BQ KEY` 公式 —— 只有明细行有。交付检查因此只在明细行上判这两列的公式覆盖率。

`Norm Amount`（Z 列）在 L1 / L2 标题行没有汇总公式，只有 K / Q / AB / AI 四列有。

## 样板行机制

`build_workbook.py` 从模板 sheetData 里按 **Description 的层级标记**认样板行：

| 描述 | 判为 |
|------|------|
| `【TOTAL】` | TOTAL |
| `【…】` | L1 |
| `《…》` | L2 |
| `{…}` | L3 |
| 其余且公式列含 Norm/Ref 套价列 | 明细 |
| 其余且不含套价列 | L3（无量空壳行） |
| 描述为空 | 跳过 |

**原来靠公式列组合指纹认，模板这一版行不通了**：删掉 `占比` 列之后 L1 和 L2 的公式指纹一模一样（都是 X + K/Q/AB/AI），TOTAL 行跟它们也撞（三者都是「无键列 + 有 Amount」）。描述标记本来就是这几类行的语义来源，反而更稳。

描述为空的行必须跳过 —— 模板第 4 行只有键列公式、没有描述，认成 L3 会把它当空壳样板用，比 `{…}` 那种真 L3 行少了 CleanDescription 公式。

明细行会有多个候选，用 `item_score` 打分取最高：某一组人材机（`Labor`/`Material`/`Equipment`）齐全的加 100 分，再加公式列总数。

取到样板后，公式里等于样板行号的行号换成哨兵，生成时填实际行号；指向 TOTAL 行的绝对引用换成 TOTAL 哨兵，单独填新的 TOTAL 行号。

模板里的 shared formula 会展开成独立公式，**展开时按列差平移相对引用** —— shared formula 的语义本来就是相对偏移，只改行号会让 K 列拿到 J 列的公式。平移只作用于引号外的片段，正则字面量不受影响。

## UniqueShot 结构

套价的作业面。表头在第 4 行，第 1 行和第 3 行是分区标题：

| 列区 | 分区 | 字段 |
|------|------|------|
| A-I | 键区 | Discipline / SortKey / Category / Subcategory / Element / BQ KEY / CleanDescription / Unit / 求和项:Qty |
| N-P | 套价（r1 `AI RATE`） | Name / Unit / Rate |
| Q-T | Manual Search | Name / Unit / Rate / Conv Formula |
| U-AC | AI Search | Name / Unit / Unit Conv Formula / Rate / Curr / Ref Project / Supplier / Date / Reason |
| AE-.. | Norm-AI（r1 `AI NORM`） | CODE / Name / … |

CombineBQ 的两条回引：

- `Norm Rate`（Y 列）→ `VLOOKUP(BQ KEY, UniqueShot!F:AJ, COLUMN(UniqueShot!AI:AI)-COLUMN(UniqueShot!F:F)+1, FALSE)`。偏移量用 `COLUMN()` 算出来，**增删列不会断**。
- `Ref Rate`（AA 列）→ `VLOOKUP(BQ KEY, UniqueShot!F:M, 5, FALSE)`。偏移量 **5 写死在公式里**，快照页 `BQ KEY`（F 列）与目标列之间增删任何一列都会打断回流 —— 改快照页布局时必须同步改它。

## 模板已知问题

（以下是模板里公式的字面内容，用列字母指位置，不是让代码按列字母定位。）

**L1 行的 `Ref Amount`（AB 列）汇总的是 `$Q:$Q`**，也就是 COST 组的 `Amount`，不是它自己的 `AB:AB`。L2 行（`AB:AB`）和 TOTAL 行（`AB5:AB67`）都是对的，只有 L1 这一处。结果是 L1 小计的 Ref 金额等于 COST 金额。

这是改版前那个同类问题的延续（原来记的是「L1 行 `AI Amount` 引用 `$U:$U`」）—— 列位重排时 Excel 把引用跟着调成了 `$Q`，错的相对关系保留了下来。修的时候连带确认 L1 行 K / Q / AI 三列（这三列目前分别正确引用 `K:K` / `$Q:$Q` / `AI:AI`）。

`Norm Amount`（Z 列）在 L1 / L2 标题行没有汇总公式。是有意留空还是漏加，需要确认。

## 模板维护规则

`pivot_template.xlsx` 是只读资产。用 Excel 打开再保存会重写 sheet XML，还会带进外部链接和垃圾定义名称 —— 上一次改版就引入了指向 `摘录清单项_工作台_V5.xlsx` 的 externalLink 和 153 条 `[1]综合单价` 的 VLOOKUP，得靠 `references/temp/scripts/fix_template.py` 清掉。确需改布局：

1. 改完先跑 `python references/temp/scripts/fix_template.py --dry-run` 看要清什么，再去掉 `--dry-run` 执行
2. 在 Excel 里刷新透视表重存一次（`cacheFields` 只有 Excel 能重建），关掉 Excel 释放文件锁
3. 跑 `python temp/scripts/regression.py`，三种源清单形态都要过
4. 跑 `python scripts/verify_workbook.py <产物> --stage build` 复核
5. 模板里各类行至少各留一行（L1 / L2 / L3 / 有量明细 / TOTAL），否则样板提取会报缺样板
6. 回来更新本文的列布局表和 `column_template.json`

**不要用 Excel COM 验证产物**（全局硬规则，见 `~/.claude/CLAUDE.md`）—— 用 `regression.py` 和 `verify_workbook.py` 脚本核对。

改 sheet 名或分组名时，记得 grep 一遍 `scripts/` 和 `references/`，以及 `pk-boq-classify/scripts/`（那边有 `layout.py` 的迁移期副本和自己的 `--sheet` 默认值）—— 写死这些名字的地方会当场失效。

模板必须保留的部件：`metadata.xml`（动态数组的 `cm="1"` 元数据指向它）、三个 `pivotTables/` 和 `pivotCache/`。`tables/table1.xml` 这一版已删（透视源改成定义名称「分类定义区」）。openpyxl 全量往返会重写 pivotTable、丢 drawing 和 media，所以脚本一律走 zip/XML 层。

## 踩过的坑

- **公式双重转义**：从模板 XML 取出的公式已经是转义态（`&amp;` `&gt;`），写回时再 escape 一次会变成 `&amp;amp;`，Excel 打开即报损坏且不说原因。只有单元格的值需要转义，公式不要。
- **calcChain 断链**：行数一变 calcChain 就对不上，要丢掉。但必须三处同时清：部件本身、`[Content_Types].xml` 的 Override、`workbook.xml.rels` 的 Relationship。只删部件会留断链，同样是"文件损坏"。
- **table 只剩表头**：清空数据行时若 sheet 上还挂着 table，ref 必须覆盖表头加至少一行 —— 只有表头的表 Excel 判定损坏，所以 `clear_rows_from` 会留一个空行。模板这一版已经没有 table（透视源改成定义名称），但清行逻辑保留了这个行为。
- **shared 宿主属性**：样板行的 `t="shared" ref="C5:C43"` 带的是模板自己的范围，行数一变就对不上，展开成独立公式后要整个丢掉。
- **动态数组公式读不到**：A/B 列是动态数组公式，openpyxl 返回 `ArrayFormula` 对象而不是 `=` 开头的字符串。用 `startswith("=")` 判断会误报"没有公式"，取 `.text`。
- **净化会删掉「分类定义区」**：`xlsx-purge` 的在用判定只扫 sheet 公式和条件格式，不扫 pivotCache 的 `worksheetSource`，所以会把这个定义名称当未使用删掉。`build_workbook.py` 每次都重建它，不受影响；但手工净化后别忘了它已经没了。
