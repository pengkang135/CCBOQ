---
name: pk-boq-review
description: 修改 BOQ 清单前的 HTML 预览审阅模式。把 xlsx 生成为 1:1 模拟清单格式的审阅稿（编号、英文描述、中文描述、单位 + 最右侧审阅意见列），用户在浏览器里改单元格、写意见、保存；AI 下一轮读回修改和意见后改出新版本 Excel。触发词：审阅稿、审阅模式、HTML 预览清单、大改清单、先在 HTML 上改、读审阅稿。
---

# pk-boq-review — 清单 HTML 审阅模式

只显示决定清单内容的四列，不显示工程量列。修改和意见保存在审阅稿内嵌的 `review-data` 里，一个文件就是完整记录。

## 用法

1. **生成**：`python ~/.claude/skills/pk-boq-review/scripts/review_html.py "<清单.xlsx>"`
   输出 `<清单名>_审阅稿.html`，在 xlsx 旁边。表头按 No./编号、Description、中文、Unit/单位 自动识别；识别不到加 `--sheet`。把路径告诉用户，用 Edge/Chrome 打开。
2. **审阅**（用户）：改单元格（删掉的字红色删除线、加的字蓝色下划线）；点行号把整行标为删除（整行红字删除线，再点撤销）；在最右列写意见；点"保存"。第一次保存在对话框里选中这份审阅稿，之后只询问是否覆盖。没保存前刷新页面不会丢。
3. **读回**：`python ~/.claude/skills/pk-boq-review/scripts/review_read.py "<审阅稿.html>"`
   输出删除行表、修改表和意见表；提示"源文件被改过"时先问用户再动手。
4. **改版**：按知识库「工作/概览.md · BOQ 编制约定」复制 vN 为 vN.1 再改，修改标黄、新增标绿、删除红字删除线；插行删行走 zip/XML 层（`~/.claude/skills/pk-boq/scripts/xlsx_rowops.py`），禁止 Excel COM。改完对新版本再生成审阅稿。
