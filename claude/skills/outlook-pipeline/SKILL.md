---
name: outlook-pipeline
description: "Outlook 邮件自动归档与分类管道。部署、管理、维护 Outlook 邮件管道，包含 COM 拉取、规则分类、Markdown 索引、快捷方式、Junction 目录联结。当用户要部署/配置/诊断/修改 Outlook 邮件管道，或对邮件处理提出需求时使用。触发词：Outlook 管道、邮件归档、部署邮件、邮件自动分类、outlook pipeline、邮件管道配置、重新分类邮件、修改分类规则。"
---

# Outlook Email Pipeline

## 决策树

```
用户提到 Outlook 邮件管道
│
├── "部署" / "安装" / "配置" / "setup" / "deploy"
│   └── → 运行 scripts/deploy.py 交互式部署
│
├── "重新分类" / "重建索引" / "快捷方式"
│   └── → 手动执行单次分类：
│         cd {pipeline_dir} && python outlook_classify.py
│
├── "改规则" / "添加关键词" / "修改分类"
│   └── → 编辑 {pipeline_dir}/pipeline_config.yaml → classification 块
│         然后重新分类验证
│
├── "重置" / "重新拉取" / "cursor"
│   └── → 见 references/operations.md 的 cursor 管理
│
├── "诊断" / "不工作了" / "报错" / "检查"
│   └── → python scripts/deploy.py --validate --pipeline-dir {dir}
│
├── "卸载" / "删除管道"
│   └── → python scripts/deploy.py --uninstall --pipeline-dir {dir}
│
└── "架构" / "怎么工作的" / "目录结构"
    └── → 读 references/architecture.md
```

## 日常运维速查

部署后，管道自动运行（Windows Task Scheduler / systemd timer）。日常最常用的操作：

```bash
# 查看分类索引（浏览器打开）
{download_dir}/_index/README.md

# 手动触发一次完整管道
cd {pipeline_dir} && python pipeline.py

# 只重新分类（不拉新邮件）
cd {pipeline_dir} && python outlook_classify.py

# 检查管道状态
python scripts/deploy.py --validate --pipeline-dir {pipeline_dir}
```

## 改分类规则

编辑 `{pipeline_dir}/pipeline_config.yaml` 中的 `classification` 块，然后运行：

```bash
cd {pipeline_dir} && python outlook_classify.py
```

规则立刻生效。详细规则体系见 [references/classification-rules.md](references/classification-rules.md)。

## 路径约定

| 内容 | 默认路径 |
|------|----------|
| 管道脚本 | `~/.outlook-pipeline/` |
| 配置文件 | `~/.outlook-pipeline/pipeline_config.yaml` |
| 邮件归档 | `~/OutlookArchive/` (部署时可改) |
| 索引输出 | `{download_dir}/_index/` |
| 快捷方式 | `{download_dir}/_shortcuts/` |

## 共享部署

将此 skill 分享给他人后，对方只需：

```bash
python scripts/deploy.py
```

按提示填入公司域名、内部人员名、自定义关键词，5 分钟内完成部署。
