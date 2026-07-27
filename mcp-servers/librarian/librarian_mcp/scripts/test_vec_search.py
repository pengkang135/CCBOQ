"""语义搜索验证脚本"""
import sys, os, json

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(_PACKAGE_DIR))

from librarian_mcp import embedding, vector_index as vi
import sqlite3

db = sqlite3.connect("F:/FeynmanLibrary/.library/library.db")

def short_path(full_path, depth=3):
    parts = full_path.replace("\\", "/").split("/")
    return "/".join(parts[-depth:]) if len(parts) > depth else full_path

test_queries = [
    ("砼强度", "FTS5匹配不到砼的同义词"),
    ("防水的施工工艺", "概念搜索——不含防水关键词也能找到"),
    ("钢筋 reinforcement", "跨语言搜索"),
    ("深基坑支护", "造价专业术语"),
]

for query, desc in test_queries:
    emb = embedding.encode(query)
    results = vi.search_similar_passages(db, emb, k=5)
    print(f"[{query}]  {desc}")
    for r in results:
        sim = 1 - r["distance"]**2 / 2  # L2 to cosine for normalized vectors
        print(f"  sim={sim:.3f}  {short_path(r['vault_path'])}")
    print()

# Hybrid search
print("[混凝土配合比]  Hybrid FTS5+Vec")
emb = embedding.encode("混凝土配合比")
results = vi.hybrid_search(db, "混凝土配合比", embedding=emb, k=5, fts_weight=0.3)
for r in results:
    parts = r["vault_path"].replace("\\", "/").split("/")
    print(f"  score={r['combined_score']:.3f}  {'/'.join(parts[-3:])}")

db.close()
print("\nAll validation complete!")
