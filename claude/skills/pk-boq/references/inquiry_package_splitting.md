# 拆分询价包 — 图纸/资料分发工作流

将设计图纸和雇主资料按询价包类别拆分并分发到对应询价文件夹。

## 适用范围

任何需要通过关键词从雇主文档和设计院图纸中筛选文件并分发到结构化询价包目录的场景。

## 标准询价包目录结构

每个询价包子文件夹遵循以下约定：

```
{包编号} {包名称}/
├── 1.BQ/                          # BOQ 清单文件
├── 2.Employer's design documents/  # 雇主招标设计文件
│   └── Drawings/                   # 雇主图纸
│       └── CAD files/              # CAD 文件（如有）
├── 3.Tender Design/                # 投标设计/设计院图纸
│   ├── {设计院A}图纸/
│   └── {设计院B}图纸/
├── 4.PER/                          # 雇主 PER（评估报告章节）
│   ├── {章节号} {章节名}/
│   └── ...
└── 5.Site serveys/                # 现场勘察资料
    ├── Bathymetry/
    ├── Geophysical/
    ├── Geotechnical/
    ├── Land Seismic/
    └── Topographic/
```

## 工作流

### Step 1: 确定询价包

从 BOQ 或采购计划中提取需询价的包件清单。每包对应一个目标文件夹。

### Step 2: 确定搜索关键词

根据包件内容提取文件名搜索关键词：

- 语言多样性：中英文关键词并行搜索。例如钢轨 → `rail`, `crane rail`, `钢轨`; 桩基 → `pile`, `管桩`, `PHC`
- 关联对象：搜索使用该材料的配套设备/结构。例如钢轨 → 搜索 `crane`（起重机用轨）、`quay`（码头结构含轨）
- 不要读取文件内容，仅根据文件名判断匹配

### 文件搜索工具：优先用 `find`

**一律用 Bash `find` 做文件名搜索，不用 MCP `start_search`（files 模式）或 Glob。**

```bash
# 单关键词
find "{源目录}" -iname "*keyword*" -type f

# 多关键词（OR）
find "{源目录}" -iname "*light*" -o -iname "*mast*" -o -iname "*照明*" -type f

# 限制深度、排除目录
find "{源目录}" -maxdepth 3 -iname "*keyword*" -not -path "*/.git/*" -type f
```

**原因**：`find` 一次调用返回结果，无 session 开销、无 JSON 包裹、无分页轮询。MCP search 需要 `start_search` + `get_more_search_results` 两轮调用，每轮带 status/runtime/分页元数据，对文件名搜索是纯 token 浪费。Glob 不支持 `-iname`（大小写不敏感）。

**例外**：只在需要跨多个不连续目录、或搜索条件极为复杂时才用 MCP content search（不是 files search）。

### Step 3: 搜索雇主文档

遍历雇主文档来源目录：

| 来源 | 路径模式 | 说明 |
|------|---------|------|
| PER 报告 | `{雇主文档根}/PER/` | 按章节组织，如 `002 Materials/`, `005 Quay/` |
| 雇主图纸 | `{雇主文档根}/Drawings/` | PDF/CAD 格式，可能有图纸编号 |

按关键词匹配文件名（case-insensitive），将匹配文件复制到目标 `4.PER/{章节}/`（PER）或 `2.Employer's design documents/Drawings/`（图纸）。

### Step 4: 搜索设计院图纸

遍历各设计院图纸目录，按关键词匹配文件名。

**文件名只有编号无具体名称时**：
1. 在图纸源目录中查找图纸目录/索引文件（index, drawing list, 目录, TOC, drawing register）
2. 根据索引文件中的条目描述判断哪些图纸与询价包相关
3. 按编号挑选对应图纸文件
4. 若索引亦不可用，选择与询价包结构性相关的图纸（如码头结构段的 General Arrangement、Typical Section 等）

**设计院图纸中无直接匹配时**：
- 选择承载该物件的结构图纸。例如钢轨无专门图纸 → 选码头结构段图纸（钢轨安装于码头）
- 选择总图/总体布置图（General Layout, Terminal Layout）
- 在分发备注中说明选择逻辑

将匹配文件复制到目标 `3.Tender Design/{设计院}图纸/`。

### Step 5: 检查参考包目录结构

**每次分发前**，必须先检查参考询价包的完整目录结构，确保目标结构与参考一致。

```bash
# 列出参考包的完整目录树
find "{base}/{参考包编号}" -type d | sort
```

对比维度：
- 文件夹层级和命名是否与参考包一致
- 设计院子文件夹命名是否包含 "图纸" 后缀
- PER 子文件夹是否按章节号+章节名组织
- Site serveys 子项是否齐全

### Step 6: 复制文件并保持结构

```bash
# 复制 PER 章节（保持子目录结构）
cp -r "{source}/PER/{chapter}" "{target}/4.PER/{chapter}"

# 复制设计院图纸（按设计院分目录）
cp "{source}/Designer/{设计师}/*.{匹配文件}" "{target}/3.Tender Design/{设计师}图纸/"
```

**关键规则**：
- 保持源目录的文件层级，不扁平化
- 设计院图纸放入 `3.Tender Design/{设计院名}图纸/`
- PER 章节放入 `4.PER/{章节号} {章节名}/`
- 确保文件名不带智能引号（`'` vs `'`），统一用直引号

### Step 7: 验证

```bash
# 验证目标包目录结构
find "{target}" -type d | sort
# 对比源和目标文件数量
find "{target}" -type f | wc -l
```

核对：
- 所有预期文件夹均已创建
- 文件数量与匹配一致（PER 章节数 + 设计院图纸数 + 雇主图纸数）
- 无文件遗漏或放错位置

## 常见问题

### Q: 雇主 Drawings 和 PER 中都有相关文件，如何区分存放？
- 雇主图纸（无章节号的独立图纸文件）→ `2.Employer's design documents/Drawings/`
- PER 报告章节（有章节号如 002/005）→ `4.PER/{章节号} {章节名}/`

### Q: 设计院有多个但只有一个有匹配图纸怎么办？
所有设计院都应在 `3.Tender Design/` 下建立子文件夹。无匹配图纸的设计院子文件夹保持空置，待后续补充。

### Q: Site serveys 需要分发吗？
除非询价内容涉及现场条件（如地基处理需要 Geotechnical/Bathymetry），否则保持空目录即可，无需复制现场勘察文件。

## 分发记录

建议在目标包根目录下创建 `_distribute_log.md` 记录分发来源：

```markdown
# {包名称} 询价资料分发记录

## 来源
- 雇主 PER: {per_source_path}
- 设计院图纸: {designer_source_paths}
- 分发日期: {date}

## 选图逻辑
- {设计院A}: {选择原因}
- {设计院B}: {选择原因}

## 文件清单
- PER: {count} 个章节
- 雇主图纸: {count} 张
- {设计院A}图纸: {count} 张
- {设计院B}图纸: {count} 张
```
