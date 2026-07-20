---
name: "thinking-in-files"
description: "Enforces explicit file-based workflows (Thinking in Files) for complex tasks. Invoke when handling large data, long processes, or critical operations requiring verification."
---

# Thinking in Files (Meta-Skill)

This skill enforces a disciplined engineering mindset: **Don't calculate in your head; show your work in files.**

## 核心理念 (Core Philosophy)
让 Agent 从“脑算”（隐式上下文处理）转变为“打草稿”（显式文件处理）。
利用命令行工具（Bash/PowerShell）将复杂任务拆解为**可复现**、**可验证**、**可组合**的步骤。

## 适用场景 (When to Invoke)
**必须使用此 Skill 的情况：**
1.  **数据处理**：超出上下文窗口或一次性计算能力的日志分析、文本搜索（grep/Select-String）。
2.  **链式调用**：API 结果需要清洗、去重、过滤后再作为下一步输入的场景。
3.  **多媒体/文件操作**：视频剪辑（ffmpeg）、批量重命名、文件格式转换。
4.  **长流程任务**：需要保存中间状态，以便出错时回溯或调试的任务。
5.  **验证关键步骤**：当每一步的输出都必须被人工或脚本验证时。
6.  **Excel 文件理解与修改**：大型 Excel 文件先转为 JSON AST 中间格式再处理，避免反复打开 Excel 或全量读入上下文。优先使用 `document-ingest` 技能。

## Excel 文件推荐中间格式

处理大型/复杂 Excel 文件时，不要直接读 raw cell 或反复用 openpyxl。推荐流程：

```bash
# 1. 转为 JSON AST（中间格式，放在 temp/）
python .claude/skills/document-ingest/scripts/excel_to_ast.py "input.xlsx" \
    --mode semantic_analysis --sheet "Sheet1" -o temp/ast.json

# 2. 在中间格式上分析/推理
#    - AI 直接阅读 temp/ast.json 理解结构
#    - 编写 modification_plan.json 描述要改的单元格

# 3. 写回原文件
python .claude/skills/document-ingest/scripts/ast_to_excel.py "input.xlsx" \
    --plan temp/modification_plan.json -o output.xlsx
```

核心原则：Excel 文件大、格式复杂 → 先转 JSON → 在 JSON 上操作 → 精准写回。

## 操作规范 (Protocol)

### 1. 建立草稿区 (Workspace Prep)
在工作根目录创建 `temp/` 文件夹用于存放中间产物。如果已存在，清理旧文件（如需）。
```bash
mkdir -p temp/
```

### 2. 分步落地 (The Pipeline)
遵循 `Input -> Process -> File -> Verify -> Next Step` 的模式。
*   **禁止**：把所有文件内容读到 Context 里让 LLM 统计。
*   **必须**：用 grep/find/awk 等工具处理，把结果写入 `temp/xxx.txt`。

### 3. 中间验证 (Verification)
在执行下一步之前，**必须**读取中间文件的头部或统计信息，确保上一步成功。
```bash
# Example
head -n 5 temp/processed_data.txt
wc -l temp/processed_data.txt
```

### 4. 痕迹管理 (Cleanup)
任务结束后，询问用户是否保留 `temp/`。默认保留以便调试。

## 示例 (Examples)

### 场景：统计所有 Markdown 文件中的 "TODO"
**❌ 错误（隐式内存操作）**
读取所有 Markdown 文件内容到上下文，靠 LLM 寻找 "TODO" 并统计。
*弊端*：容易漏、无法验证、消耗大量 Token。

**✅ 正确（显式文件操作）**
1. **搜索落盘**：
   ```powershell
   Get-ChildItem -Recurse *.md | Select-String "TODO" > temp/todo_list.txt
   ```
2. **验证数据**：
   ```powershell
   Get-Content temp/todo_list.txt -TotalCount 5
   ```
3. **计算结果**：
   ```powershell
   (Get-Content temp/todo_list.txt).Count
   ```

## 为什么这样做？ (Why?)
*   **可复现 (Reproducible)**：同样的命令再跑一遍，结果一样。
*   **可验证 (Verifiable)**：模型不是凭“记忆”瞎编，而是基于实际文件。
*   **可组合 (Composable)**：利用管道（Pipe）将简单工具串联解决复杂问题。
