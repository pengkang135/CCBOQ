---
name: pdf-bookmark-from-summary
description: 从摘要说明文档为超长 PDF 反向注入书签树。适用场景：阅读招标文件/法规/技术规范/合同/报告等超长 PDF，同时整理摘要说明（.md 文档）并大量引用源文页码，希望在源 PDF 侧栏插入分层书签以便反向导航。触发词：PDF 加书签、PDF 反向索引、给 PDF 做目录、从摘要生成书签、超长文书签、PDF 大纲、PDF 导航书签、PDF 侧栏目录、PDF 批注书签、pdf bookmark。
license: Proprietary
---

# PDF 书签反向注入（从摘要文档生成）

## 场景

阅读超长 PDF（招标文件、法规、技术规范、合同、研究报告、教材等），过程中在 md 文档里整理摘要说明并引用源文页码。整理完希望在源 PDF 里插书签，使得 PDF 阅读器侧栏能一键跳到每个引用点——**反向索引**。

**核心价值**：Markdown 规范不支持行/页跳转（`#L42` 只在 GitHub 网页有效），但 **PDF 书签是所有 PDF 阅读器都支持的原生功能**，能真正实现"点一下→跳到源文位置"。

## 触发词

给 PDF 加书签、PDF 大纲、PDF 反向索引、从摘要生成书签、超长文书签、PDF 导航、PDF 目录、PDF 批注书签、给源文件加书签、pdf bookmark

## 前置条件

- 一份**源 PDF**（超长，一般 100 页以上）
- 一份或多份**摘要 md 文档**（含章节层级和 PDF 页码/章节引用）
- Python 环境含 `pymupdf`（推荐，速度快，支持 UTF-8 书签）

```bash
python -c "import fitz; print(fitz.__version__)"
# 或安装: pip install pymupdf
```

## 三步工作流

### Step 1 · 探查 PDF 结构

先用 `scripts/inspect_pdf.py` 摸底：

```bash
python scripts/inspect_pdf.py <source.pdf>
```

输出：
- 总页数
- 是否已有书签（有几个）
- 前 30 个书签（如果有）
- 建议：如已有书签，是否合并还是覆盖

### Step 2 · 生成书签配置（bookmarks.json）

有两种方式：

**方式 A · 从摘要 md 半自动生成（推荐）**

```bash
python scripts/extract_toc_from_md.py <summary.md> <source.pdf> -o bookmarks.json
```

脚本会：
1. 解析 md 的 `## / ### / ####` 章节结构
2. 从章节标题和表格里提取所有"PDF 页码引用"（正则匹配 `P.212`、`PDF 212`、`第 212 页`、`212-214`、`212 起`、`p.212`）
3. 提取每个引用附近的**上下文关键词**（章节标题、附近的独特短语）
4. 用关键词在 PDF 中搜索定位**真实页码**（因为 md 里标的页码可能有偏移）
5. 生成 `bookmarks.json` 草稿，同时输出校对报告

**方式 B · 手工编写 bookmarks.json**

如果摘要 md 结构不规则，或想完全自定义，直接手写：

```json
[
  {"level": 1, "title": "【项目做法表.md】索引", "page": 212},
  {"level": 2, "title": "一、结构专业", "page": 605},
  {"level": 3, "title": "1.1 桩基工程", "page": 552},
  {"level": 4, "title": "Piling Method Statement §1.9", "page": 557}
]
```

**书签层级规则**（用户确立的约定）：
- **Level 1** = 摘要 md 文件名（如 `【项目做法表.md】索引`）
- **Level 2+** = md 章节 + 页码
- 允许多个 Level 1（不同摘要文档 → 同一 PDF 的多个入口树）

层级只能 `+1` 递增，不能跳级（如从 L2 直接跳到 L4 会报错）。

### Step 3 · 写入 PDF

```bash
python scripts/apply_bookmarks.py <source.pdf> bookmarks.json [-o output.pdf]
```

- 默认输出 `<source>_bookmarked.pdf`（不改原文件）
- 若 `-o` 未指定，输出到 PDF 同目录

## 决策树

```
用户: "给这个 PDF 加书签" / "从这份摘要生成 PDF 导航"
   │
   ├─ 有摘要 md 吗？
   │    │
   │    ├─ 有 → Step 1 探查 PDF → Step 2 方式 A（从 md 抽取）
   │    │
   │    └─ 没有，只有需求 → Step 2 方式 B（手工列 bookmarks.json）
   │
   └─ 页码可能有偏移吗？
        │
        ├─ md 里页码是从 md 转换来的 → 需要用关键词校对（Step 2 内置）
        │
        └─ md 里页码是手写的 PDF 页码 → 一般准确，可跳过校对
```

## 关键实现细节

### 页码偏移处理

**问题**：md 转 PDF 时页码计数常有偏移。例如：
- md 里 `## Page 313` 实际对应 PDF 第 317 页（偏移 +4）
- 不同章节偏移量还可能不同（PDF 的 TOC/图纸/附录会插页）

**解决**：不依赖 md 里标的页码，而是**用 md 里的上下文关键词在 PDF 全文搜索**：
- md 里的章节名（"3.02 Scope of the Works"、"SECTION 096900 ACCESS FLOORING"）
- md 里的独特短语（"tentatively at end of January 2027"、"THB฿ 4,000,000"）
- 匹配到 PDF 里的实际页码作为书签目标

### 保留原有书签（可选）

某些 PDF 已有出版社/CAD 生成的书签，可以保留：

```bash
python scripts/apply_bookmarks.py <source.pdf> bookmarks.json --merge-existing
```

新书签会追加到原书签树末尾，或与原书签同级并存。

### 支持多个摘要文档

一个 PDF 可以对应多个摘要 md（不同角度的分析）。生成多份 `bookmarks.json`，逐份 apply：

```bash
python scripts/apply_bookmarks.py source.pdf summary1.json -o step1.pdf
python scripts/apply_bookmarks.py step1.pdf summary2.json --merge-existing -o final.pdf
```

## 脚本速查

| 脚本 | 用途 | 关键参数 |
|------|------|----------|
| `inspect_pdf.py` | 摸底 PDF（页数/已有书签） | `<pdf>` |
| `extract_toc_from_md.py` | 从摘要 md 生成书签草稿 | `<md> <pdf> -o <json>` |
| `apply_bookmarks.py` | 写入 PDF | `<pdf> <json> [-o <out>] [--merge-existing]` |
| `verify_pages.py` | 独立校对页码（可选） | `<json> <pdf>` |

## 输出建议

在报价/合规/研究等**长期使用**的场景，建议：

1. **原文件放"招标文件/"或"参考资料/"目录**，永久不改
2. **加了书签的版本命名为 `<原名>_bookmarked.pdf`**，日常查阅用这个
3. **bookmarks.json 与摘要 md 放同一目录**，便于摘要更新时同步重跑

## 使用注意

- **书签只支持内部页跳转**，不能像 md 链接那样引用外部文件——它是 PDF 内的原生锚点
- **PDF 页码是绝对页码**（从 1 开始），不受 PDF 内部页眉编号影响
- **中文/emoji 书签需要 UTF-8**：pymupdf 天然支持，无需额外处理
- **超大 PDF（>500MB）**建议先 `garbage=4, deflate=True` 压缩输出，`apply_bookmarks.py` 默认已开启
- **重跑不叠加**：默认覆盖模式，重跑一次只保留最新 bookmarks.json 的书签。需要保留原书签用 `--merge-existing`

## 与其他技能的关系

- 需先做**摘要 md 整理** → 常配合 `document-ingest`（PDF → md）+ `baoyu-format-markdown`（美化）使用
- 摘要 md 完成后 → 用本技能反向给 PDF 加书签
- 未来如需给不同角度的多份摘要注入同一 PDF → 用 `--merge-existing`

## 完整示例

```bash
# 场景：招标文件 500 页，已整理"项目做法表.md"
cd project-root/

# 1. 摸底 PDF
python C:/Users/Kevin/.claude/skills/pdf-bookmark-from-summary/scripts/inspect_pdf.py \
  "docs/tender.pdf"

# 2. 从摘要生成书签草稿
python .../scripts/extract_toc_from_md.py \
  "docs/项目做法表.md" \
  "docs/tender.pdf" \
  -o "docs/bookmarks.json"

# 3. 人工 review bookmarks.json，按需微调

# 4. 应用到 PDF
python .../scripts/apply_bookmarks.py \
  "docs/tender.pdf" \
  "docs/bookmarks.json"

# 输出：docs/tender_bookmarked.pdf
```
