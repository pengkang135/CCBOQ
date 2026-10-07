# 常见坑

| 坑 | 症状 | 修正 |
|---|---|---|
| 钢筋 t/kg 错位 | 单价 20,000 THB × 2.4M "kg" qty = 天文数字 | writeback 内建 fix: rebar 家族 unit=t 时 /1000 |
| 总计行有旧 AI 内容 | 报告总合价严重虚高 | writeback 显式清零总计行 O-W |
| 手工套价被覆盖 | 用户 L-N 列被清除 | writeback 检 N 是否 >0 (正数)，跳过 |
| DB name 空单位 | 单位相容度 0.3，被误排低 | retrieval 给空单位相容度不惩罚 |
| Gypsum board 命中 partition wall system | 单价 1800 THB/m2 (含骨架) 用到裸石膏板 (应 300-400) | Matcher prompt 明写 "系统价 vs 材料价" 区分 |
| DB 中英混排 | 英文描述搜不到中文 rate | 术语表预翻译 EN->CN 双路查 |
| 源文件行号漂移 | 用户实时编辑 -> row 移位 | 用 BQ Code (F 列) 稳定索引 |
| **中文 3 字产品名被误杀** | 止水带/天沟/水不漏搜不到 | 检索层改 `len < 2`（不用 `len < 4`） |
| **price_incl_tax str/float 混存** | 精确过滤匹配不到字符串 | 价格过滤用 `$in: [v, str(v)]` 双类型 |
| **price_incl_tax='nan' 坏记录** | NaN 绕过 price>0 过滤 | `price_num` 用 `math.isfinite(p)` 判定 |
| **中文只在 name_cn** | CN 正则只搜 name 漏掉 name_cn | 查询用 `$or: [{name: rx}, {name_cn: rx}]` |
| **country="??" 真实记录被过滤** | 2019 条泰国记录 country 是 "??" | country 过滤改 `$in: ["泰国", "??"]` |
| **查询无 sort 任意切片** | limit(20) 取插入序，全取旧价 | 每个 find 加 `.sort([("date", -1)])` |
| **domain map 覆盖不足** | 高频工艺类整类 no_match | 跑 `scripts/v4_recall_audit.py` 做死正则回归 |
| 系统价 vs 单板价误用 | 0.8mm 彩钢单板套 Sandwich Panel PIR 100mm @1765 | 规格差 >3x 时查更贴的候选；note 写明需市场复核 |
| **非 THB 价被标成 THB 写入** | LLM 选 USD 候选后直接写美元数 | 写回前按 matched_id 回查 currency；非 THB 用 fx.py 换算 |
| **_id 不支持 $regex 回查** | ObjectId 字段命中 0 条 | 带完整 `matched_full_id` 用 ObjectId 精确查 |
| **重复 BQ Code 覆盖** | 同描述两次出现，后项覆盖前项 | 写回时 row 缺失 -> 按 bq_code 复制补全 |
| **Excel O 列 NaN 陷阱** | `nan <= 0` 为 False -> 误判非 AI-todo | `num()` 判定 `f == f`（NaN 与自身不等）-> 返回 0 |
| **人民币恢复项混入** | Auditor 恢复项币种=人民币 | 恢复项必须检查 `new_matched_currency == "THB"` |
| **旧轮字段缺失** | 旧轮只在 reasoning 文本写价格 | 写回前从 reasoning 提取价格或标注"需人工复核" |
| **跨语言评分误配** | Rinsing Spray->Spray Paint 得 1.05 | 规则评分只排序不自动定案，疑难项交 LLM 裁决 |

## Domain Map 覆盖不足 — 系统性修复方法

### 为什么需要 Domain Map

BOQ 用正式规范英文（"Intumescent Fire-Resistive Coating"），DB rate 用务实工程英语或中文（"Paint to steel structure works; fire rate paint"）。fuzzy token 重叠 < 30%，rapidfuzz 阈值过滤会把正确项全部误杀。

**正确做法**：「BOQ 描述 trigger → DB 名称 regex」的领域同义词映射（`domain_synonym_map.json`）。每次语义匹配前先用 domain map 把 BOQ 描述翻译成 DB 侧的搜索词。

### 覆盖不足的典型症状与修复

| 症状 | 根因 | 修复 |
|---|---|---|
| 砂浆/找平/抹灰类全部 no_match | DOMAIN_MAP 无 mortar/screed/render/plaster 条目 | 新增：`trigger: mortar\|screed\|render\|plaster\|找平\|抹灰\|砂浆\|抗裂` |
| 止水带（中文 3 字）候选池只有英文 | `len(name) < 4` 过滤误杀中文 3 字产品名 | 过滤改 `len < 2` |
| 彩钢屋面板搜不到 sheet roof cladding | `roofing sheet` 命不中 `sheet roof cladding` | db_regex 扩展：`sheet roof\|roof cladding\|sandwich panel\|彩钢\|屋面板` |

**教训**：高频工艺类（砂浆、抹灰、找平、涂料、防水、保温）必须有独立 domain 条目。每次 no_match 先手工验证 DB 是否存在该数据，再判断是"真缺项"还是"检索覆盖不足"。

种子数据见 `domain_synonym_map.json`（48 条泰国 THB 池验证条目），含钢结构涂装、土方路基、混凝土模板、钢筋型钢、防水、防火门、金属屋面、洁具、瓷砖、砂浆找平、幕墙、XPS 等。
