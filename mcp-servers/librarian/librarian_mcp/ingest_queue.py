"""
摄入队列 — 异步处理 PDF 等重文件，避免 MCP 同步超时。

轻量 PDF (< 10 页) 可以同步处理。重型 PDF 进入队列后台处理。
队列策略: 仅对标题和摘要做向量嵌入，正文仅做 FTS5 全文索引。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

from librarian_mcp.config import DB_PATH, VAULT_ROOT


QUEUE_POLL_INTERVAL = 2  # seconds between queue checks
WORKER_SHUTDOWN_TIMEOUT = 10  # seconds to wait for worker on shutdown


@dataclass
class QueueItem:
    id: str
    source_path: str
    processor: str
    title: Optional[str]
    force: bool
    external_root: Optional[str]
    status: str  # pending | processing | done | failed
    progress: str
    result_json: Optional[str]
    error: Optional[str]
    created_at: str
    updated_at: str


def _ensure_queue_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingest_queue (
            id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            processor TEXT NOT NULL DEFAULT 'auto',
            title TEXT,
            force INTEGER NOT NULL DEFAULT 0,
            external_root TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            progress TEXT NOT NULL DEFAULT '',
            result_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ingest_queue_status
        ON ingest_queue(status, created_at)
    """)
    conn.commit()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def queue_ingest(
    source_path: str,
    processor: str = "auto",
    title: Optional[str] = None,
    force: bool = False,
    external_root: Optional[str] = None,
) -> dict:
    """将摄入任务放入队列，立即返回 task_id。

    这是 MCP tool 的入口，必须快速返回（< 10ms）。
    """
    task_id = str(uuid.uuid4())[:8]
    now = _now_iso()

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        _ensure_queue_table(conn)
        conn.execute(
            """INSERT INTO ingest_queue (id, source_path, processor, title, force, external_root,
               status, progress, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', '', ?, ?)""",
            (task_id, source_path, processor, title, 1 if force else 0, external_root, now, now),
        )
        conn.commit()
        item = conn.execute("SELECT * FROM ingest_queue WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()

    return {
        "ok": True,
        "task_id": task_id,
        "status": "pending",
        "source_path": source_path,
        "message": f"Task {task_id} queued. Check status with ingest_status('{task_id}').",
    }


def ingest_status(task_id: str) -> dict:
    """查询摄入任务状态。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        _ensure_queue_table(conn)
        row = conn.execute(
            "SELECT * FROM ingest_queue WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"Task {task_id} not found"}

        result = dict(row)
        if result.get("result_json"):
            try:
                result["result"] = json.loads(result["result_json"])
            except json.JSONDecodeError:
                result["result"] = None
        del result["result_json"]
        return {"ok": True, **result}
    finally:
        conn.close()


def list_queue(status: Optional[str] = None, limit: int = 20) -> dict:
    """列出队列中的任务。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        _ensure_queue_table(conn)

        if status:
            rows = conn.execute(
                "SELECT * FROM ingest_queue WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ingest_queue ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        items = []
        for row in rows:
            item = dict(row)
            item.pop("result_json", None)
            items.append(item)

        return {"ok": True, "returned": len(items), "items": items}
    finally:
        conn.close()


def _run_worker_loop() -> None:
    """后台 worker：轮询队列，处理 pending 任务。

    在独立线程中运行。处理每个任务时：
    1. 文本提取 (markitdown/pandoc) — 同步
    2. FTS5 全文索引 — 同步
    3. 标题/摘要向量嵌入 — 仅在内容少时同步
    4. 全文段落向量嵌入 — 跳过（仅对大模型有意义的内容才做）
    """
    from librarian_mcp.ingest import SourceIngestService

    ingest_service = SourceIngestService()

    while not _worker_stop_event.is_set():
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            _ensure_queue_table(conn)
            row = conn.execute(
                """SELECT * FROM ingest_queue
                   WHERE status = 'pending'
                   ORDER BY created_at ASC LIMIT 1"""
            ).fetchone()

            if row is None:
                conn.close()
                _worker_stop_event.wait(QUEUE_POLL_INTERVAL)
                continue

            task_id = row["id"]
            source_path = row["source_path"]
            processor = row["processor"]
            title = row["title"]
            force = bool(row["force"])
            external_root = row["external_root"]
            now = _now_iso()

            conn.execute(
                "UPDATE ingest_queue SET status = 'processing', progress = 'Starting...', updated_at = ? WHERE id = ?",
                (now, task_id),
            )
            conn.commit()
            conn.close()

            try:
                conn = sqlite3.connect(str(DB_PATH))
                conn.row_factory = sqlite3.Row
                conn.execute(
                    "UPDATE ingest_queue SET progress = 'Extracting text...', updated_at = ? WHERE id = ?",
                    (_now_iso(), task_id),
                )
                conn.commit()
                conn.close()

                result = ingest_service.ingest_source(
                    source_path=source_path,
                    processor=processor,
                    title=title,
                    force=force,
                    external_root=external_root,
                )

                conn = sqlite3.connect(str(DB_PATH))
                conn.row_factory = sqlite3.Row
                now = _now_iso()
                if result.get("ok"):
                    conn.execute(
                        "UPDATE ingest_queue SET status = 'done', progress = 'Complete', result_json = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(result, default=str), now, task_id),
                    )
                else:
                    error_msg = result.get("error", {}).get("message", str(result.get("error", "Unknown error")))
                    conn.execute(
                        "UPDATE ingest_queue SET status = 'failed', progress = 'Failed', error = ?, result_json = ?, updated_at = ? WHERE id = ?",
                        (error_msg, json.dumps(result, default=str), now, task_id),
                    )
                conn.commit()
                conn.close()

            except Exception as exc:
                conn = sqlite3.connect(str(DB_PATH))
                conn.row_factory = sqlite3.Row
                now = _now_iso()
                conn.execute(
                    "UPDATE ingest_queue SET status = 'failed', progress = 'Error', error = ?, updated_at = ? WHERE id = ?",
                    (str(exc), now, task_id),
                )
                conn.commit()
                conn.close()

        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            _worker_stop_event.wait(QUEUE_POLL_INTERVAL)


_worker_thread: Optional[threading.Thread] = None
_worker_stop_event = threading.Event()


def start_worker() -> None:
    """启动后台摄入 worker 线程。"""
    global _worker_thread, _worker_stop_event
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _worker_stop_event.clear()
    _worker_thread = threading.Thread(target=_run_worker_loop, daemon=True, name="ingest-worker")
    _worker_thread.start()


def stop_worker() -> None:
    """停止后台 worker 线程。"""
    global _worker_thread
    _worker_stop_event.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=WORKER_SHUTDOWN_TIMEOUT)
        _worker_thread = None


def worker_status() -> dict:
    """返回 worker 运行状态。"""
    return {
        "running": _worker_thread is not None and _worker_thread.is_alive(),
        "thread_name": _worker_thread.name if _worker_thread else None,
    }
