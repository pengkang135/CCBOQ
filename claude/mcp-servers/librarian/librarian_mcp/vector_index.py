"""
sqlite-vec 向量索引模块
为 Librarian MCP 提供语义搜索能力，与现有 FTS5 全文索引互补
"""
from __future__ import annotations

import json
import os
import struct
from typing import Optional

import sqlite3
import sqlite_vec


DIM = 512


def _get_db_path() -> str:
    from librarian_mcp.config import get_config
    return str(get_config().db_path)


def load_vec(db: sqlite3.Connection) -> None:
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)


def ensure_vec_tables(db: sqlite3.Connection) -> None:
    load_vec(db)
    expected_dim = DIM
    for tbl in ("passage_vec", "memory_vec"):
        db.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {tbl} USING vec0(
                embedding FLOAT[{expected_dim}]
            )
        """)
        count = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        if count == 0:
            info = db.execute(f"PRAGMA table_info({tbl})").fetchall()
            for col in info:
                if col[1] == "embedding" and col[2]:
                    import re
                    m = re.search(r"FLOAT\[(\d+)\]", col[2])
                    if m and int(m.group(1)) != expected_dim:
                        db.execute(f"DROP TABLE IF EXISTS {tbl}")
                        db.execute(f"""
                            CREATE VIRTUAL TABLE {tbl} USING vec0(
                                embedding FLOAT[{expected_dim}]
                            )
                        """)
                    break


def _floats_to_blob(values: list[float]) -> bytes:
    return struct.pack("f" * len(values), *values)


def _blob_to_floats(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack("f" * count, blob))


def index_passage(db: sqlite3.Connection, passage_id: int, embedding: list[float]) -> None:
    """向向量索引写入一条 passage 的嵌入"""
    load_vec(db)
    blob = _floats_to_blob(embedding)
    db.execute(
        "INSERT OR REPLACE INTO passage_vec(rowid, embedding) VALUES (?, ?)",
        (passage_id, blob),
    )


def index_memory(db: sqlite3.Connection, memory_id: int, embedding: list[float]) -> None:
    """向向量索引写入一条 memory 的嵌入"""
    load_vec(db)
    blob = _floats_to_blob(embedding)
    db.execute(
        "INSERT OR REPLACE INTO memory_vec(rowid, embedding) VALUES (?, ?)",
        (memory_id, blob),
    )


def delete_passage_vec(db: sqlite3.Connection, passage_id: int) -> None:
    load_vec(db)
    db.execute("DELETE FROM passage_vec WHERE rowid = ?", (passage_id,))


def delete_memory_vec(db: sqlite3.Connection, memory_id: int) -> None:
    load_vec(db)
    db.execute("DELETE FROM memory_vec WHERE rowid = ?", (memory_id,))


def search_similar_passages(
    db: sqlite3.Connection,
    embedding: list[float],
    k: int = 10,
) -> list[dict]:
    """
    语义搜索最相似的 passages
    返回: [{"id": int, "distance": float, "vault_path": str, "snippet": str}, ...]
    """
    load_vec(db)
    blob = _floats_to_blob(embedding)
    rows = db.execute(
        """
        SELECT pv.rowid, pv.distance, d.vault_path, p.text
        FROM passage_vec pv
        JOIN passages p ON p.id = pv.rowid
        JOIN documents d ON d.id = p.document_id
        WHERE pv.embedding MATCH ? AND k = ?
        ORDER BY pv.distance
        """,
        (blob, k),
    ).fetchall()

    return [
        {
            "id": r[0],
            "distance": r[1],
            "vault_path": r[2],
            "snippet": r[3][:300] if r[3] else "",
        }
        for r in rows
    ]


def search_similar_passages_filtered(
    db: sqlite3.Connection,
    embedding: list[float],
    k: int = 10,
    path_prefix: Optional[list[str]] = None,
) -> list[dict]:
    """
    带路径过滤的语义搜索
    """
    load_vec(db)
    blob = _floats_to_blob(embedding)
    results = db.execute(
        """
        SELECT pv.rowid, pv.distance, d.vault_path, p.text
        FROM passage_vec pv
        JOIN passages p ON p.id = pv.rowid
        JOIN documents d ON d.id = p.document_id
        WHERE pv.embedding MATCH ? AND k = ?
        ORDER BY pv.distance
        """,
        (blob, k * 3),
    ).fetchall()

    filtered = []
    for r in results:
        if path_prefix:
            if not any(r[2].startswith(p) for p in path_prefix):
                continue
        filtered.append({
            "id": r[0],
            "distance": r[1],
            "vault_path": r[2],
            "snippet": r[3][:300] if r[3] else "",
        })
        if len(filtered) >= k:
            break
    return filtered


def search_similar_memories(
    db: sqlite3.Connection,
    embedding: list[float],
    k: int = 5,
) -> list[dict]:
    """
    语义搜索最相关的长期记忆
    """
    load_vec(db)
    blob = _floats_to_blob(embedding)
    rows = db.execute(
        """
        SELECT mv.rowid, mv.distance, m.content
        FROM memory_vec mv
        JOIN memory_entries m ON m.id = mv.rowid
        WHERE mv.embedding MATCH ? AND k = ?
        ORDER BY mv.distance
        """,
        (blob, k),
    ).fetchall()

    return [
        {"id": r[0], "distance": r[1], "content": r[2][:300] if r[2] else ""}
        for r in rows
    ]


def hybrid_search(
    db: sqlite3.Connection,
    query_text: str,
    embedding: Optional[list[float]] = None,
    k: int = 10,
    path_prefix: Optional[list[str]] = None,
    fts_weight: float = 0.4,
    vec_weight: float = 0.6,
) -> list[dict]:
    """
    混合搜索：FTS5 关键词 + 向量语义
    结果合并去重，加权排序
    """
    fts_results = {}
    vec_results = {}

    # FTS5 关键词搜索
    prefix_clause = ""
    prefix_params = []
    if path_prefix:
        conditions = " OR ".join(
            ["d.vault_path LIKE ?" for _ in path_prefix]
        )
        prefix_clause = f"AND ({conditions})"
        prefix_params = [f"{p}%" for p in path_prefix]

    fts_rows = db.execute(
        f"""
        SELECT p.id, d.vault_path, p.text,
               bm25(passage_fts, 0.0, 0.75, 0.25) as score
        FROM passage_fts
        JOIN passages p ON p.id = passage_fts.passage_id
        JOIN documents d ON d.id = p.document_id
        WHERE passage_fts MATCH ? {prefix_clause}
        ORDER BY score
        LIMIT ?
        """,
        ([query_text] + prefix_params + [k * 2]),
    ).fetchall()

    max_fts_score = max((r[3] for r in fts_rows), default=1.0) or 1.0
    for r in fts_rows:
        fts_results[r[0]] = {
            "id": r[0], "vault_path": r[1], "snippet": r[2][:300] if r[2] else "",
            "fts_score": r[3] / max_fts_score,
        }

    # 向量语义搜索
    if embedding:
        vec_rows = search_similar_passages_filtered(
            db, embedding, k=k * 2, path_prefix=path_prefix
        )
        max_vec_dist = max((r["distance"] for r in vec_rows), default=1.0) or 1.0
        for r in vec_rows:
            vec_results[r["id"]] = {
                "id": r["id"], "vault_path": r["vault_path"],
                "snippet": r["snippet"],
                "vec_score": 1.0 - (r["distance"] / max_vec_dist),
            }

    # 合并、加权排序
    all_ids = set(fts_results.keys()) | set(vec_results.keys())
    merged = []
    for pid in all_ids:
        fts_s = fts_results.get(pid, {}).get("fts_score", 0.0)
        vec_s = vec_results.get(pid, {}).get("vec_score", 0.0)
        combined = fts_weight * fts_s + vec_weight * vec_s
        entry = fts_results.get(pid) or vec_results.get(pid)
        entry["combined_score"] = combined
        merged.append(entry)

    merged.sort(key=lambda x: x["combined_score"], reverse=True)
    return merged[:k]


def reindex_all_passages(db: sqlite3.Connection, embed_fn) -> dict:
    """
    重建所有 passage 的向量索引
    embed_fn: 接收 text 字符串，返回 list[float]
    """
    load_vec(db)
    db.execute("DELETE FROM passage_vec")
    passages = db.execute(
        "SELECT id, text FROM passages WHERE text IS NOT NULL AND text != ''"
    ).fetchall()

    indexed = 0
    errors = 0
    for pid, text in passages:
        try:
            embedding = embed_fn(text)
            index_passage(db, pid, embedding)
            indexed += 1
        except Exception:
            errors += 1

    return {"indexed": indexed, "errors": errors, "total": len(passages)}


def reindex_all_memories(db: sqlite3.Connection, embed_fn) -> dict:
    """重建所有 memory 的向量索引"""
    load_vec(db)
    db.execute("DELETE FROM memory_vec")
    memories = db.execute(
        "SELECT id, content FROM memory_entries WHERE content IS NOT NULL AND content != ''"
    ).fetchall()

    indexed = 0
    errors = 0
    for mid, content in memories:
        try:
            embedding = embed_fn(content)
            index_memory(db, mid, embedding)
            indexed += 1
        except Exception:
            errors += 1

    return {"indexed": indexed, "errors": errors, "total": len(memories)}


def get_vec_stats(db: sqlite3.Connection) -> dict:
    """获取向量索引统计"""
    load_vec(db)
    p_count = db.execute("SELECT COUNT(*) FROM passage_vec").fetchone()[0]
    m_count = db.execute("SELECT COUNT(*) FROM memory_vec").fetchone()[0]
    return {
        "passage_vec_count": p_count,
        "memory_vec_count": m_count,
        "dimension": DIM,
        "sqlite_vec_version": sqlite_vec.__version__,
    }
