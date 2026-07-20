# Outlook Pipeline 架构

## 数据流

```
Outlook (COM/MAPI)
  │
  ▼
outlook_com.py         ← 增量拉取，cursor 游标控制
  │  .msg originals + attachments + metadata.json
  ▼
{download_dir}/
  ├── inbox/2026-05/2026-05-28_Subject_eid1234/
  │   ├── original.msg
  │   ├── attachment.pdf
  │   └── metadata.json
  ├── sent/...
  ├── BQ/...           ← 自动发现的文件夹
  └── QUOTATION/...
  │
  ▼
outlook_classify.py    ← 规则分类 + 索引 + 快捷方式 + Junction
  │
  ▼
{download_dir}/
  ├── _index/          ← Markdown 索引（浏览器可看）
  │   ├── README.md
  │   ├── MEP/MEP.md
  │   ├── 内部/内部.md
  │   ├── 供应商/供应商.md
  │   └── 外部/外部.md
  ├── _shortcuts/      ← Windows .lnk 快捷方式（导航用）
  │   └── {top_level}/{sub_cat}/*.lnk
  └── _junctions/
      └── ByCategory/  ← NTFS Junction 目录联结（复制用）
          └── {top_level}/{sub_cat}/{email_dir}/
```

## 关键设计决策

### Cursor 增量拉取

每个 Outlook 文件夹维护独立 cursor，存储在 SQLite `{pipeline_dir}/db/state.sqlite`:

```
cursors 表:
  source           → "outlook_inbox", "outlook_sent", "outlook_BQ" ...
  position         → ISO timestamp of latest fetched email
  updated          → last update time
```

每次拉取: `[ReceivedTime] > cursor`，拉完后更新 cursor 为最新邮件时间。

### EntryID 去重

同一天同一主题的邮件可能是同一封（reply chain 中的不同副本）。优先保留带 EntryID 后缀的目录名（`_eid1234`），因为它可以精确关联 back to Outlook item。

### Junction 目录联结

`.lnk` 快捷方式不能复制原件。`_junctions/ByCategory/` 使用 NTFS `mklink /J` 创建目录联结：
- Windows 将其视为真实目录
- 可直接复制、拖拽、搜索、压缩
- 不占额外磁盘空间
- 删除 Junction 不影响原始文件

## 依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| `pywin32` | Outlook COM 接口 | `pip install pywin32` |
| `pyyaml` | 配置文件解析 | `pip install pyyaml` |
| Outlook 客户端 | COM 服务 | 需安装并登录 |

## 调度

- **Windows**: Windows Task Scheduler (`OutlookPipeline` 任务)
- **Linux/macOS**: systemd timer 或 crontab

管道间隔建议 30 分钟。拉取频率过高会被 Outlook 限流。
