---
name: wx-msg
description: Query the WeChat message database (ledger_v2.db) via wxdb MCP. Search messages, AI extractions (文件交换/联系方式/关键节点/材料设备/专业/技术要点), summaries, contacts. When user asks about WeChat chats, group messages, file shares, contact info, or recent activity — translate to SQL and answer.
---

# wx-msg — Alice 微信消息查询

## 数据库

通过 `mcp__wxdb__*` 工具查询 `F:\WXDashboard\data\ledger_v2.db`。

### 表结构速查

| 表 | 行数 | 关键列 |
|----|------|--------|
| messages | 2355 | sender, content, msg_time, msg_date, msg_type |
| groups | 42 | name, category, last_active_date, total_messages |
| ai_extractions | 907 | extract_type, content, group_id, generated_at |
| ai_summaries | 15 | date_range, summary_text, key_topics, group_id |
| contacts | ~100 | sender_name, display_name, company, phone, email |
| messages_fts | FTS | messages 全文索引 |

### ai_extractions.extract_type 值
`联系方式`, `关键节点`, `材料设备`, `文件交换`, `专业/技术要点`

## 常用查询

### "XXX公司发文件没有"
```
先用 ai_extractions WHERE extract_type='文件交换' AND content LIKE '%公司名%'
若无结果，再搜 messages WHERE content LIKE '%公司名%' AND msg_type LIKE '%文件%'
```

### 最新提取信息
```
SELECT e.extract_type, e.content, e.generated_at, g.name
FROM ai_extractions e JOIN groups g ON e.group_id = g.id
ORDER BY e.generated_at DESC LIMIT 30
```

### 某群最新消息
```
SELECT sender, content, msg_time FROM messages m
JOIN groups g ON m.group_id = g.id WHERE g.name LIKE '%群名%'
ORDER BY m.id DESC LIMIT 20
```

### 全文搜索
```
SELECT g.name, m.sender, m.content, m.msg_time
FROM messages m JOIN messages_fts fts ON m.id = fts.rowid
JOIN groups g ON m.group_id = g.id
WHERE messages_fts MATCH '关键词' ORDER BY m.id DESC LIMIT 30
```

### 摘要 / 活跃群 / 联系人
见完整版在 Librarian AgentSkills vault。

## 规则
- 始终 JOIN groups 显示群名
- 模糊匹配用 LIKE '%keyword%'，全文搜索用 FTS MATCH
- 默认 LIMIT 30
- 直接中文回答，不展示 raw SQL 结果
- 无结果时建议扩宽搜索
