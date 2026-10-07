# 三色差异标记方法论

把新版设计院清单相对旧版合并清单的变更，用红/黄/绿三色标到旧版副本上，供人眼快速识别"哪变了"。

## 三色语义

| 颜色 | 含义 | 操作 | 值来源 |
|------|------|------|--------|
| 绿 | 新增 | 整行插入到同一 L3 `{}` 或最接近位置 | 新版清单 |
| 黄 | 修改 | 改单位/工程量后标黄，**不改名称** | 新版清单 |
| 红 | 删除 | 仅标红不删，等人工删除 | 保留旧值 |

**颜色常量（RGB 十六进制）**：绿 `00FF00`、黄 `FFFF00`、红 `FF0000`。（旧版用 COM 的 `Interior.Color` 是 BGR，黄红两色顺序相反，别照抄。）openpyxl 读到的是 ARGB 字符串：`FF00FF00`（绿）、`FFFFFF00`（黄）、`FFFF0000`（红）。

## 判定规则

| 情形 | 判定 | 说明 |
|------|------|------|
| 工程量变化 | 修改(黄) | qty 差值 > 1e-6 |
| 单位实质变化 | 修改(黄) | `No.`/`Set` 等视为同义不改 |
| 名称/单位同义仅翻译差异 | 不改 | "中文转英文翻译问题，不算偏差" |
| 新版独有 | 新增(绿) | 匹配失败自然落入 |
| 基准独有 | 删除(红) | 标红不删 |

**名称实质变化（材料/尺寸/类型不同）**：匹配失败自然落入"删 + 增"，不单独判"修改名称"。这比自动改名称更安全——描述一旦改动需人工确认是否真偏差。

## 匹配引擎（三级权重）

块内 DP 对齐（LCS 变体），`match_score`：

1. **qty 相同**：`3.0 + 描述相似度`（同量项优先匹配，翻译差异项靠这个匹配上）
2. **编码相同**：`2.0 + 描述相似度`（`TR01A`/`IS`/`MH`/`OP`/`DP` 等前缀）
3. **描述相似**：`SequenceMatcher > 0.7` 才有效，否则 0（不匹配）

## 插入策略

- **从后往前**：新增项按 anchor 降序插入，避免插入导致后续行号偏移
- **插行**：`xlsx_rowops.SheetEditor.insert_row(after=anchor, ...)`，zip/XML 层，不启动 Excel。插入后的公式行引用（含绝对引用和 SUBTOTAL 范围）由它统一平移
- **禁止 openpyxl `insert_rows`**：不调整公式引用，会破坏 CleanDescription/入价等公式列
- **anchor**：新增项取"前一个已匹配基准项"的行号；块开头无前项时取"后一个已匹配项"
- **anchor=None**（整块无匹配基准项）：跳过并打印警告，人工定位插入

## 硬规则

- **基准必须是干净旧版**：若基准已被部分变更污染，diff 会失真（已插的新增项被判为匹配）。先回滚或人工修正再跑
- **保留原背景色**：只对标记行整行 `Interior.Color` 覆盖，其余单元格背景色不动（源清单黄色改动标记原样保留）
- **删除不删**：脚本只标红，物理删除永远由人工执行
- **先 dry-run 后 apply**：dry-run 输出修改/新增/删除清单，人工抽查（尤其同描述同 qty 项易匹配错）确认后再 apply

## 已知陷阱

| 陷阱 | 表现 | 解决 |
|------|------|------|
| L2 分组错位 | 旧版有独立 L2（如 `CAR PARK ENTRANCE AND EXIT`），新版保留在原 L2（5.1）下，条目被误判为新增 | `--l2-extra` 列出旧版额外 L2 + `--l2-merge-to` 指定归并目标 |
| 同描述同 qty 项匹配错 | 门 `2500x3000` 有 Class B 和 Roller Shutter 两条，DP 匹配可能对错 | dry-run 抽查，人工修正 cur_row |
| 翻译差异误判为新增 | 描述文字不同但同义，SequenceMatcher 低分 | 靠 qty 相同权重兜底；仍误判时人工标"不改" |
| openpyxl 破坏公式 | `insert_rows` 后公式行号错乱 | 用 `xlsx_rowops.SheetEditor`：zip/XML 层插行，行号映射后重写所有公式引用 |
| 新增项公式列空 | 只写名称/单位/工程量，公式列（CleanDescription/入价/分类）留空 | 符合"只改三列"要求，后续套价补全 |

## 典型工作流

```bash
# 1. dry-run 看差异
python mark_boq_three_color.py \
    --base CMI_MOD2_BOQ.xlsx \
    --new "2026-08-16 Merge第三版.xlsx" \
    --base-cols desc=5,unit=6,qty=7 --new-cols desc=3,unit=4,qty=5 \
    --dry-run --json diff.json

# 2. 抽查 diff.json，确认 L2 分组、同描述项匹配正确

# 3. 应用
python mark_boq_three_color.py \
    --base CMI_MOD2_BOQ.xlsx \
    --new "2026-08-16 Merge第三版.xlsx" \
    --base-cols desc=5,unit=6,qty=7 --new-cols desc=3,unit=4,qty=5 \
    -o CMI_MOD2_BOQ_第三版变更更新.xlsx
```
