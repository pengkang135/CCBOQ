"""
批量重建向量索引 — bge-small-zh-v1.5 高性能版
用法: .venv/Scripts/python.exe -m librarian_mcp.scripts.vec_batch_reindex
"""
import sqlite3
import struct
import sys
import time
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(_PACKAGE_DIR))

from librarian_mcp.vector_index import load_vec, ensure_vec_tables
from librarian_mcp.embedding import encode_batch, dim

DB_PATH = "F:/FeynmanLibrary/.library/library.db"
BATCH_SIZE = 128
COMMIT_EVERY = 2000
TRUNC_CHARS = 512  # bge 对短文本效果最好，前 512 字含核心语义


def floats_to_blob(values):
    return struct.pack("f" * len(values), *values)


def main():
    t_start = time.time()

    print("Loading bge-small-zh-v1.5...", flush=True)
    test = encode_batch(["test"], batch_size=1)
    print(f"  dim={dim()} OK", flush=True)

    db = sqlite3.connect(DB_PATH)
    load_vec(db)
    ensure_vec_tables(db)

    total = db.execute(
        "SELECT COUNT(*) FROM passages WHERE text IS NOT NULL AND text != ''"
    ).fetchone()[0]
    print(f"Total passages: {total}", flush=True)

    # Drop old vec table and recreate (handles dimension change from 1024→512)
    db.execute("DROP TABLE IF EXISTS passage_vec")
    ensure_vec_tables(db)
    db.commit()

    rows = db.execute(
        "SELECT id, text FROM passages WHERE text IS NOT NULL AND text != ''"
    ).fetchall()
    print(f"Fetched {len(rows)} passages", flush=True)

    indexed = 0
    errors = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        ids = [r[0] for r in batch]
        texts = [r[1][:TRUNC_CHARS] for r in batch]

        try:
            embeddings = encode_batch(texts, batch_size=BATCH_SIZE)
        except Exception as e:
            print(f"  encode error at batch {i}: {e}", flush=True)
            errors += len(batch)
            continue

        for pid, emb in zip(ids, embeddings):
            blob = floats_to_blob(emb)
            db.execute(
                "INSERT OR REPLACE INTO passage_vec(rowid, embedding) VALUES (?, ?)",
                (pid, blob),
            )
        indexed += len(batch)

        if (indexed % COMMIT_EVERY) < BATCH_SIZE or indexed >= total:
            db.commit()
            elapsed = time.time() - t_start
            pct = indexed / total * 100
            rate = indexed / elapsed if elapsed > 0 else 0
            eta = (total - indexed) / rate if rate > 0 else 0
            print(f"  {indexed}/{total} ({pct:.1f}%) | {rate:.0f}/s | ETA {eta/60:.1f}min", flush=True)

    db.commit()

    count = db.execute("SELECT COUNT(*) FROM passage_vec").fetchone()[0]
    elapsed = time.time() - t_start
    print(f"\nDone! Indexed {count}/{total} passages in {elapsed/60:.1f} min", flush=True)
    print(f"Errors: {errors}", flush=True)
    db.close()


if __name__ == "__main__":
    main()
