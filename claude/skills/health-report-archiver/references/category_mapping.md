# Medical Document Classification

## Classification Rules

Identify document type from OCR content, then route to the correct archive subdirectory.

| Category | Directory | Key Identifiers in Text |
|----------|-----------|------------------------|
| 生殖内分泌与超声 | `01_生殖内分泌与超声/` | 超声、B超、彩超、CRL、孕囊、卵泡监测、子宫动脉、性激素六项、FSH、LH、E2、PRL、T、AMH |
| 免疫与凝血 | `02_免疫与凝血/` | 狼疮抗凝物、LA1/LA2、蛋白C、蛋白S、抗凝血酶Ⅲ、D-二聚体、血栓弹力图、TEG、TAT、PIC、血小板聚集、淋巴细胞亚群、CD4、CD8、NK细胞、免疫球蛋白、IgG、IgM、IgA、补体C3、C4、CRP、血沉、ESR、ANA、抗核抗体、抗磷脂抗体、T-SPOT、结核、PAI-1、同型半胱氨酸 |
| 妊娠激素 | `03_妊娠激素/` | HCG、β-HCG、孕酮、PRGE、雌二醇、妊娠三项、早孕三项、hCG破卵针 |
| 妇科微生态 | `04_妇科微生态/` | 白带、Nugent、清洁度、TCT、宫颈、阴道微生态、HPV |
| 全身综合体检 | `05_全身综合体检/` | 血常规、尿常规、肝功、肾功、血脂、血糖、HbA1c、糖化血红蛋白、维生素D、25-羟、铁蛋白、微量元素、甲状腺、TSH、FT3、FT4、心电图、乳腺、腹部超声、肿瘤标志物、CA125、生化全套 |
| 肠道与营养代谢 | `06_肠道与营养代谢/` | 肠漏、ZO-1、食物不耐受、IgG、肠道菌群、尿有机酸、线粒体、营养、B族维生素、辅酶Q10、叶酸代谢 |
| 其他专科 | `07_其他专科/` | 门诊病历、复诊病历、处方、诊断证明、出院小结、会诊记录 |
| 男科及遗传 | `08_男科及遗传/` | 精液、精子、染色体核型、CMA、WES、全外显子、PAI-1基因、叶酸代谢基因、胚胎染色体 |

## Ambiguous Documents

When a document spans multiple categories (e.g., a visit record that contains lab orders for multiple systems):

1. **Multi-page visit records**: Classify as `07_其他专科/` (outpatient records are comprehensive by nature)
2. **Single lab report with mixed tests**: Classify by the PRIMARY test type (first listed or most clinically significant)
3. **Prescription-only images**: Classify as `07_其他专科/`

## Category Discovery

If the archive uses different directory names or categories than listed above, adapt to the archive's actual structure. Read the archive's README.md or index file first to understand its layout.
