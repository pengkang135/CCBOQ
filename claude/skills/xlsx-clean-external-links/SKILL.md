---
name: xlsx-clean-external-links
description: "清除 Excel 文件(.xlsx)中的外部链接、错误 defined names、外部公式引用和 ZIP 级残留。在 ZIP/XML 底层直接操作，无需 Excel COM。当用户需要清除外部链接、清理Excel外部链接、清除Excel链接、去除外部引用、剥离链接、清理Excel表/文件的外部连接、干净xlsx、修复Excel打开时弹出更新链接提示导致卡死时使用。"
license: Proprietary. LICENSE.txt has complete terms
---

# XLSX Clean External Links

> 此技能也可通过 `pk-boq-organize` 的决策树调用。如需 BOQ 合并、关键字提取等功能，使用 `pk-boq-organize`。

## 脚本

`scripts/clean_external_links.py` — ZIP/XML 级 7 步清理：

| 步骤 | 内容 |
|------|------|
| Step 1 | 识别 bad definedNames（`#REF!`/`[外部文件]`/`file://`/UNC/绝对路径） |
| Step 2 | ET 解析 sheet，含 `[N]` 外部引用或 bad name 的公式转值；shared formula 整组一起转 |
| Step 2b | 检测并修复孤立 shared formula（slave 无 master） |
| Step 3 | 清理 workbook.xml：删除 bad definedName、`<externalReferences>` |
| Step 4 | 同步清理 calcChain：删除已转值单元格的计算链条目 |
| Step 5 | 清理 .rels 文件中的 externalLink Relationship |
| Step 6 | 清理 Content_Types 中的 externalLink Override |
| Step 7 | 写出 ZIP，跳过 externalLinks/ 和 trash/ 目录 |

## 工作流

### Phase 1: 探测

用原始文件确认外部链接存在并量化范围：

```bash
python -c "
import zipfile, os, re
f = 'path/to/file.xlsx'
with zipfile.ZipFile(f, 'r') as z:
    names = z.namelist()
    ext = [n for n in names if 'externalLinks' in n]
    wb = z.read('xl/workbook.xml').decode('utf-8', errors='replace')
    bad_dn = len(re.findall(r'<definedName[^>]*>.*?\[.*?</definedName>', wb, re.DOTALL))
    print(f'{os.path.basename(f)}: {len(ext)} external links, extRefs={\"<externalReferences\" in wb}, bad DN={bad_dn}')
"
```

### Phase 2: 执行

```bash
python scripts/clean_external_links.py "file.xlsx" [-o output.xlsx] [--no-backup]
```

| 参数 | 说明 |
|------|------|
| `input` | 输入 .xlsx（必填） |
| `-o, --output` | 输出路径（默认 `{input}_clean.xlsx`） |
| `--no-backup` | 跳过备份（默认备份到 `原始备份/`） |

**多文件批处理**：对每个文件逐一调用，独立验证。

### Phase 3: 自动验证（6 项强制检查）

```
1. externalLinks 条目数 = 0
2. workbook.xml 中 <externalReferences> 已移除
3. 无效 definedName = 0
4. 孤立 shared formula = 0
5. calcChain 一致性（0 不匹配）
6. 所有 XML parse 通过
```

6 项全部通过才能交付。

### Phase 4: 用户手动验证

- [ ] Excel 打开不弹出"更新链接"提示
- [ ] 文件正常打开，不陷入修复→崩溃循环
- [ ] 抽查公式计算和数据完整性正常
- [ ] 打开后退出提示保存属正常（Excel 重算公式+重建 calcChain）

## 关键规则

- **必须使用原始文件**：不得在已部分清理的文件上重复清理（增量清理掩盖问题）
- **必须使用此脚本**：不得编写 ad-hoc 临时脚本替代（简单 zip 删除会遗漏 definedName/rels/calcChain 清理）
- **顺序**：清理外部链接是其他处理（`document-ingest` → `merge_boq`）的前置步骤

## 检测规则

| 检测类型 | 匹配模式 |
|----------|---------|
| 外部工作簿索引 | `[N]` 标记（如 `[1]`） |
| 坏名称 | `#REF!`, `#NAME?`, `#VALUE?`, `#DIV/0!`, `#NUM!`, `#NULL!`, `#N/A` |
| 协议引用 | `file://`, `https?://` |
| UNC 路径 | `\\server\...` |
| 绝对路径 | `X:\...` |
