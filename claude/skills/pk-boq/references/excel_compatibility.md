# Office Excel 兼容性关键规则

## 核心原则

**优先使用 xlsxwriter 新建文件**，避免 openpyxl 修改现有文件，防止触发 Office Excel 修复模式。

## 已知问题

### merge_cells + PatternFill → 修复模式

openpyxl 的合并单元格与 PatternFill 组合使用时，Excel 打开会触发"文件已损坏，是否修复"提示。

**症状**：打开文件 → Office 提示修复 → 修复后合并单元格丢失或有灰色背景

**解决方案**：
1. 使用 xlsxwriter 从头写（推荐）
2. 如需用 openpyxl：先 style 所有单元格 → 再 merge → 仅设置 top-left 值
3. 避免 `merge_cells` + `PatternFill` 同时使用

### write_blank 风险

xlsxwriter 的 `write_blank()` 写入空单元格可能导致 Excel 兼容性警告。

**建议**：跳过空单元格，不写任何内容，而非写入空格式。

## 库选择指南

| 场景 | 推荐 | 原因 |
|------|------|------|
| 新建 xlsx | xlsxwriter | Office 原生兼容 |
| 读取数据 | openpyxl (data_only=True) | 读公式结果 |
| 修改现有文件 | openpyxl | 唯一选择（谨慎使用） |
| 数据分析 | pandas | 便捷但公式丢失 |

## 验证方法

生成 xlsx 后，在 Microsoft Excel 中打开确认：
1. 无修复提示
2. 合并单元格正常显示
3. 样式（填充、字体、边框）完整
4. 数字格式正确
5. 行分组/大纲按钮可用
