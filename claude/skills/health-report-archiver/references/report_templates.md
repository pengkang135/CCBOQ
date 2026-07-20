# Report Templates

## 1. OCR Report (per document)

Saved alongside the original image in the category directory.

```markdown
# YYYY-MM-DD 文档类型报告

**医院：** <医院名称>
**日期：** <报告日期>
**科室：** <科室>

## 检测结果/所见

<OCR提取的关键数据，用表格呈现>

## 提示/诊断

<报告结论>
```

**Rules:**
- Use the exact values from OCR, do not interpret
- Mark abnormal values with ↑ or ↓
- Include reference ranges when available
- Keep it factual and concise

---

## 2. Comprehensive Assessment Report

Saved in `00_综合评估总报告/` (or the archive's equivalent top-level summary directory).

```markdown
# YYYY-MM-DD 综合医学评估与建议

## 一、本轮最核心结论

<3-6 bullet points. Lead with the most clinically significant findings. 
Each point: what changed, which direction, why it matters.>

## 二、今日新增信息逐项解读

### 2.1 <文档1类型>（日期，医院）

| 参数 | 前次值 | 本次值 | 评估 |
|------|--------|--------|:--:|
| ... | ... | ... | ... |

<每个新增文档一段分析>

## 三、分系统评估

### 3.1 <系统1>
### 3.2 <系统2>
...

<每个系统：历史趋势表 + 当前判断>

## 四、用药方案分析

<如有用药变化：对比新旧方案、分析变化原因、评估合理性>

## 五、具体建议（按优先级排列）

### 第一优先
### 第二优先
### 第三优先

### 症状警戒线（出现即就诊）

## 六、一句话总评

<1-2句话概括整体判断>

---

*依据说明：...（区分本地依据/模型判断/外部来源）*
```

### Data Presentation Rules

1. **Trend tables** use this format:

```
| 日期 | 参数1 | 参数2 | 参数3 | 趋势 |
|------|-------|-------|-------|:--:|
| YYYY-MM-DD | value | value | value | →/↑/↓ |
```

2. **Normal/abnormal markers**: Bold abnormal values, add ↑ or ↓ suffix
3. **Units**: Always include units in column headers
4. **Reference ranges**: Mention when a value crosses a clinical threshold

### Analysis Principles

1. **Lead with conclusion, then evidence** — state the judgment first, then support with data
2. **Trend over snapshot** — a single value means less than the direction of change
3. **Cross-reference systems** — e.g., ultrasound findings + hormone levels tell a combined story
4. **Distinguish signal from noise** — not every lab fluctuation is clinically meaningful
5. **Flag what's missing** — identify monitoring gaps explicitly
6. **Source attribution** at end: distinguish local evidence vs model judgment vs external sources

### Medication Analysis

When medication changes occur:
1. List old vs new regimen in a comparison table
2. Explain the clinical reasoning behind the change
3. Note any discrepancies between patient report and medical record
4. Flag safety monitoring needs for new medications
