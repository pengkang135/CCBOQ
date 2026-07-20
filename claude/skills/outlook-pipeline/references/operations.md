# 日常运维操作

## 触发方式

管道自动运行，也可手动触发：

```bash
# 完整管道（拉取 + 分类）
cd ~/.outlook-pipeline && python pipeline.py

# 仅拉取
cd ~/.outlook-pipeline && python pipeline.py --fetch-only

# 仅分类
cd ~/.outlook-pipeline && python pipeline.py --classify-only
```

## 健康检查

```bash
python ~/.claude/skills/outlook-pipeline/scripts/deploy.py --validate --pipeline-dir ~/.outlook-pipeline
```

返回示例：
```json
{
  "config_exists": true,
  "scripts_present": ["outlook_com.py", "outlook_classify.py", "pipeline.py"],
  "scripts_missing": [],
  "cron_active": true,
  "python_deps_ok": true,
  "errors": []
}
```

## 查看日志

```bash
# Windows Task Scheduler 运行历史
schtasks /query /tn OutlookPipeline /v

# 手动运行输出
cd ~/.outlook-pipeline && python pipeline.py
```

## Cursor 管理

Cursor 存储在 `{pipeline_dir}/db/state.sqlite`。

```bash
# 查看所有 cursor
python -c "
import sqlite3
db = sqlite3.connect('db/state.sqlite')
for row in db.execute('SELECT * FROM cursors'):
    print(row)
"

# 重置某个文件夹 cursor（触发重新拉取）
python -c "
import sqlite3
db = sqlite3.connect('db/state.sqlite')
db.execute(\"UPDATE cursors SET position='2020-01-01' WHERE source='outlook_inbox'\")
db.commit()
db.close()
"

# 重置所有 cursor
python -c "
import sqlite3
db = sqlite3.connect('db/state.sqlite')
db.execute(\"UPDATE cursors SET position='2020-01-01'\")
db.commit()
db.close()
"
```

## 常见问题

### Outlook 未运行

`outlook_com.py` 需要 Outlook COM 接口。确保 Outlook 已登录运行。如 Outlook 不在前台，COM 也会自动启动它。

### pywin32 未安装

```bash
pip install pywin32
```

### 快捷方式未生成

仅 Windows 支持。确保 PowerShell 执行策略允许脚本。

### Junction 创建失败

需要管理员权限或启用开发者模式。如失败不影响其他功能，Junction 是可选特性。

### 邮件归档目录满了

`download_dir` 可选择同步目录（如 OneDrive/BaiduSyncdisk）。如空间不足，改为非同步目录或设置大盘：

```yaml
# pipeline_config.yaml
outlook:
  download_dir: D:/OutlookArchive
```

### 迁移到新机器

1. 复制 `~/.outlook-pipeline/pipeline_config.yaml` 到新机器
2. 运行 `python scripts/deploy.py` 并指向已有 config
3. 复制或同步 `download_dir` 到新位置
