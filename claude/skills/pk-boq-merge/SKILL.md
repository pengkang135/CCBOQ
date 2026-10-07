---
name: pk-boq-merge
description: "BOQ 清单合并与预处理。多源清单归一化合并、按关键字提取子清单、清理外部链接。分部分项清单表（描述+单位+工程量）和开办费/暂列金等总价表（描述+金额）都合并，汇总表按 sheet 名排除。合并前先创建临时副本保护原文件，检测隐藏行并征求用户确认。合并时保留原始列结构、表头和单元格标注格式（背景色/字体色/加粗），仅注入 L1【sheet名】分组标记，不做列转换。当用户需要合并BOQ、整理清单、归一化、提取子清单、清理Excel外部链接、结构化清单、或在合并前探测Excel结构时，必须使用此技能。即使只提到'整理一下这个xlsx'或'把这个BOQ处理一下'这类模糊描述也应触发。"
license: Proprietary. LICENSE.txt has complete terms
---

# PK BOQ — 合并

> **禁止用 Excel COM 处理表格**（BOQ 技能族硬规则）：不准启动 Excel 来读写、标记、插行、刷新或校验表格，`win32com` 和 COM 版 `excel` MCP 都不行 —— 它会抢占用户正开着的 Excel 实例、逼用户关文件等脚本、还比纯脚本慢。读值用 `fastexcel`，公式文本和保留格式改单元格用 `openpyxl`，插列/插行/搬 sheet/透视表这类结构操作走 zip+XML 层。这是**全局硬规则**（见 `~/.claude/CLAUDE.md` 的「Excel/AI 加速工具集」硬前置），不限 BOQ；BOQ 场景的具体替代做法见 [pk-boq/SKILL.md](../pk-boq/SKILL.md)。


> 找出有工程量清单的分部分项清单表（有描述+单位+工程量的 sheet），原样堆叠合并，**连人工标注底色一起搬过来**，注入 L1【sheet名】标记来源。L2 及以上层级由下游 `pk-boq-hierarchy` 技能负责。
> 完整工作流拓扑 → [references/merge_workflow_topology.md](references/merge_workflow_topology.md)

## 合并流程

```
源 xlsx → 临时副本(temp/) → 清外部链接 → 清单表识别 → 隐藏行检测(询问用户) → 读值+读样式 → 堆叠+L1标记 → 自检 → 输出 Merge xlsx → pk-boq-hierarchy 技能
```

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1. 临时副本 | `shutil.copy2` → `temp/_merge_temp_{name}.xlsx` | 所有操作在副本上进行，保护原文件不被修改 |
| 2. 清外部链接 | `xlsx_purge.py --mode links` 处理副本 | 防止 Excel 崩溃，ZIP/XML 清理 + 外链公式转值 |
| 3. 清单表识别 | fastexcel 扫描候选 sheet，分 measured（描述+单位+工程量）和 lumpsum（描述+金额）两类 | 分部分项和开办费/暂列金都纳入，只排除汇总表（靠 sheet 名） |
| 4. 隐藏行检测 | `openpyxl` 检测各 sheet 隐藏行 | 如有隐藏行，停下来询问用户是否删除。**删除后行号全变，必须重新识别** |
| 5. 表头对齐 | 以最宽 sheet 为模板，**按表头名称**匹配各 sheet 列位置 | 窄 sheet 缺 Specifications 列时仍能对齐 Unit/Qty/Rate，不按列号硬编码 |
| 6. 读值 + 读样式 | fastexcel 读值；`openpyxl(read_only)` 读每格底色/字体色/加粗 | 两者行号必须对齐，所以 fastexcel 一律 `header_row=None` |
| 7. 堆叠输出 | xlsxwriter 写出，格式走缓存池（同样式复用同一个 Format 对象） | 样式随值走同一套列映射，窄表颜色也落在正确列 |
| 8. 自检验证 | 分段**工程量 + 金额**双重比对 | 源侧按各表自己的列直读、输出侧读交付文件，逐 sheet + 总计核对，不通过则退出 |
| 9. 层级化 | **路由到 `pk-boq-hierarchy` 技能** | 五级 NRM 层级（L1-L4+Note+outline level）+ AI 审查 |

实测 7500 行 5.5 秒、30000 行 20 秒，与不保留格式的旧版持平（读样式 20000 格仅 0.24 秒，不是瓶颈）。

## 路由

| 需求 | 工具 | 说明 |
|------|------|------|
| 合并/归一化 | `scripts/merge_boq.py` | fastexcel 读值 + openpyxl 读样式 + xlsxwriter 输出，保留标注格式与列结构，注入 L1【sheet名】标记 |
| **→ 五级层级化** | **`pk-boq-hierarchy` 技能** | **合并后必须路由到此技能**，施加完整 NRM 5 级，含 AI 审查管道 |
| 清除外部链接 | `xlsx-purge` 技能的 `xlsx_purge.py --mode links` | ZIP/XML 清理 + 逐格值比对验证 |
| 关键字提取 | `extract_boq_by_keyword.py` | 保留层级关系 |

> CLI 参数 → [../pk-boq/references/scripts_reference.md](../pk-boq/references/scripts_reference.md)

## 合并后强制路由

**合并脚本完成后，必须立即调用 `pk-boq-hierarchy` 技能处理合并输出文件。**

```
merge_boq.py → (日期 Merge)原文件名.xlsx → pk-boq-hierarchy 技能（就地层级化，不另生成文件）
```

## 输出格式

- **列结构**：与最宽清单表的原始列完全一致（表头名称、列数、列序全部原样保留），窄表按表头名称对齐，开办费的金额列归并到模板的总价列
- **No. 序号**：有单位+工程量（分部分项项）**或**有金额（开办费/暂列金项）的行都编号，二者都是可报价条目
- **单元格格式**：**背景色、字体颜色、加粗、斜体逐格保留**（含空单元格上的底色）。字体名/字号统一为 9pt Microsoft YaHei UI，边框和行高不保留——这三项下游 `pk-boq-hierarchy` 会按层级重设
- **L1 标记**：每个 sheet 的数据前插入一行 `【Sheet名称】`，蓝底加粗，标记数据来源
- **数据行**：原始行内容原样保留（Ref 编号、章节标记、所有列值），不做转换
- **公式**：源单元格的公式取值写入（fastexcel 读的是计算值），交付文件只含 No. 列的序号公式

## 清单表识别规则

`classify_sheet` 认两类表，两类都合并：

| 类型 | 条件 | 典型 |
|------|------|------|
| **measured**（分部分项） | 描述列 + 单位列 + 工程量列 | 土建/安装工程量清单 |
| **lumpsum**（总价项） | 描述列 + 金额列，无单位/工程量 | 开办费、暂列金、暂定金额、计日工 |

先判 measured 再判 lumpsum——分部分项表通常也有金额列，不能被误判成总价项。

**金额列同义词**：`Amount / Total / Total Price / Total Amount / Sum / Price / 金额 / 合价 / 总价 / 总额` 归为同一列，所以开办费的 `Amount` 和分部分项的 `Total Price` 会落到输出表的同一列，全标造价一个 SUM 就能核。

**汇总表必须靠 sheet 名拦**：汇总表的结构和 lumpsum 表**完全一样**（描述+金额），内容上无法区分，唯一防线是 `DEFAULT_SKIP_PATTERNS`（`SUMMARY / LIST / COLLECTION / GRAND TOTAL / 汇总 / 总计`）。放它进来等于金额重复计算。遇到新命名（如 `BILL NO.1`、`RECAP`）必须用 `--skip` 补上，或者直接加进默认列表。

**副表头 vs 第一条数据行**：表头下一行只有同时满足"跨 2 列以上 + 无 BOQ 关键词 + 描述列不超 6 字 + Ref 列不像条目编号"才算副表头（如 THB 货币行、(1)(2)(3) 列编号行）。开办费表通常没有章节标题，表头下面直接就是数据，判错就会整条吞掉——这是实测踩到过的坑。

## 硬规则

- **临时副本**：始终先复制源文件到 `temp/` 子目录再处理，禁止直接在原文件上操作。合并完成后自动清理副本
- **隐藏行**：检测到隐藏行必须停下来询问用户。用户确认后传 `--delete-hidden-rows` 重新运行，删除操作在临时副本上进行，不破坏原文件
- **禁止去除原清单背景色**：原清单的单元格底色是人工信息（标黄待确认、标红异常、章节配色），**必须随数据一起搬到合并表**。禁止只读值不读样式、禁止给数据行统一刷一个 `data_fmt` 了事。字体色、加粗、斜体同理，空单元格上的底色也要保住
- **样式必须走缓存池**：`make_fmt_pool` 按 (底色, 字体色, 粗, 斜, 是否数字) 缓存 Format 对象。禁止逐格 `add_format`——xlsxwriter 的 Format 对象数量直接写进 styles.xml，逐格新建会让文件体积和写入时间爆掉
- **样式与值共用列映射**：样式必须和值走同一个 `col_map`，否则窄表的颜色会落错列
- **行号必须对齐**：fastexcel 一律 `load_sheet_by_name(name, header_row=None)`。默认 `header_row=0` 会吃掉第一行，使 df 索引与 openpyxl 的真实行号错开，样式就会整体串行
- **原样保留**：列结构、表头、行内容全部原样保留，不做列映射、重命名、格式转换
- **列对齐按表头名称**：窄表缺列时按表头文本匹配到模板列，**禁止按列号硬编码位移**（曾因假定 Quantity 在 index 3 而整列错位，且源侧输出侧同错对消、验证假通过）
- **前向填充仅限名称列**：数据区垂直合并单元格的前向填充**只作用于描述列（desc_col_idx）**，其他列不填充。防止 Ref/Unit/Qty 等列的值被错误传播。填充遇 L1【】标记行重置，描述不跨 sheet 边界串味
- **L1 注入**：每个 sheet 数据前插入 L1【sheet名】行，标记来源。不注入 L2/Note 等更深层级
- **输出**：`(YYYY-MM-DD Merge)原文件名.xlsx`，放源文件同目录（交付物，不放 `temp/`）。合并后在同一文件上就地层级化，不另生成层级化文件
- **去重**：仅跳空行（整行全空）/ 错误值 / 重复表头（多列比对，非关键词匹配）。其余全部保留，不确定时一律保留
- **验证必须同时核工程量和金额**：开办费/暂列金表没有工程量，只核工程量等于**完全不核**（0.00 vs 0.00 恒 PASS，金额丢了也发现不了）
- **源侧合计必须从源列直读**：用各表自己的列索引读未映射的原始行，**禁止读映射后的 row_data**——那样列映射一旦出错，源侧和输出侧同错对消，验证会假通过（Quantity 错位那个 bug 就是这么藏住的）
- **汇总表只能靠 sheet 名拦**：见「清单表识别规则」，误纳入等于金额重复计算
- **清链前置**：始终用 `xlsx-purge` 技能，不要 ad-hoc。合并前先清外部链接
- **不用 Excel COM**：曾评估过 `win32com` 的 `Range.Copy(Destination)` 整体复制（格式 100% 保真，含边框和合并单元格），实测 7500 行 13.6 秒 vs 现方案 5.5 秒——COM 有约 8 秒固定启动开销，反而更慢，还要依赖本机 Excel、可能残留 excel.exe 进程。**不要再往这个方向改**，脚本逐格写不是 token 生成，开销可以忽略
- **删隐藏行后必须重新识别**：`delete_hidden_rows_from_sheets` 会让每个 sheet 的行号整体上移，表头行号、data_start 和样式表全部失效，必须重跑 `identify_qualifying` 并重读样式
- **Excel 规范** → `pk-boq` 技能

## 相关技能

`pk-boq-hierarchy`（下游必经） · `xlsx-purge` · `document-ingest` · `pk-boq` · `pk-boq-compare` · `pk-boq-inquiry`
