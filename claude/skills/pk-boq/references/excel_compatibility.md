# Office Excel 兼容性关键规则

## 核心原则（库选择顺序）

1. **写文件（新建）→ `xlsxwriter`**（默认）
2. **读文件 → `fastexcel`**（默认，Rust 实现，比 openpyxl 快 9-16x）
3. **openpyxl 只在"必须读入现有 xlsx → 局部修改 → 写回"时使用**（如清单套价、写入单价到既有清单）

不允许"图省事"用 openpyxl 从零写文件——即使功能上能实现。

## 库选择速查

| 场景 | 首选 | 备注 |
|------|------|------|
| 新建 xlsx（导出清单/报表/价格表） | **xlsxwriter** | 生成的文件更接近 Excel 原生格式，规避渲染 bug |
| 读取数据（值/文本） | **fastexcel** | `fastexcel.read_excel(path).load_sheet_by_name(name).to_pandas()` |
| 读公式结果（value cache） | fastexcel 或 openpyxl `data_only=True` | fastexcel 支持 `formulas` 参数 |
| 读+改+回写现有文件 | openpyxl | 唯一选择，谨慎使用 |
| 大表批量数据分析 | fastexcel + pandas | 内存和速度都优 |
| 需要 Excel 求值/公式 API | formualizer | 确定性求值，不依赖 Excel.exe |

## 已知 openpyxl 写入问题

### 1. 黑条渲染 bug（严重）

**症状**：openpyxl 生成的 xlsx 打开后 Excel 窗口出现黑色条带，标签栏被挤没；即使关闭当前文件、重开 Excel 仍残留，必须 kill EXCEL.EXE 才恢复；关闭硬件图形加速无效。

**触发**：openpyxl 输出的 `workbook.xml` 缺少 Excel 期望的元数据（fileVersion/calcPr 等），触发 Excel 渲染管线退化路径，污染 GPU 缓冲区。

**根治**：改用 xlsxwriter。

### 2. merge_cells + PatternFill → 修复模式

**症状**：Excel 打开提示"文件已损坏，是否修复" → 修复后合并单元格丢失或有灰色背景。

**根治**：改用 xlsxwriter。若必须 openpyxl：先 style 所有单元格 → 再 merge → 仅设置 top-left 值。

### 3. workbookView 尺寸为 None

**症状**：Excel 打开后窗口位置异常（可能在屏外）。

**规避**：xlsxwriter 默认写入完整 view 参数，无此问题。

## xlsxwriter 使用注意

### 跳过空单元格

`write_blank()` 写入空单元格会引发 Excel 兼容性警告。空单元格干脆不写，或只在需要边框/背景时用 `write_blank(row, col, None, fmt)`。

### 只写不能读

xlsxwriter 是 write-only。任何"读现有文件"用 fastexcel；"读改写"用 openpyxl。

## 验证方法

生成 xlsx 后，在 Microsoft Excel 中打开确认：
1. 无修复提示、无黑条
2. 合并单元格正常显示
3. 样式（填充、字体、边框）完整
4. 数字格式正确
5. 行分组/大纲按钮可用
6. 关闭 Excel 后再重开，仍无异常
