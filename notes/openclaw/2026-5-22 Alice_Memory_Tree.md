# Alice 记忆框架 (2026-05-22)

## 总览

```mermaid
flowchart TB
    subgraph SOURCES["数据源"]
        direction LR
        WX[("微信消息\nwx-cli + wxdb MCP")]
        CC[("Claude Code 会话\nstaging/cc-*.json")]
        TG[("Telegram\nBot API")]
        GH[("GitHub\nIssues/PRs")]
        GM[("Gmail")]
    end

    subgraph PIPELINE["Memory Pipeline (每30min)"]
        direction TB
        FETCH["1. fetch\n多源采集器"]
        CANON["2. canonicalize\n路由到 Threaded JSON"]
        CHUNK["3. chunk\nSHA-256 去重分块"]
        WRITE["4. store\n写入 Librarian vault"]
        BUCKET["5. bucket-seal\n累积阈值触发"]
        EVAL["6. evaluate\nDeepSeek LLM 记忆提取"]

        FETCH --> CANON --> CHUNK --> WRITE --> BUCKET --> EVAL
    end

    subgraph VAULTS["Librarian Vaults"]
        direction LR
        V1[("Kevin Knowledge Hub\n~/.claude/knowledge/")]
        V2[("Feynman Library\nF:/FeynmanLibrary/")]
        V3[("名片库\n~/.claude/business-cards/")]
        V4[("百度同步盘\nF:/BaiduSyncdisk/")]
    end

    subgraph LIBRARIAN["Librarian CLI"]
        direction LR
        SQLITE[("SQLite + FTS5")]
        VECTOR[("Vector\nembedding")]
        CLI["librarian.cmd\nhyb_search / vec_search\nmemory_list / get_excerpt"]
        SQLITE --- VECTOR --- CLI
    end

    subgraph OC_MEMORY["OpenClaw memory-core"]
        direction TB
        MAINDB[("main.sqlite")]
        LIGHT["Light Dreaming\n回溯3天, 相似度0.85"]
        DEEP["Deep Dreaming\n最低分0.4, 半衰10天"]
        REM["REM Dreaming\n模式强度 >= 0.7"]
        MAINDB --> LIGHT --> DEEP --> REM
    end

    subgraph ACTIVE["active-memory 插件"]
        direction LR
        RETRIEVE["会话启动时检索"]
        INJECT["注入 agent 上下文\npromptStyle: balanced"]
        RETRIEVE --> INJECT
    end

    subgraph CONSUMERS["消费者"]
        direction LR
        ALICE["Alice (OpenClaw)\n微信 + Telegram"]
        CC2["Claude Code\nIDE / CLI"]
    end

    SOURCES -->|"raw data"| PIPELINE
    PIPELINE -->|"markdown + 结构化记忆"| VAULTS
    VAULTS --> LIBRARIAN
    LIBRARIAN <-->|"检索"| ACTIVE
    OC_MEMORY <-->|"dreaming 记忆"| ALICE
    ACTIVE -->|"上下文注入"| ALICE
    CC2 -->|"会话归档"| CC
    CC2 <-->|"检索"| LIBRARIAN
```

## 数据流详解

```mermaid
sequenceDiagram
    participant CC as Claude Code
    participant STG as staging/
    participant PIPE as Memory Pipeline
    participant LIB as Librarian Vault
    participant OC as OpenClaw (Alice)
    participant WX as 微信用户

    Note over CC: 会话结束
    CC->>STG: 写入 cc-{session_id}.json

    Note over PIPE: cron 每30min触发
    PIPE->>STG: StagingFetcher 扫描
    PIPE->>PIPE: canonicalize 转 Threaded JSON
    PIPE->>PIPE: chunk SHA-256 去重
    PIPE->>LIB: store 写入 vault
    PIPE->>PIPE: bucket-seal 累积判断
    PIPE->>PIPE: evaluate DeepSeek 提取记忆

    WX->>OC: 发送消息
    OC->>OC: memory-core dreaming 检索
    OC->>LIB: active-memory 检索相关知识
    LIB->>OC: 返回记忆上下文
    OC->>WX: 回复(注入记忆上下文)
```

## 记忆层级

```mermaid
graph LR
    subgraph L1["L1: 原始数据"]
        RAW["微信消息 / CC会话 / Telegram\n未处理, 仅存储"]
    end

    subgraph L2["L2: 结构化归档"]
        THREAD["Threaded JSON\n标准化格式, 时间线组织"]
    end

    subgraph L3["L3: 去重分块"]
        CHUNK["Content Chunks\nSHA-256 幂等, 可检索"]
    end

    subgraph L4["L4: 语义记忆"]
        SEM["结构化记忆\nLLM 提取, 置信度评分"]
    end

    subgraph L5["L5: Dreaming 记忆"]
        DREAM["Pattern Memory\n关联模式, 习惯, 偏好"]
    end

    L1 -->|"Pipeline: canonicalize"| L2
    L2 -->|"Pipeline: chunk"| L3
    L3 -->|"Pipeline: evaluate"| L4
    L4 -->|"memory-core: dreaming"| L5
```

## 关键参数

| 组件 | 参数 | 值 |
|------|------|-----|
| **Memory Pipeline** | 执行频率 | 每30分钟 (cron: `7,37 * * * *`) |
| | Bucket-Seal 触发阈值 | 10条消息 / 5000 tokens / 60分钟 |
| | 去重方式 | SHA-256 内容哈希 |
| | 状态数据库 | `~/.openclaw/memory-pipeline/db/state.sqlite` |
| **memory-core Light** | 回溯天数 | 3天 |
| | 去重相似度阈值 | 0.85 |
| **memory-core Deep** | 最低评分 | 0.4 |
| | 记忆半衰期 | 10天 |
| **memory-core REM** | 模式强度阈值 | 0.7 |
| **active-memory** | 注入时机 | 每次会话启动 (contextInjection: always) |
| | promptStyle | balanced |
| | 适用会话类型 | direct + group |
| **Librarian** | 检索方式 | 混合检索 (关键词 FTS5 + 语义向量) |
| | Vault 数量 | 4个 |
