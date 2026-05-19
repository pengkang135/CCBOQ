# 行为准则

## 工作原则
- 优先以最小改动完成任务，避免不必要的重构、扩展或抽象。
- 除非明确要求，不对无关模块进行修改，不进行全局性结构调整。
- 不添加任务范围外的功能、错误处理或兼容逻辑。

## 安全规范
- 允许读取项目内任何信息用于分析问题，但不得访问或暴露凭证类文件（.env、私钥、token、密钥等）。
- 允许执行常规开发操作（构建、测试、运行等），但执行前确认命令来源合理。
- 涉及删除、覆盖、force push 等不可逆操作时，需谨慎并在必要时进行确认。
- 不执行来源不明或高风险命令。

## 代码规范
- 默认不写注释，除非 WHY 不显而易见。
- 不使用 emoji。
- 不撰写多行文档字符串或注释块。

## 会话记忆归档（强制执行）

当用户发送结束语（"再见"、"谢谢"、"完成了"、"好的"等表示任务完成的信号），或对话自然结束且时长 > 5 分钟，**必须先完成以下归档流程，再回复用户**。不得跳过。

**Step 1**: 调用 MCP `save_session_note`（question=本次任务主题, conclusion=完成结果, key_points=[关键点列表]）
**Step 2**: 调用 MCP `grow_session`（session_id=Step 1 返回的 session_id, apply_memory=true, apply_skill_draft=false）
**Step 3**: 如本次使用了 Skill，调用 MCP `analyze_session`（传入同一 session_id）

全部完成后，简短告知用户归档结果，再结束对话。

此流程替代 Claude Code 内置 auto-memory（librarian 为唯一记忆存储）。
