# 网络调研流程

## 前置条件

```bash
~/.kimi-webbridge/bin/kimi-webbridge status
# 确保 running: true + extension_connected: true
```

如未安装或未启动，按 `kimi-webbridge` skill 的 `references/operations.md` 处理。

## 会话管理

使用独立 session 名隔离调研标签页：
```
session: "stock-research-{公司拼音}"
```

所有操作发送到 `http://127.0.0.1:10086/command`。

## 调研步骤（按优先级）

### Step 1: 券商研报（优先级最高）

**目标网站**：东方财富研报中心 `https://data.eastmoney.com/report/`

**操作流程**：
1. navigate 到研报中心（newTab:true, group_title:"研报调研"）
2. snapshot 定位搜索框
3. fill 搜索框填入 `"{公司名}"`
4. click 搜索按钮
5. snapshot 获取研报列表
6. 对前 3-5 篇研报用 evaluate 提取：标题、机构、日期、评级、目标价、核心逻辑
7. 可选：click 进入单篇研报详情页，snapshot 提取关键段落

**信息提取要点**：
- 目标价与当前价的空间
- 评级（买入/增持/中性/减持/卖出）
- 盈利预测（未来2-3年营收/净利润预测值）
- 核心推荐逻辑
- 机构分歧点（不同机构评级差异大时需关注）

### Step 2: 行业分析

**方式A** — 东方财富行业板块：
- navigate 到 `https://data.eastmoney.com/bkzj/hy.html`
- 查找公司所属行业板块
- 查看行业整体估值、涨跌幅

**方式B** — 搜索引擎：
- navigate 到 `https://www.google.com` 或 `https://www.baidu.com`
- 搜索：`"{公司所在行业} 行业分析报告 2026"`
- snapshot 搜索结果，记录相关报告链接
- 打开2-3篇高质量行业报告，提取关键信息

**信息提取要点**：
- 行业市场规模与增速（近3年及预测）
- 竞争格局（CR3/CR5 及变化趋势）
- 政策环境（利好/利空政策）
- 技术变革方向
- 行业估值中枢

### Step 3: 雪球社区讨论

**操作流程**：
1. navigate 到 `https://xueqiu.com/`
2. snapshot 检查登录状态
3. 定位搜索框，填入 `"{公司股票代码}"` 如 `"SH603936"`
4. click 搜索，进入个股页面
5. snapshot 获取热门帖子列表
6. 点击2-3条最热帖子，snapshot 提取讨论内容
7. 关注：热门帖子的话题方向（多/空）、核心论据、关键质疑

**信息提取要点**：
- 主要多头论点（为什么看好）
- 主要空头论点（为什么不看好）
- 争议焦点（市场分歧最大的问题）
- 散户关注的话题（如分红、减持、新产品等）
- 大V观点（关注认证用户的深度分析）

### Step 4: 最新新闻与公告

**方式A** — 巨潮资讯网（官方公告）：
- navigate 到 `http://www.cninfo.com.cn/`
- 搜索公司公告（最新5条）

**方式B** — 搜索引擎：
- 搜索：`"{公司名} 最新公告 2026"` 或 `"{公司名} 新闻"`
- 关注：定增/配股、大股东增减持、重大合同、业绩预告修正、分红方案、高管变动

## 调研日志

全程记录调研日志，保存为 `{公司}_research_log.md`：

```markdown
# {公司名} 网络调研日志
> 调研时间：YYYY-MM-DD HH:MM

## 券商研报
| 机构 | 日期 | 评级 | 目标价 | 核心逻辑摘要 | 来源URL |
|------|------|------|--------|-------------|---------|

## 行业分析
| 主题 | 来源 | 关键发现 | URL |
|------|------|---------|-----|

## 雪球讨论
| 话题 | 作者 | 方向 | 核心观点 | URL |
|------|------|------|---------|-----|

## 新闻公告
| 日期 | 标题 | 类型 | 摘要 | URL |
|------|------|------|------|-----|
```

## 截图存档

关键页面截图保存到 `{中间格式目录}/_research_screenshots/`：

```bash
bash "C:\Users\Kevin\.claude\skills\kimi-webbridge\scripts\screenshot.sh" \
  -s stock-research-{公司} -f png
```

## 调研结束

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -d '{"action":"close_session","session":"stock-research-{公司}"}'
```

## Kimi-WebBridge 快速参考

| 操作 | curl 命令 |
|------|-----------|
| navigate | `{"action":"navigate","args":{"url":"...","newTab":true},"session":"..."}` |
| snapshot | `{"action":"snapshot","session":"..."}` |
| click | `{"action":"click","args":{"selector":"@e123"},"session":"..."}` |
| fill | `{"action":"fill","args":{"selector":"@e123","value":"text"},"session":"..."}` |
| evaluate | `{"action":"evaluate","args":{"code":"()=>document.title"},"session":"..."}` |
| screenshot | 使用 `screenshot.sh` 脚本，不直接调 API |
| close_session | `{"action":"close_session","session":"..."}` |
