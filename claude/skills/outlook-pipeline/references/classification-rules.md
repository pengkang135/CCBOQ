# 分类规则体系

## 两级分类

```
一级 (Top Level)    二级 (Sub Category)
─────────────────   ──────────────────
MEP                  询价文件
                     报价文件
                     工程量清单
                     设计图纸
                     澄清往来
                     内部通知
                     其他

内部                  询价文件
                     报价文件
                     ...

供应商                询价文件
                     报价文件
                     ...

外部                  询价文件
                     报价文件
                     ...
```

## 一级分类逻辑

匹配优先级: MEP > 内部 > 供应商 > 外部

| 级别 | 收件箱判定 | 发件箱判定 |
|------|----------|----------|
| MEP | 标题/正文含 MEP 关键词 | 同收件箱 |
| 内部 | 发件人域名/姓名在 internal_domains/names 中 | 收件人域名/姓名匹配 |
| 供应商 | 标题/正文含报价/RFQ/tender 等关键词 | 同收件箱 |
| 外部 | 以上都不匹配（兜底） | 同收件箱 |

Sent 文件夹特殊处理：按收件人判定而非发件人。

## 二级分类逻辑

按 `subcategory_rules` 顺序逐项匹配标题+正文。不匹配时回退到附件文件名匹配（`attach_signals`）。

### 特殊规则：询价发出 vs 询价RFQ

当匹配到"询价文件"且发件人是 outgoing sender 时：

```
if 发件人是 outgoing_sender:
  if 标题含 Re/回复/转发/Fwd:
    if 附件含 quotation/报价/price list:
      → 报价文件 (有价值的互动回复)
    else:
      → 询价文件 (互动跟进)
  else:
    → 询价文件 (一次性广播)
else:
  → 询价文件 (外部询价)
```

### 特殊规则：询价文档自发送

当内部人员（outgoing_sender）发给自己/BCC 且标题匹配询价关键词 → 询价文件。

## 规则配置位置

所有规则在 `pipeline_config.yaml` → `classification` 块：

```yaml
classification:
  top_level_order: ["MEP", "内部", "供应商", "外部"]
  subcat_order: ["询价文件", "报价文件", "工程量清单", ...]
  mep_keywords: [...]
  internal_domains: ["@mycompany.com"]
  internal_names: ["Peng Kang", "张三"]
  subcategory_rules:
    询价文件: ["RFQ", "询价", ...]
    报价文件: ["quotation", "报价", ...]
    ...
  attach_signals:
    询价文件: ["询价", "RFQ", ...]
    ...
  outgoing_rfq_senders: ["Peng Kang", ...]
  reply_patterns: ["Re", "回复", ...]
  quotation_attach_patterns: ["quotation", "报价", ...]
```

## 新增/修改分类

1. 编辑 `pipeline_config.yaml` → `classification` → `subcategory_rules`
2. 添加新分类名和关键词
3. 将新分类名加入 `subcat_order` 列表
4. 运行 `python outlook_classify.py` 验证

不需要重启管道。下次 cron 触发自动使用新规则。
