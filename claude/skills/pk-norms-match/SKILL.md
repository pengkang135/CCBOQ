---
name: pk-norms-match
description: "BOQ清单套定额：Claude语义理解匹配。构建定额池 → 拆分为Agent批次 → 并行派发子Agent做语义匹配 → 合并结果 → 写入Excel。适用于任何定额库和清单。"
---

# BOQ清单套定额

将BOQ清单Excel中的项目逐一匹配到定额数据库，基于Claude语义理解而非关键词计数。

## 核心原则

- **不使用脚本做匹配。** 匹配过程由 Claude 直接阅读理解 BOQ 条目含义和定额名称，基于工程专业知识做语义匹配。
- **不绑定特定定额库。** 本方法适用于任何定额标准（港口、公路、房建、市政等），只需替换数据库路径和章节映射即可。
- **保留脚本的环节**：定额池构建、数据库查询、结果合并、Excel写入。这些是确定性操作，脚本比AI更可靠。

## 整体流程

```
BOQ.xlsx → 构建定额池(按章节分组) → 拆分为Agent批次JSON → 并行派发子Agent语义匹配
                                                                     ↓
                                                             各Agent写入结果.txt
                                                                     ↓
                                                           合并脚本解析 → merged.json
                                                                     ↓
                                                           write_results.py → Excel
```

## 阶段零：前期准备

### 定额数据库

支持任意SQLite定额数据库，需满足以下结构（或通过配置映射）：

```sql
-- 章节表
chapter: id, parent_id, sort_order, level, title

-- 定额表（section_title 是匹配的关键字段）
norms_table: id, chapter_id FK, section_title, unit, work_content

-- 定额子目表（norms_code 是最终输出的定额编号）
norms_item: id, table_id FK, norms_code, attr_level1-4, cost_item, quantity
```

### 配置文件

在项目目录下创建 `config.json`：

```json
{
  "databases": {
    "main": { "path": "path/to/main.sqlite", "label": "主定额", "prefix": "" },
    "supplementary": { "path": "path/to/supp.sqlite", "label": "参考定额", "prefix": "[参考]" }
  },
  "chapter_mapping": [
    { "chapter_name": "土石方工程", "chapter_ids": [1,2,3,4,5,6,7] },
    { "chapter_name": "基础工程", "chapter_ids": [8,9,10,11,12,13] }
  ],
  "boq_sheet": "清单",
  "boq_columns": {
    "row": "A",
    "sn": "B",
    "name": "E",
    "unit": "F",
    "qty": "G",
    "description": "H"
  }
}
```

## 阶段一：构建定额池

从定额数据库按章节提取唯一定额条目，作为匹配候选池。

```python
# 从主定额库按章节查询
SELECT DISTINCT nt.section_title, nt.work_content, nt.unit, c.title as chapter_title
FROM norms_table nt
JOIN chapter c ON nt.chapter_id = c.id
WHERE nt.chapter_id IN (?, ?, ...)
ORDER BY nt.section_title

# 参考定额库全量作为补充
SELECT DISTINCT nt.section_title, nt.work_content, nt.unit, c.title as chapter_title
FROM norms_table nt
JOIN chapter c ON nt.chapter_id = c.id
ORDER BY nt.section_title
```

按 `section_title` 去重后，数万条定额通常浓缩为数百个唯一定额组，极大减少Agent匹配时的候选空间。

## 阶段二：拆分清单并派发 Agent

将 BOQ 条目按工程类别分类，每个 Agent 处理 60-120 项。生成 dispatch JSON 文件，每文件包含 `items`（BOQ项）和 `quota_pool`（定额池）。

Agent 分配按**工程专业**划分（非按数据库章节），确保每个Agent的知识领域聚焦：

| 划分维度 | 说明 |
|----------|------|
| 按分部 | B/C分部（土石方/场地）、D分部（地基/桩基）、E/F分部（混凝土/钢筋）、G分部（机电管）等 |
| 定额池 | 每个Agent只携带相关章节的定额池，而非全库 |
| 条目数 | 60-120条/Agent，确保上下文不溢出 |

已匹配完成的分部可通过配置排除，不再重复匹配。

## 阶段三：并行语义匹配（核心）

### 3.1 前置过滤

派发Agent前，在Python端做确定性过滤，减少无效匹配：

```python
def should_skip(item):
    """确定性跳过规则，不需要AI判断"""
    name = item.get("name", "")
    qty = item.get("true_qty") or item.get("qty", 1)

    # 1. 零工程量：跳过
    if qty == 0 or qty is None:
        return True, "零工程量"

    # 2. 标题标记行：名称含 "Summary" / "Subtotal" / "Total" / "小计" / "合计"
    title_keywords = ["Summary", "Subtotal", "Total", "小计", "合计",
                      "Carried", "Brought", "forward", "to collection"]
    for kw in title_keywords:
        if kw.lower() in name.lower():
            return True, f"标题行({kw})"

    # 3. 概念性单位（lump sum / 项 / lot 且不可量化）
    conceptual_units = ["lump sum", "p-sum", "l.s", "lot", "item", "ps", "p.s."]
    unit = (item.get("unit") or "").lower().strip()
    if unit in conceptual_units:
        # 开办费/管理类：无对应定额
        # 具体工程类 lump sum：需拆解后匹配，暂标记需人工
        return False, None  # 不自动跳过，交给Agent判断

    return False, None
```

### 3.2 Agent 匹配提示词模板

每个子 Agent 的 prompt 必须包含以下结构化分析流程：

```
## 你的任务

你是工程造价专家。对下面 {item_count} 条BOQ清单项，在定额池中找到最匹配的定额子目。

## 分析流程（逐条执行，不可跳过）

### 步骤1：理解工程内容
- 阅读 BOQ 条目的 name 和 description
- 关注上下文：context_div（分部）、context_subdiv（子分部）、context_subitem（细目）
- 同一 context_subdiv 下的条目通常属于同一工程类型，应匹配到同一或相近定额章节
- 判断该条目属于哪个工程专业（土石方/基础/混凝土/钢结构/机电/装饰等）

### 步骤2：检查工程量与单位
- 工程量为0 → 直接输出"跳过: 零工程量"
- 单位为 lump sum / p-sum / item / lot → 判断是否可量化：
  * 开办费/管理费类（Contractor's Supervision、Security、Insurance）→ "无对应定额"
  * 具体工作类（如 "Supply and Install Handrails"）→ 继续匹配
- 单位为物理量（m3、m2、m、t、kg、个、套等）→ 继续匹配

### 步骤3：在定额池中查找
- 基于工程专业知识做语义判断，不是关键词计数
- 理解BOQ条目的施工工序实质，匹配到描述该工序的定额子目
- 同一工序有多种施工方法时（陆上/水上、机械/人工、有/无围堰），根据BOQ上下文选择
- 定额池中的 section_title 是最关键匹配字段，work_content 提供额外信息

### 步骤4：单位兼容性验证
- BOQ条目单位和定额单位必须可换算：
  | 兼容关系 | 示例 |
  |---------|------|
  | 完全一致 | m3 ↔ m3 |
  | 定额含倍数前缀 | m3 ↔ 100m3、m2 ↔ 100m2、m ↔ 100m |
  | 同维度可换算 | t ↔ 100t、kg ↔ t、m2 ↔ 1000m2 |
  | 不可兼容 | m3 ↔ m2（体积vs面积）、m3 ↔ m（体积vs长度）、t ↔ m2 |
- 单位不兼容 → 这不是你要找的定额，继续搜索或标记"无对应定额"

### 步骤5：结合定额子目内容深入判断
- 如果 section_title 匹配但不确定，查看 work_content（工作内容描述）
- 如果 section_title 有多个相似项，用 attr_level1-4 和 cost_item 区分
- 例如：预制混凝土构件有多种（空心板/实心板/镶面板/靠船构件），按BOQ描述选择
- 定额名称相似但施工条件不同（水上/陆上、有/无围堰、不同桩径），必须选匹配的那个

### 步骤6：输出判定

## 输出格式

每行一条，格式：
Row{row} | {name} | {判定类型} | 理由: {简短中文理由}

判定类型分四种：
- **匹配: {section_title}** — 在定额池中找到对应定额
- **需其他章节** — 明显不属于本批次工程范畴（如土石方批次中出现电气/管道/给排水/消防/通信）
- **无对应定额** — 属于本范畴但定额库缺乏对应子目（如检测试验、监测仪器、特种施工工艺）
- **跳过: {原因}** — 零工程量/标题行等

## 输出示例

Row45 | Contractor's Supervision | 无对应定额 | 理由: A分部开办费/管理费，非施工工序
Row102 | Ground clearance Block C | 匹配: [主] 一、场地清理 | 理由: 场地表面植被清除，定额含清除草皮及30cm表土
Row187 | Steel tubular pile fabrication Type A | 匹配: [参考] 一、水上打大直径钢管桩 | 理由: 大直径钢管桩制作安装(水上打桩)
Row256 | Precast Slab Installation | 匹配: 八、水上安装空心板 | 理由: 水上安装预制板类构件，M50混凝土空心板
Row103 | Electrical Cable 11kV | 需其他章节 | 理由: 电气专业，不属于土建定额范畴
Row140 | Settlement Plate | 无对应定额 | 理由: 沉降板为监测仪器，定额库无监测类子目

## 常见匹配陷阱（必须避免）

1. **不要只看关键词** — "Concrete" 可以匹配到混凝土浇筑、预制构件、管桩、路面等完全不同定额
2. **不要忽略施工方法** — 陆上打桩≠水上打桩，机械开挖≠人工开挖
3. **不要忽略单位** — m3 的混凝土浇筑和 m2 的混凝土面层是不同的定额
4. **不要将MEP匹配到土建** — 电气/给排水/消防/暖通/通信属于机电安装定额，非港口水工
5. **不要把检测/监测当施工** — 静载试验、沉降观测、钻孔取样属于检测监测，非施工定额
6. **不要把开办费当施工** — 管理费、保险费、安保费属于间接费，非实体工程定额
7. **不要忽略上下文** — 同一分部/子分部的条目通常属于同一工程类型，应匹配到相近定额

## 统计汇总

结尾附统计：
总计: {N} 条
成功匹配: {M} 条
需其他章节: {P} 条
无对应定额: {Q} 条
跳过: {R} 条
```

### 3.3 并行派发

```
主会话:
  Agent("语义匹配 earthwork batch1 (120项)")  ← 后台运行
  Agent("语义匹配 earthwork batch2 (120项)")  ← 后台运行
  Agent("语义匹配 concrete batch1 (100项)")   ← 后台运行
  Agent("语义匹配 ancillary batch1 (120项)")  ← 后台运行
  ... (全部并行)

  等待全部完成 → 收集 .txt 结果文件
```

每个子 Agent 必须直接写入文件（不能只返回内存结果），防止上下文压缩丢失。

## 阶段四：合并结果

编写合并脚本解析所有 `.txt` 结果文件：

1. 从定额数据库构建 `section_title → norms_code` 映射（取每个 section_title 的第一个 norms_code）
2. 逐行解析各结果文件，正则提取 Row、匹配类型、定额名称
3. 处理编码变体：数据库中可能含 CJK 异体字（如 `錨` vs `锚`），需做字符标准化
4. 处理 section_title 格式差异：Agent 可能写 `主定额-五 | 陆上钢结构` 而非 DB 中的 `五、陆上钢结构`
5. 对"已匹配"项，通过 code_map 查找 quota_code 填入；"需其他章节"/"无对应定额"留空
6. 输出 `merged_semantic_final.json`

### 关键处理细节

```python
# CJK 字符标准化
VARIANT_MAP = {
    '錨': '锚', '峯': '峰', '羣': '群', '峽': '峡',
    '峯': '峰', '羣': '群', '衞': '卫', '爲': '为',
}

# section_title 格式标准化
def normalize_section_title(title):
    # "主定额-五 | 陆上钢结构" → "五、陆上钢结构"
    m = re.match(r'^.+-([一二三四五六七八九十]+)\s*\|\s*(.+)', title)
    if m:
        return f"{m.group(1)}、{m.group(2)}"
    # 已有 "五、xxx" 格式
    return title

# 定额编号查找（级联降级）
def resolve_quota_code(quota_name, code_map):
    # 1. 精确匹配
    if quota_name in code_map:
        return code_map[quota_name]
    # 2. 标准化后匹配
    normalized = normalize_section_title(quota_name)
    if normalized in code_map:
        return code_map[normalized]
    # 3. CJK变体清理后匹配
    clean = apply_variant_map(quota_name)
    for k, v in code_map.items():
        clean_k = apply_variant_map(k)
        if clean_k and clean in clean_k or (clean_k and clean_k in clean):
            return v
    return ""
```

### 输出 JSON 格式

```json
{
  "row": 60,
  "boq_name": "Ground clearance in the container yard area (Block C)",
  "match_type": "已匹配",
  "matches": [{
    "quota_code": "G1-001",
    "quota_name": "一、场地清理",
    "db_source": "claude-semantic",
    "match_evidence": "场地表面清理植被清除平整"
  }]
}
```

## 阶段五：写入 Excel

```bash
python scripts/write_results.py merged_semantic_final.json 原始清单.xlsx \
  --sheet "清单" -o 输出.xlsx
```

仅写入 A列（定额编号）和 B列（定额名称）。未匹配项（"需其他章节"/"无对应定额"）A/B列清空留空。

`write_results.py` 通过 BOQ 名称列做名称匹配定位行，而非依赖行号。

## 适配新定额库

切换到新定额库的步骤：

1. **更新 config.json**：修改数据库路径和章节映射
2. **重建定额池**：运行 `build_quota_pools.py` 生成新的定额池
3. **调整 dispatch**：按新定额的章节结构重新划分Agent批次
4. **无需改动**：Agent 匹配流程、合并脚本、Excel写入均与定额库无关

## 参考

- `merge_all_semantic.py`: 合并脚本模板（解析结果文件 + 定额编号回填）
- `write_results.py`: Excel写入脚本（A列定额编号 + B列定额名称）
- `build_quota_pools.py`: 定额池构建脚本
- `dispatch_semantic.py`: Agent批次拆分脚本
