# 三种记忆系统对比分析

> 2026-05-13，基于 FeynmanLibrary、OpenClaw 生态、Hermes Agent 的技术调研。

---

## 一、系统概况

| 系统 | 定位 | 核心理念 | 成熟度 |
|------|------|----------|--------|
| **FeynmanLibrary** | 个人知识库 (MCP) | 人策展的图书馆 —— 你决定什么值得存 | 生产可用 |
| **OpenClaw 生态** | Agent 记忆插件集 | 规则策展 —— 时间/频率/认知权重自动管理 | 社区活跃 |
| **Hermes Agent** | 自进化 Agent 框架 | Agent 策展 —— Agent 自己判断、提炼、改进 | 35.7k Star |

## 二、存储架构对比

| 维度 | FeynmanLibrary | OpenClaw (Noesis) | Hermes |
|------|:---|:---|:---|
| 全文检索引擎 | SQLite FTS5 (trigram) | LanceDB + BM25 | SQLite FTS5 |
| 向量存储 | sqlite-vec (BGE 512d) | LanceDB IVF-PQ | sqlite-vec (计划中) |
| 嵌入模型 | bge-small-zh-v1.5 | nomic-embed-text (768d) | all-MiniLM-L6-v2 (计划) |
| 知识图谱 | 无 | 实体关系 + 因果 | 无 (Honcho 可选) |
| 文件格式 | MD + 源文件 (SQLite) | MD + JSONL + LanceDB | MD + SQLite |
| 中文支持 | 原生 (trigram + bge-zh) | 依赖模型 | 依赖模型 |

## 三、记忆分层对比

```
FeynmanLibrary          OpenClaw (12层)          Hermes (3层)
──────────────          ───────────────          ────────────
Documents (源文件)       L0: LCM (运行时DAG)      会话记忆 (SQLite)
├── Passages (分块)      L1-3: 常驻文件 (身份/记忆)  ├── FTS5 全文索引
├── Sessions (对话)      L4: facts.db (结构化)     ├── 按需检索
├── Memory (记忆条目)     L5: Continuity (向量回忆)   └── 毫秒级
├── Skills (技能)        L5b: LightRAG (知识图谱)
└── PriceIndex (价格)    L10-13: 元认知管线

                        越上层越快, 越下层越深
```

## 四、检索能力对比

| 能力 | FeynmanLibrary | OpenClaw | Hermes |
|------|:---:|:---:|:---:|
| FTS5 全文搜索 | Y | Y (BM25) | Y |
| 向量语义搜索 | Y (可选) | Y (LanceDB) | 计划中 |
| 混合搜索 (RRF) | Y | Y (MMR 重排) | 计划中 |
| 时间衰减排序 | N | Y | N |
| 认知权重排序 | N | Y (MemTier) | N |
| 交叉编码器重排 | N | Y (ClawMem) | 计划中 |
| 查询扩展 | N | Y (ClawMem) | N |
| 跨运行时检索 | N (仅 MCP) | Y (ClawMem) | N |

## 五、自我进化能力对比

| 能力 | FeynmanLibrary | OpenClaw | Hermes |
|------|:---:|:---:|:---:|
| 自动记忆提取 | N | Y (auto-capture) | Y (主动策划) |
| Skill 自主创建 | N (人工审批) | N | Y (自动提炼) |
| Skill 自改进 | N | N | Y (反馈回溯) |
| 用户建模 | N | N | Y (Honcho) |
| 跨会话模式识别 | N | Y (MemTier) | Y |
| 夜间深度分析 | N | Y (Cron 任务) | Y (内置 Cron) |
| 元认知 (反思自身) | N | Y (12层架构) | N |

## 六、遗忘策略对比

| 策略 | FeynmanLibrary | OpenClaw | Hermes |
|------|:---:|:---:|:---:|
| 遗忘机制 | 无 (人工清理) | 半衰期 + 反衰减 | 主动选择性遗忘 |
| 记忆上限 | 无硬限制 | 多数无限制 | 硬约束 (2200+1375字符) |
| 过期检测 | Y (check_stale) | Y (时间衰减) | N (硬上限自然淘汰) |
| 去重 | 仅文件路径 | SimHash+MinHash | 依赖 Agent 判断 |
| 归档 | N | Y (active→archive) | N |

## 七、文档摄入能力对比

| 能力 | FeynmanLibrary | OpenClaw | Hermes |
|------|:---:|:---:|:---:|
| PDF 摄入 | Y (3引擎fallback) | N | N |
| Office 文档 | Y (docx/xlsx/pptx) | N | N |
| HTML/EPUB | Y | N | N |
| 价格表提取 | Y (PDF表格→CSV→索引) | N | N |
| 自动监控目录 | N | N | N |
| 质量评估 | Y (启发式) | N | N |
| 处理器 fallback | Y (5引擎自动切换) | N | N |

## 八、部署和运维

| 维度 | FeynmanLibrary | OpenClaw | Hermes |
|------|:---:|:---:|:---:|
| 安装复杂度 | 中 (Python venv + 依赖) | 低 (npm install) | 中 (Python/Node 双运行时) |
| 外部依赖 | sentence-transformers, sqlite-vec | Ollama (可选) | fastembed (计划) |
| MCP 原生支持 | Y | N | 计划中 |
| 跨平台 | Windows/Mac/Linux | Mac/Linux 优先 | Mac/Linux 优先 |
| 多租户支持 | N | Y (Cortex) | N |
| 运营成本 | 本地免费 | 本地免费 | 本地免费 |

## 九、核心优劣势总结

### FeynmanLibrary
- 优势: 文档摄入能力碾压级领先, 中文原生支持, MCP 直接可用, 你完全掌控
- 劣势: 无自主记忆策划, 无自我进化, 无遗忘机制, 单项目绑定

### OpenClaw 生态
- 优势: 方案多样可选, 混合检索最成熟 (MMR + 交叉编码器 + 查询扩展), 社区活跃创新快
- 劣势: 方案碎片化 (选哪个?), 文档摄入能力弱, 中文支持不确定

### Hermes Agent
- 优势: 自进化飞轮是独有优势, 主动记忆策划最智能, 硬上限防止信息膨胀, 社区规模大
- 劣势: 不能替代 Claude Code 做工程, RAG 知识库还在开发, 中文嵌入方案未定

## 十、结论

三套系统不是替代关系，而是**互补关系**：

- **FeynmanLibrary** 做「知识存储和检索」—— 文档引擎、中文搜索
- **Hermes** 做「知识提炼和进化」—— 记忆策划、Skill 改进
- **OpenClaw 方案**可做「跨运行时记忆层」—— 如果将来同时用多个 Agent

当前最优策略：保留 FeynmanLibrary 的文档摄入和检索能力，借鉴 Hermes 的自进化设计理念逐步增强自主性，参考 OpenClaw 的混合检索技术提升搜索质量。
