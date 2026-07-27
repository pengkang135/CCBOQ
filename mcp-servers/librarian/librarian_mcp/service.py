from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable, Optional

import yaml

from librarian_mcp.config import (
    AGENT_SKILL_ROOT,
    DB_PATH,
    DEFAULT_INDEX_PREFIXES,
    ERROR_LOG_PATH,
    EXCLUDED_INDEX_PREFIXES,
    EXTERNAL_ROOTS,
    LIBRARY_DIR,
    MEMORY_FILE,
    MEMORY_INDEX_PATH,
    MEMORY_VAULT_DIR,
    SESSION_ROOT,
    SKILLS_INDEX_PATH,
    SKILLS_LIBRARY_DIR,
    SKILL_DRAFT_ROOT,
    SOURCE_NOTES_DIR,
    USER_FILE,
    VAULT_ROOT,
)

try:
    from librarian_mcp import embedding as _embedding
    from librarian_mcp import vector_index as _vi

    _HAS_EMBED = True
except ImportError:
    _HAS_EMBED = False

VERSION = "2.0"

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
INVALID_FILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def ok(tool: str, data: dict) -> dict:
    return {
        "ok": True,
        "tool": tool,
        "version": VERSION,
        "data": data,
        "error": None,
    }


def fail(tool: str, code: str, message: str, details: Optional[dict] = None) -> dict:
    return {
        "ok": False,
        "tool": tool,
        "version": VERSION,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


AUTO_REFRESH_INTERVAL = 180  # 3 minutes between auto-refresh checks


class LibrarianService:
    def __init__(self, vault_root: Path = VAULT_ROOT, db_path: Path = DB_PATH) -> None:
        self.vault_root = Path(vault_root)
        self.db_path = Path(db_path)
        self.library_dir = self.db_path.parent
        self.error_log_path = ERROR_LOG_PATH
        self._last_auto_refresh = 0.0

    def initialize(self) -> dict:
        self._ensure_dirs()
        with self._connect() as conn:
            self._init_schema(conn)
        return ok(
            "initialize",
            {
                "db_path": str(self.db_path),
                "vault_root": str(self.vault_root),
            },
        )

    def reindex(self, prefixes: Optional[list[str]] = None) -> dict:
        tool = "reindex_vault"
        self._ensure_dirs()
        index_prefixes = prefixes or list(DEFAULT_INDEX_PREFIXES)
        normalized_prefixes = [self._normalize_relative_path(prefix) for prefix in index_prefixes]
        scanned_paths = sorted(set(self._iter_markdown_paths(normalized_prefixes)))
        current_state = {path: self._file_mtime_iso(self.vault_root / path) for path in scanned_paths}
        indexed = 0
        skipped = 0
        deleted = 0
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                """
                SELECT vault_path, file_mtime
                FROM documents
                WHERE
            """
                + " OR ".join(["vault_path LIKE ?"] * len(normalized_prefixes)),
                [f"{prefix}%" for prefix in normalized_prefixes],
            ).fetchall()
            existing_state = {row["vault_path"]: row["file_mtime"] for row in rows}
            for vault_path, file_mtime in current_state.items():
                if existing_state.get(vault_path) == file_mtime:
                    skipped += 1
                    continue
                self._index_single_path(conn, vault_path)
                indexed += 1
            stale_paths = set(existing_state) - set(current_state)
            for vault_path in stale_paths:
                self._delete_document(conn, vault_path)
                deleted += 1
        return ok(
            tool,
            {
                "prefixes": normalized_prefixes,
                "scanned": len(scanned_paths),
                "indexed": indexed,
                "skipped": skipped,
                "deleted": deleted,
            },
        )

    def check_stale(self, prefixes: Optional[list[str]] = None) -> dict:
        tool = "check_stale"
        self._ensure_dirs()
        index_prefixes = prefixes or list(DEFAULT_INDEX_PREFIXES)
        normalized_prefixes = [self._normalize_relative_path(p) for p in index_prefixes]

        stale_docs: list[dict] = []
        with self._connect() as conn:
            self._init_schema(conn)
            clauses = " OR ".join(["d.vault_path LIKE ?"] * len(normalized_prefixes))
            rows = conn.execute(
                f"""
                SELECT d.id, d.title, d.vault_path, d.source_path, d.file_mtime, d.updated_at
                FROM documents d
                WHERE d.source_path IS NOT NULL
                  AND d.type = 'source_note'
                  AND ({clauses})
                """,
                [f"{p}%" for p in normalized_prefixes],
            ).fetchall()

            for row in rows:
                source_path = row["source_path"]
                if not source_path:
                    continue
                if source_path.startswith("@"):
                    resolved = self._resolve_external_path(source_path)
                    if resolved is None:
                        continue
                    source_file = Path(resolved)
                else:
                    source_file = self.vault_root / source_path

                if not source_file.exists():
                    stale_docs.append({
                        "vault_path": row["vault_path"],
                        "source_path": source_path,
                        "source_note_mtime": row["file_mtime"],
                        "source_file_mtime": None,
                        "status": "source_missing",
                        "title": row["title"],
                    })
                    continue

                try:
                    source_mtime = self._file_mtime_iso(source_file)
                except OSError:
                    continue

                if source_mtime > row["file_mtime"]:
                    stale_docs.append({
                        "vault_path": row["vault_path"],
                        "source_path": source_path,
                        "source_note_mtime": row["file_mtime"],
                        "source_file_mtime": source_mtime,
                        "status": "stale",
                        "title": row["title"],
                    })

        return ok(
            tool,
            {
                "prefixes": normalized_prefixes,
                "stale_count": len(stale_docs),
                "stale_documents": stale_docs,
            },
        )

    def _auto_refresh_if_needed(self) -> dict | None:
        """如果距离上次自动刷新超过 AUTO_REFRESH_INTERVAL 秒，执行增量 reindex。"""
        import time
        now = time.time()
        if now - self._last_auto_refresh < AUTO_REFRESH_INTERVAL:
            return None
        self._last_auto_refresh = now
        return self.reindex()

    def search_summaries(
        self,
        query: str,
        types: Optional[list[str]] = None,
        path_prefixes: Optional[list[str]] = None,
        limit: int = 5,
    ) -> dict:
        tool = "search_summaries"
        if not query.strip():
            return fail(tool, "INVALID_QUERY", "query must not be empty", {"field": "query"})
        limit = max(1, min(int(limit), 20))
        normalized_prefixes = [self._normalize_relative_path(prefix) for prefix in path_prefixes or []]
        self._ensure_dirs()
        with self._connect() as conn:
            self._init_schema(conn)
            count = conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
            if count == 0:
                return fail(tool, "INDEX_NOT_READY", "index is empty, run reindex first")
            is_list_mode = query.strip() == "*"
            if is_list_mode:
                sql = """
                    SELECT
                        d.title,
                        d.type,
                        d.vault_path,
                        d.source_path,
                        d.tags,
                        d.updated_at,
                        p.heading,
                        p.chunk_order,
                        p.text,
                        p.priority,
                        p.decay_score,
                        0 AS score
                    FROM documents d
                    JOIN passages p ON p.document_id = d.id
                    WHERE 1 = 1
                """
                params: list[object] = []
            else:
                sql = """
                    SELECT
                        d.title,
                        d.type,
                        d.vault_path,
                        d.source_path,
                        d.tags,
                        d.updated_at,
                        p.heading,
                        p.chunk_order,
                        p.text,
                        p.priority,
                        p.decay_score,
                        -bm25(passage_fts) AS score
                    FROM passage_fts
                    JOIN passages p ON p.id = passage_fts.passage_id
                    JOIN documents d ON d.id = p.document_id
                    WHERE passage_fts MATCH ?
                """
                params: list[object] = [query]
            if types:
                placeholders = ",".join(["?"] * len(types))
                sql += f" AND d.type IN ({placeholders})"
                params.extend(types)
            else:
                sql += " AND d.type != ?"
                params.append("skill_draft")
            if normalized_prefixes:
                clauses = []
                for prefix in normalized_prefixes:
                    clauses.append("d.vault_path LIKE ?")
                    params.append(f"{prefix}%")
                sql += " AND (" + " OR ".join(clauses) + ")"
            sql += " ORDER BY p.priority DESC, score DESC, p.decay_score DESC, d.updated_at DESC LIMIT ?"
            params.append(limit)
            if is_list_mode:
                rows = conn.execute(sql, params).fetchall()
            else:
                try:
                    rows = conn.execute(sql, params).fetchall()
                except sqlite3.OperationalError:
                    safe_query = self._make_safe_phrase_query(query)
                    params[0] = safe_query
                    try:
                        rows = conn.execute(sql, params).fetchall()
                    except sqlite3.OperationalError as exc:
                        return fail(tool, "INVALID_QUERY", "query could not be parsed by FTS5", {"query": query, "error": str(exc)})
                if not rows and not is_list_mode:
                    rows = self._fallback_like_search(conn, query, types, normalized_prefixes, limit)
        results = [self._row_to_passage_ref(row) for row in rows]
        for result in results:
            doc = result.get("document", {})
            if doc.get("type") != "source_note":
                continue
            source_path = doc.get("source_path")
            if not source_path:
                continue
            if source_path.startswith("@"):
                source_full = self._resolve_external_path(source_path)
                if source_full is None:
                    continue
                source_full = Path(source_full)
            else:
                source_full = self.vault_root / source_path
            if not source_full.exists():
                result["stale"] = True
                result["stale_reason"] = "source_missing"
                continue
            try:
                note_full = self.vault_root / doc["vault_path"]
                if note_full.exists():
                    source_mtime = self._file_mtime_iso(source_full)
                    note_mtime = self._file_mtime_iso(note_full)
                    if source_mtime > note_mtime:
                        result["stale"] = True
                        continue
            except OSError:
                pass
            result["stale"] = False
        return ok(
            tool,
            {
                "query": query,
                "returned": len(results),
                "has_more": len(results) == limit,
                "results": results,
            },
        )

    def query_material_price(
        self,
        material_name: str,
        path_prefixes: Optional[list[str]] = None,
        limit: int = 5,
    ) -> dict:
        tool = "query_material_price"
        if not material_name.strip():
            return fail(tool, "INVALID_QUERY", "material_name must not be empty", {"field": "material_name"})
        limit = max(1, min(int(limit), 20))
        normalized_prefixes = [self._normalize_relative_path(prefix) for prefix in path_prefixes or []]
        material_key = self._normalize_material_key(material_name)
        with self._connect() as conn:
            self._init_schema(conn)
            count = conn.execute("SELECT COUNT(*) AS count FROM price_index").fetchone()["count"]
            if count == 0:
                return fail(tool, "PRICE_INDEX_NOT_READY", "price index is empty, ingest table pdfs or run reindex first")
            sql = """
                SELECT *
                FROM price_index p
                WHERE (
                    p.material_name_key = ?
                    OR p.material_name_key LIKE ?
                    OR p.material_name LIKE ?
                    OR p.lookup_key LIKE ?
                )
            """
            params: list[object] = [
                material_key,
                f"{material_key}%",
                f"%{material_name.strip()}%",
                f"%{material_name.strip()}%",
            ]
            if normalized_prefixes:
                clauses = []
                for prefix in normalized_prefixes:
                    clauses.append("(COALESCE(p.source_path, p.source_note_path) LIKE ? OR p.source_note_path LIKE ?)")
                    params.extend((f"{prefix}%", f"{prefix}%"))
                sql += " AND (" + " OR ".join(clauses) + ")"
            sql += """
                ORDER BY
                    CASE
                        WHEN p.material_name_key = ? THEN 300
                        WHEN p.material_name_key LIKE ? THEN 200
                        WHEN p.material_name LIKE ? THEN 120
                        WHEN p.lookup_key LIKE ? THEN 80
                        ELSE 0
                    END DESC,
                    LENGTH(p.material_name) ASC,
                    p.updated_at DESC
                LIMIT ?
            """
            params.extend([material_key, f"{material_key}%", f"%{material_name.strip()}%", f"%{material_name.strip()}%", limit])
            rows = conn.execute(sql, params).fetchall()
        results = [self._price_row_to_ref(row) for row in rows]
        return ok(
            tool,
            {
                "material_name": material_name,
                "returned": len(results),
                "has_more": len(results) == limit,
                "results": results,
            },
        )

    def search_price_candidates(
        self,
        query: str,
        path_prefixes: Optional[list[str]] = None,
        limit: int = 5,
    ) -> dict:
        tool = "search_price_candidates"
        if not query.strip():
            return fail(tool, "INVALID_QUERY", "query must not be empty", {"field": "query"})
        limit = max(1, min(int(limit), 20))
        normalized_prefixes = [self._normalize_relative_path(prefix) for prefix in path_prefixes or []]
        material_key = self._normalize_material_key(query)
        with self._connect() as conn:
            self._init_schema(conn)
            count = conn.execute("SELECT COUNT(*) AS count FROM price_index").fetchone()["count"]
            if count == 0:
                return fail(tool, "PRICE_INDEX_NOT_READY", "price index is empty, ingest table pdfs or run reindex first")
            sql = """
                SELECT
                    p.*,
                    -bm25(price_fts) AS score
                FROM price_fts
                JOIN price_index p ON p.id = price_fts.record_id
                WHERE price_fts MATCH ?
            """
            params: list[object] = [self._escape_fts5_query(query)]
            if normalized_prefixes:
                clauses = []
                for prefix in normalized_prefixes:
                    clauses.append("(COALESCE(p.source_path, p.source_note_path) LIKE ? OR p.source_note_path LIKE ?)")
                    params.extend((f"{prefix}%", f"{prefix}%"))
                sql += " AND (" + " OR ".join(clauses) + ")"
            sql += """
                ORDER BY
                    CASE
                        WHEN p.material_name_key = ? THEN 300
                        WHEN p.material_name_key LIKE ? THEN 200
                        WHEN p.material_name LIKE ? THEN 120
                        ELSE 0
                    END DESC,
                    score DESC,
                    p.updated_at DESC
                LIMIT ?
            """
            params.extend([material_key, f"{material_key}%", f"%{query.strip()}%", limit])
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                safe_query = self._make_safe_phrase_query(query)
                params[0] = safe_query
                try:
                    rows = conn.execute(sql, params).fetchall()
                except sqlite3.OperationalError as exc:
                    return fail(tool, "INVALID_QUERY", "query could not be parsed by price FTS", {"query": query, "error": str(exc)})
        results = [self._price_row_to_ref(row) for row in rows]
        return ok(
            tool,
            {
                "query": query,
                "returned": len(results),
                "has_more": len(results) == limit,
                "results": results,
            },
        )

    def list_price_sources(
        self,
        material_name: Optional[str] = None,
        path_prefixes: Optional[list[str]] = None,
        limit: int = 10,
    ) -> dict:
        tool = "list_price_sources"
        limit = max(1, min(int(limit), 20))
        normalized_prefixes = [self._normalize_relative_path(prefix) for prefix in path_prefixes or []]
        with self._connect() as conn:
            self._init_schema(conn)
            count = conn.execute("SELECT COUNT(*) AS count FROM price_index").fetchone()["count"]
            if count == 0:
                return fail(tool, "PRICE_INDEX_NOT_READY", "price index is empty, ingest table pdfs or run reindex first")
            sql = """
                SELECT
                    p.source_name,
                    p.source_path,
                    p.source_note_path,
                    COUNT(*) AS record_count,
                    MAX(p.updated_at) AS updated_at
                FROM price_index p
                WHERE 1 = 1
            """
            params: list[object] = []
            if material_name and material_name.strip():
                material_key = self._normalize_material_key(material_name)
                sql += " AND (p.material_name_key = ? OR p.material_name_key LIKE ? OR p.material_name LIKE ?)"
                params.extend([material_key, f"{material_key}%", f"%{material_name.strip()}%"])
            if normalized_prefixes:
                clauses = []
                for prefix in normalized_prefixes:
                    clauses.append("(COALESCE(p.source_path, p.source_note_path) LIKE ? OR p.source_note_path LIKE ?)")
                    params.extend((f"{prefix}%", f"{prefix}%"))
                sql += " AND (" + " OR ".join(clauses) + ")"
            sql += """
                GROUP BY p.source_name, p.source_path, p.source_note_path
                ORDER BY record_count DESC, updated_at DESC
                LIMIT ?
            """
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        results = [
            {
                "source_name": row["source_name"],
                "source_path": row["source_path"],
                "source_note_path": row["source_note_path"],
                "record_count": row["record_count"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return ok(
            tool,
            {
                "material_name": material_name,
                "returned": len(results),
                "has_more": len(results) == limit,
                "results": results,
            },
        )

    def open_note(self, vault_path: str) -> dict:
        tool = "open_note"
        try:
            normalized_path = self._normalize_relative_path(vault_path)
        except ValueError:
            return fail(tool, "MISSING_VAULT_PATH", "vault_path must be a relative path", {"vault_path": vault_path})
        path = self.vault_root / normalized_path
        if path.exists():
            if path.suffix.lower() != ".md":
                return fail(tool, "NOTE_NOT_MARKDOWN", "vault_path must point to a markdown file", {"vault_path": normalized_path})
            try:
                content = path.read_text(encoding="utf-8")
            except OSError as exc:
                return fail(tool, "ACCESS_DENIED", "failed to read note", {"vault_path": normalized_path, "error": str(exc)})
            metadata, body = self._parse_markdown(content)
            document = self._build_document_ref(normalized_path, metadata, body, self._file_mtime_iso(path))
            return ok(
                tool,
                {
                    "document": document,
                    "content": content,
                    "content_length": len(content),
                },
            )
        # Fallback: 文件不存在时从 SQLite 重建内容
        with self._connect() as conn:
            self._init_schema(conn)
            doc_row = conn.execute(
                "SELECT id, title, type, tags, source_path, updated_at FROM documents WHERE vault_path = ?",
                (normalized_path,),
            ).fetchone()
            if not doc_row:
                doc_row = conn.execute(
                    "SELECT id, title, type, tags, source_path, updated_at FROM documents WHERE source_path = ?",
                    (normalized_path,),
                ).fetchone()
            if not doc_row:
                return fail(tool, "NOTE_NOT_FOUND", "vault_path does not exist", {"vault_path": normalized_path})
            passage_rows = conn.execute(
                "SELECT heading, chunk_order, text FROM passages WHERE document_id = ? ORDER BY chunk_order ASC",
                (doc_row["id"],),
            ).fetchall()
        tags = json.loads(doc_row["tags"]) if doc_row["tags"] else []
        body_parts: list[str] = []
        for p in passage_rows:
            heading = p["heading"]
            text = p["text"]
            if heading != doc_row["title"] and heading:
                body_parts.append(f"\n\n## {heading}\n\n{text}")
            else:
                body_parts.append(text)
        body = "\n\n".join(body_parts).strip()
        content = f"# {doc_row['title']}\n\n{body}\n"
        document = {
            "title": doc_row["title"],
            "type": doc_row["type"],
            "tags": tags,
            "vault_path": normalized_path,
            "source_path": doc_row["source_path"],
            "updated_at": doc_row["updated_at"],
        }
        return ok(
            tool,
            {
                "document": document,
                "content": content,
                "content_length": len(content),
                "reconstructed": True,
            },
        )

    def get_excerpt(self, vault_path: str, heading: Optional[str] = None, chunk_order: Optional[int] = None) -> dict:
        tool = "get_excerpt"
        if bool(heading) == bool(chunk_order):
            return fail(tool, "INVALID_EXCERPT_SELECTOR", "heading and chunk_order must be mutually exclusive")
        try:
            normalized_path = self._normalize_relative_path(vault_path)
        except ValueError:
            return fail(tool, "MISSING_VAULT_PATH", "vault_path must be a relative path", {"vault_path": vault_path})
        with self._connect() as conn:
            self._init_schema(conn)
            document_row = conn.execute(
                """
                SELECT id, title, type, vault_path, source_path, tags, updated_at
                FROM documents
                WHERE vault_path = ?
                """,
                (normalized_path,),
            ).fetchone()
            if not document_row:
                path = self.vault_root / normalized_path
                if not path.exists():
                    return fail(tool, "NOTE_NOT_FOUND", "vault_path does not exist", {"vault_path": normalized_path})
                self._index_single_path(conn, normalized_path)
                document_row = conn.execute(
                    """
                    SELECT id, title, type, vault_path, source_path, tags, updated_at
                    FROM documents
                    WHERE vault_path = ?
                    """,
                    (normalized_path,),
                ).fetchone()
            if heading:
                rows = conn.execute(
                    """
                    SELECT heading, chunk_order, text
                    FROM passages
                    WHERE document_id = ? AND heading = ?
                    ORDER BY chunk_order ASC
                    """,
                    (document_row["id"], heading),
                ).fetchall()
                if not rows:
                    return fail(tool, "HEADING_NOT_FOUND", "heading was not found", {"vault_path": normalized_path, "heading": heading})
                text = "\n\n".join(row["text"] for row in rows)
                result_chunk_order = None
                result_heading = heading
            else:
                row = conn.execute(
                    """
                    SELECT heading, chunk_order, text
                    FROM passages
                    WHERE document_id = ? AND chunk_order = ?
                    """,
                    (document_row["id"], chunk_order),
                ).fetchone()
                if not row:
                    return fail(tool, "CHUNK_NOT_FOUND", "chunk_order was not found", {"vault_path": normalized_path, "chunk_order": chunk_order})
                text = row["text"]
                result_chunk_order = row["chunk_order"]
                result_heading = row["heading"]
        return ok(
            tool,
            {
                "document": self._document_row_to_ref(document_row),
                "heading": result_heading,
                "chunk_order": result_chunk_order,
                "text": text,
                "text_length": len(text),
            },
        )

    def locate_source(self, vault_path: str) -> dict:
        tool = "locate_source"
        try:
            normalized_path = self._normalize_relative_path(vault_path)
        except ValueError:
            return fail(tool, "MISSING_VAULT_PATH", "vault_path must be a relative path", {"vault_path": vault_path})
        path = self.vault_root / normalized_path
        metadata = {}
        if path.exists():
            if path.suffix.lower() == ".md":
                try:
                    metadata, _ = self._parse_markdown(path.read_text(encoding="utf-8"))
                except OSError as exc:
                    return fail(tool, "ACCESS_DENIED", "failed to read note", {"vault_path": normalized_path, "error": str(exc)})
            source_path = self._normalize_optional_relative_path(metadata.get("source_path")) if metadata else None
            source_exists = False
            if source_path:
                if isinstance(source_path, str) and source_path.startswith("@"):
                    resolved = self._resolve_external_path(source_path)
                    source_exists = resolved is not None and Path(resolved).exists()
                else:
                    source_exists = (self.vault_root / source_path).exists()
            sibling_candidates = self._find_sibling_source_candidates(path)
            related_markdown = self._find_related_markdown_candidates(normalized_path)
            return ok(
                tool,
                {
                    "vault_path": normalized_path,
                    "source_path": source_path,
                    "source_exists": source_exists,
                    "sibling_candidates": sibling_candidates,
                    "related_markdown": related_markdown,
                },
            )
        # Fallback: 文件不存在时从 SQLite 读取 source_path
        with self._connect() as conn:
            self._init_schema(conn)
            doc_row = conn.execute(
                "SELECT source_path, title FROM documents WHERE vault_path = ?",
                (normalized_path,),
            ).fetchone()
            if not doc_row:
                doc_row = conn.execute(
                    "SELECT source_path, title FROM documents WHERE source_path = ?",
                    (normalized_path,),
                ).fetchone()
        if not doc_row:
            return fail(tool, "NOTE_NOT_FOUND", "vault_path does not exist", {"vault_path": normalized_path})
        source_path = doc_row["source_path"]
        source_exists = False
        resolved_source = None
        if source_path:
            if isinstance(source_path, str) and source_path.startswith("@"):
                resolved_source = self._resolve_external_path(source_path)
                source_exists = resolved_source is not None and Path(resolved_source).exists()
            else:
                full_path = self.vault_root / source_path
                source_exists = full_path.exists()
        return ok(
            tool,
            {
                "vault_path": normalized_path,
                "source_path": source_path,
                "source_exists": source_exists,
                "resolved_source": resolved_source,
                "sibling_candidates": [],
                "related_markdown": self._find_related_markdown_candidates(normalized_path),
                "reconstructed": True,
            },
        )

    def search_sessions(self, query: str, limit: int = 5) -> dict:
        tool = "search_sessions"
        if not query.strip():
            return fail(tool, "INVALID_QUERY", "query must not be empty", {"field": "query"})
        limit = max(1, min(int(limit), 20))
        with self._connect() as conn:
            self._init_schema(conn)
            sql = """
                SELECT
                    s.id,
                    COALESCE(s.session_key, CAST(s.id AS TEXT)) AS session_key,
                    COALESCE(s.title, s.question_summary, s.question) AS title,
                    COALESCE(s.source, 'session_note') AS source,
                    COALESCE(s.started_at, s.created_at) AS started_at,
                    COALESCE(s.ended_at, s.created_at) AS ended_at,
                    COALESCE(s.answer_summary, s.question_summary, s.question) AS summary,
                    -bm25(session_fts) AS score,
                    sm.content AS matched_content
                FROM session_fts
                JOIN session_messages sm ON sm.id = session_fts.message_id
                JOIN sessions s ON s.id = sm.session_id
                WHERE session_fts MATCH ?
                ORDER BY score DESC, s.created_at DESC
                LIMIT ?
            """
            params: list[object] = [query, max(limit * 5, 10)]
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                safe_query = self._make_safe_phrase_query(query)
                params[0] = safe_query
                try:
                    rows = conn.execute(sql, params).fetchall()
                except sqlite3.OperationalError as exc:
                    return fail(tool, "INVALID_QUERY", "query could not be parsed by session FTS", {"query": query, "error": str(exc)})
        deduped: dict[str, dict] = {}
        for row in rows:
            session_key = row["session_key"]
            if session_key in deduped:
                continue
            deduped[session_key] = {
                "session_id": session_key,
                "title": row["title"],
                "source": row["source"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "summary": row["summary"],
                "score": row["score"],
                "matched_content": row["matched_content"],
            }
            if len(deduped) >= limit:
                break
        results = list(deduped.values())
        return ok(
            tool,
            {
                "query": query,
                "returned": len(results),
                "has_more": len(results) >= limit and len(rows) > len(results),
                "results": results,
            },
        )

    def open_session(self, session_id: str) -> dict:
        tool = "open_session"
        if not session_id.strip():
            return fail(tool, "SESSION_NOT_FOUND", "session_id must not be empty", {"field": "session_id"})
        with self._connect() as conn:
            self._init_schema(conn)
            row = conn.execute(
                """
                SELECT
                    id,
                    COALESCE(session_key, CAST(id AS TEXT)) AS session_key,
                    title,
                    question,
                    question_summary,
                    answer_summary,
                    citations,
                    vault_path,
                    created_at,
                    started_at,
                    ended_at,
                    source
                FROM sessions
                WHERE session_key = ? OR CAST(id AS TEXT) = ?
                """,
                (session_id, session_id),
            ).fetchone()
            if not row:
                return fail(tool, "SESSION_NOT_FOUND", "session_id was not found", {"session_id": session_id})
            messages = conn.execute(
                """
                SELECT role, content, tool_name, tool_payload, created_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (row["id"],),
            ).fetchall()
        return ok(
            tool,
            {
                "session": {
                    "session_id": row["session_key"],
                    "title": row["title"],
                    "question": row["question"],
                    "question_summary": row["question_summary"],
                    "answer_summary": row["answer_summary"],
                    "citations": json.loads(row["citations"]) if row["citations"] else [],
                    "vault_path": row["vault_path"],
                    "created_at": row["created_at"],
                    "started_at": row["started_at"] or row["created_at"],
                    "ended_at": row["ended_at"] or row["created_at"],
                    "source": row["source"] or "session_note",
                },
                "messages": [
                    {
                        "role": item["role"],
                        "content": item["content"],
                        "tool_name": item["tool_name"],
                        "tool_payload": json.loads(item["tool_payload"]) if item["tool_payload"] else None,
                        "created_at": item["created_at"],
                    }
                    for item in messages
                ],
            },
        )

    def memory_write(
        self,
        action: str,
        target: str,
        content: Optional[str] = None,
        match: Optional[str] = None,
        source_session_id: Optional[str] = None,
    ) -> dict:
        tool = "memory_write"
        target_norm = target.strip().lower()
        if target_norm not in ("memory", "user"):
            return fail(tool, "INVALID_MEMORY_TARGET", "target must be memory or user", {"target": target})

        self._ensure_dirs()
        self._migrate_old_memories()

        content = (content or "").strip()
        match = (match or "").strip()
        index_entries = self._read_memory_index()
        timestamp = self._now_iso()

        if action == "add":
            if not content:
                return fail(tool, "INVALID_MEMORY_WRITE", "add requires content")
            if self._should_block_memory_content(content):
                return fail(tool, "MEMORY_WRITE_BLOCKED", "content is too temporary for persistent memory", {"content": content})
            title = re.sub(r'^#+\s*', '', content.split("\n")[0][:80].strip())
            slug = self._memory_slug(title)
            file_name = f"mem-{timestamp.replace(':', '').replace('-', '')[:14]}-{slug}.md"
            file_path = MEMORY_VAULT_DIR / file_name
            vault_rel = f"Librarian/Memory/{file_name}"
            frontmatter = self._make_memory_frontmatter(title, target_norm, [], source_session_id)
            file_path.write_text(frontmatter + content + "\n", encoding="utf-8")
            entry_id = str(len(index_entries) + 1)
            new_entry = {
                "id": entry_id,
                "title": title,
                "target": target_norm,
                "tags": [],
                "updated_at": timestamp,
                "vault_path": vault_rel,
            }
            self._append_memory_index(new_entry)
            index_entries.append(new_entry)
            status = "active"

        elif action == "replace":
            if not content or not match:
                return fail(tool, "INVALID_MEMORY_WRITE", "replace requires content and match")
            if self._should_block_memory_content(content):
                return fail(tool, "MEMORY_WRITE_BLOCKED", "content is too temporary for persistent memory", {"content": content})
            found = self._find_memory_by_match(match)
            if found is None:
                return fail(tool, "MEMORY_MATCH_NOT_FOUND", "match was not found in persistent memory", {"match": match, "target": target_norm})
            file_path = found["file"]
            old_entry = found["entry"]
            old_frontmatter, _ = self._parse_markdown(file_path.read_text(encoding="utf-8"))
            old_created_at = (old_frontmatter or {}).get("created_at")
            if isinstance(old_created_at, datetime):
                old_created_at = old_created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            title = re.sub(r'^#+\s*', '', content.split("\n")[0][:80].strip())
            frontmatter = self._make_memory_frontmatter(title, target_norm, old_entry.get("tags", []), source_session_id, created_at=old_created_at)
            file_path.write_text(frontmatter + content + "\n", encoding="utf-8")
            for e in index_entries:
                if e["vault_path"] == old_entry["vault_path"]:
                    e["title"] = title
                    e["updated_at"] = timestamp
                    break
            self._rewrite_memory_index(index_entries)
            status = "replaced"

        elif action == "remove":
            if not match:
                return fail(tool, "INVALID_MEMORY_WRITE", "remove requires match")
            found = self._find_memory_by_match(match)
            if found is None:
                return fail(tool, "MEMORY_MATCH_NOT_FOUND", "match was not found in persistent memory", {"match": match, "target": target_norm})
            file_path = found["file"]
            old_entry = found["entry"]
            if file_path.exists():
                file_path.unlink()
            index_entries = [e for e in index_entries if e["vault_path"] != old_entry["vault_path"]]
            self._rewrite_memory_index(index_entries)
            status = "removed"

        else:
            return fail(tool, "INVALID_MEMORY_ACTION", "action must be add, replace, or remove", {"action": action})

        with self._connect() as conn:
            self._init_schema(conn)
            conn.execute(
                "INSERT INTO memory_entries(target, content, source_session_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (target_norm, content, source_session_id, status, timestamp, timestamp),
            )
            if action != "remove":
                vault_rel = new_entry["vault_path"] if action == "add" else found["entry"]["vault_path"]
                title = content.split("\n")[0][:80].strip()
                self._index_memory_in_fts5(conn, title, vault_rel, content, [])
            else:
                vault_rel = old_entry["vault_path"]
                self._remove_memory_from_fts5(conn, vault_rel)
            conn.commit()

        return ok(
            tool,
            {
                "target": target_norm,
                "action": action,
                "entry_count": len(index_entries),
                "index": index_entries,
                "updated_at": timestamp,
            },
        )

    def memory_list(self, target: Optional[str] = None) -> dict:
        tool = "memory_list"
        self._ensure_dirs()
        self._migrate_old_memories()
        index_entries = self._read_memory_index()
        if target:
            target_norm = target.strip().lower()
            index_entries = [e for e in index_entries if e["target"] == target_norm]
        return ok(
            tool,
            {
                "vault_dir": "Librarian/Memory",
                "index_path": "Librarian/Memory/MEMORY_INDEX.md",
                "entry_count": len(index_entries),
                "note": "Use open_note on vault_path to read full content; use search_summaries to find memories by keyword.",
                "index": index_entries,
            },
        )

    def list_skills(
        self,
        query: Optional[str] = None,
        statuses: Optional[list[str]] = None,
        limit: int = 10,
    ) -> dict:
        tool = "list_skills"
        limit = max(1, min(int(limit), 20))
        self._ensure_dirs()
        with self._connect() as conn:
            self._init_schema(conn)
            if conn.execute("SELECT COUNT(*) AS count FROM skills").fetchone()["count"] == 0:
                self._rebuild_skill_index(conn, include_drafts=True)
            sql = """
                SELECT name, status, summary, vault_path, index_keywords, source_session_id, updated_at, version
                FROM skills
                WHERE 1 = 1
            """
            params: list[object] = []
            if statuses:
                placeholders = ",".join(["?"] * len(statuses))
                sql += f" AND status IN ({placeholders})"
                params.extend(statuses)
            if query and query.strip():
                sql += " AND (name LIKE ? OR summary LIKE ? OR index_keywords LIKE ?)"
                like = f"%{query.strip()}%"
                params.extend([like, like, like])
            sql += " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, updated_at DESC, name ASC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        results = [self._skill_row_to_ref(row) for row in rows]
        return ok(
            tool,
            {
                "query": query,
                "returned": len(results),
                "has_more": len(results) == limit,
                "results": results,
            },
        )

    def open_skill(self, vault_path: str) -> dict:
        return self.open_note(vault_path)

    def save_skill_draft(
        self,
        name: str,
        summary: str,
        keywords: Optional[list[str]] = None,
        applicable_when: Optional[list[str]] = None,
        preconditions: Optional[list[str]] = None,
        inputs: Optional[list[str]] = None,
        outputs: Optional[list[str]] = None,
        steps: Optional[list[str]] = None,
        checkpoints: Optional[list[str]] = None,
        failure_modes: Optional[list[str]] = None,
        source_session_id: Optional[str] = None,
    ) -> dict:
        tool = "save_skill_draft"
        self._ensure_dirs()
        title = f"技能草稿 - {name.strip()}"
        target_path = SKILL_DRAFT_ROOT / f"{self._sanitize_filename(title)}.md"
        frontmatter = {
            "title": title,
            "type": "skill_draft",
            "tags": ["skill", "draft"],
            "status": "draft",
            "updated": datetime.now(UTC).strftime("%Y-%m-%d"),
            "skill_name": name.strip(),
            "summary": summary.strip(),
            "keywords": keywords or [],
            "source_session_id": source_session_id,
            "version": "0.1.0",
        }
        content = self._render_skill_note(
            frontmatter=frontmatter,
            applicable_when=applicable_when or [],
            preconditions=preconditions or [],
            inputs=inputs or [],
            outputs=outputs or [],
            steps=steps or [],
            checkpoints=checkpoints or [],
            failure_modes=failure_modes or [],
        )
        try:
            target_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return fail(tool, "WRITE_FAILED", "failed to write skill draft", {"path": str(target_path), "error": str(exc)})
        relative_path = str(target_path.relative_to(self.vault_root)).replace("\\", "/")
        with self._connect() as conn:
            self._init_schema(conn)
            self._index_single_path(conn, relative_path)
            self._rebuild_skill_index(conn, include_drafts=True)
        return ok(
            tool,
            {
                "name": name.strip(),
                "status": "draft",
                "vault_path": relative_path,
                "indexed": True,
                "created_at": self._now_iso(),
            },
        )

    def promote_skill(self, draft_vault_path: str, target_name: Optional[str], change_summary: str) -> dict:
        tool = "promote_skill"
        try:
            normalized_draft_path = self._normalize_relative_path(draft_vault_path)
        except ValueError:
            return fail(tool, "INVALID_DRAFT_PATH", "draft_vault_path must be relative", {"draft_vault_path": draft_vault_path})
        draft_path = self.vault_root / normalized_draft_path
        if not draft_path.exists():
            return fail(tool, "SKILL_NOT_FOUND", "draft skill was not found", {"draft_vault_path": normalized_draft_path})
        metadata, body = self._parse_markdown(draft_path.read_text(encoding="utf-8"))
        skill_name = (target_name or metadata.get("skill_name") or metadata.get("title") or draft_path.stem).strip()
        skill_name = re.sub(r"^技能草稿\s*-\s*", "", skill_name).strip()
        active_path = AGENT_SKILL_ROOT / f"{self._sanitize_filename(skill_name)}.md"
        existing_version = None
        if active_path.exists():
            existing_meta, _ = self._parse_markdown(active_path.read_text(encoding="utf-8"))
            existing_version = existing_meta.get("version")
        version = self._next_skill_version(existing_version)
        frontmatter = {
            "title": skill_name,
            "type": "agent_skill",
            "tags": ["skill", "agent_skill"],
            "status": "active",
            "updated": datetime.now(UTC).strftime("%Y-%m-%d"),
            "skill_name": skill_name,
            "summary": metadata.get("summary") or self._extract_first_paragraph(body) or skill_name,
            "keywords": self._normalize_tags(metadata.get("keywords")),
            "source_session_id": metadata.get("source_session_id"),
            "version": version,
        }
        promoted_body = self._promote_skill_body(body, change_summary)
        content = self._render_markdown_with_frontmatter(frontmatter, promoted_body)
        try:
            active_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return fail(tool, "SKILL_PROMOTION_FAILED", "failed to write promoted skill", {"path": str(active_path), "error": str(exc)})
        relative_path = str(active_path.relative_to(self.vault_root)).replace("\\", "/")
        with self._connect() as conn:
            self._init_schema(conn)
            self._index_single_path(conn, relative_path)
            self._rebuild_skill_index(conn, include_drafts=True)
            skill_row = conn.execute("SELECT id FROM skills WHERE vault_path = ?", (relative_path,)).fetchone()
            if skill_row:
                conn.execute(
                    """
                    INSERT INTO skill_versions(skill_id, version, change_summary, vault_path, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (skill_row["id"], version, change_summary.strip(), relative_path, self._now_iso()),
                )
                conn.commit()
        return ok(
            tool,
            {
                "name": skill_name,
                "status": "active",
                "vault_path": relative_path,
                "version_tag": version,
                "indexed": True,
                "created_at": self._now_iso(),
            },
        )

    def rebuild_skill_index(self, include_drafts: bool = True) -> dict:
        tool = "rebuild_skill_index"
        self._ensure_dirs()
        with self._connect() as conn:
            self._init_schema(conn)
            results = self._rebuild_skill_index(conn, include_drafts=include_drafts)
        return ok(tool, results)

    def save_session_note(
        self,
        question: str,
        conclusion: str,
        key_points: Optional[list[str]] = None,
        citations: Optional[list[dict]] = None,
        model_judgement: Optional[str] = None,
        external_sources: Optional[list[dict]] = None,
        todo: Optional[list[str]] = None,
        auto_grow: bool = False,
        apply_memory: bool = False,
        apply_skill_draft: bool = False,
    ) -> dict:
        tool = "save_session_note"
        if not question.strip():
            return fail(tool, "INVALID_SESSION_PAYLOAD", "question must not be empty", {"field": "question"})
        if not conclusion.strip():
            return fail(tool, "INVALID_SESSION_PAYLOAD", "conclusion must not be empty", {"field": "conclusion"})
        self._ensure_dirs()
        day_folder = SESSION_ROOT / datetime.now(UTC).strftime("%Y-%m-%d")
        day_folder.mkdir(parents=True, exist_ok=True)
        title = f"问答归档 - {self._trim_title(question)}"
        filename = f"{self._sanitize_filename(title)}.md"
        target_path = day_folder / filename
        frontmatter = {
            "title": title,
            "type": "session_note",
            "tags": ["session"],
            "updated": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        content = self._render_session_note(
            frontmatter=frontmatter,
            question=question,
            conclusion=conclusion,
            key_points=key_points or [],
            citations=citations or [],
            model_judgement=model_judgement,
            external_sources=external_sources or [],
            todo=todo or [],
        )
        try:
            target_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return fail(tool, "WRITE_FAILED", "failed to write session note", {"path": str(target_path), "error": str(exc)})
        relative_path = str(target_path.relative_to(self.vault_root)).replace("\\", "/")
        try:
            with self._connect() as conn:
                self._init_schema(conn)
                self._index_single_path(conn, relative_path)
                session_key = self._create_session_key()
                created_at = self._now_iso()
                citations_json = json.dumps(citations or [], ensure_ascii=False)
                cursor = conn.execute(
                    """
                    INSERT INTO sessions(
                        session_key,
                        title,
                        question,
                        question_summary,
                        answer_summary,
                        citations,
                        vault_path,
                        created_at,
                        started_at,
                        ended_at,
                        source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_key,
                        title,
                        question,
                        self._trim_title(question),
                        conclusion,
                        citations_json,
                        relative_path,
                        created_at,
                        created_at,
                        created_at,
                        "session_note",
                    ),
                )
                session_row_id = cursor.lastrowid
                self._insert_session_message(conn, session_row_id, session_key, "user", question)
                assistant_parts = [conclusion]
                if key_points:
                    assistant_parts.append("要点：\n" + self._render_bullets(key_points))
                if model_judgement:
                    assistant_parts.append("模型判断：\n" + model_judgement)
                if external_sources:
                    assistant_parts.append("外部来源：\n" + self._render_citations(external_sources))
                self._insert_session_message(conn, session_row_id, session_key, "assistant", "\n\n".join(part for part in assistant_parts if part.strip()))
                conn.commit()
        except Exception as exc:
            return fail(tool, "INDEX_UPDATE_FAILED", "session note was written but indexing failed", {"vault_path": relative_path, "error": str(exc)})
        result = {
            "vault_path": relative_path,
            "title": title,
            "created_at": created_at,
            "indexed": True,
            "session_id": session_key,
        }
        if auto_grow:
            growth = self.grow_session(session_id=session_key, apply_memory=apply_memory, apply_skill_draft=apply_skill_draft)
            result["growth"] = growth.get("data") if growth.get("ok") else {"error": growth.get("error")}
        return ok(tool, result)

    def grow_session(self, session_id: str, apply_memory: bool = False, apply_skill_draft: bool = False) -> dict:
        tool = "grow_session"
        if not session_id.strip():
            return fail(tool, "SESSION_NOT_FOUND", "session_id must not be empty", {"field": "session_id"})
        session = self.open_session(session_id)
        if not session.get("ok"):
            return fail(tool, "SESSION_NOT_FOUND", "session_id was not found", {"session_id": session_id})
        payload = session["data"]
        session_key = payload["session"]["session_id"]
        question = payload["session"]["question"] or ""
        answer_summary = payload["session"]["answer_summary"] or ""
        messages = payload.get("messages") or []
        assistant_text = ""
        for item in messages:
            if item.get("role") == "assistant":
                assistant_text = item.get("content") or ""
        memory_candidates = self._suggest_memory_from_texts([question, answer_summary, assistant_text])
        skill_candidate = self._suggest_skill_from_texts(question=question, answer=assistant_text or answer_summary, source_session_id=session_key)
        applied_memory: list[dict] = []
        applied_skill: Optional[dict] = None
        if apply_memory:
            for content in memory_candidates:
                write_result = self.memory_write(action="add", target="memory", content=content, source_session_id=session_key)
                if write_result.get("ok"):
                    applied_memory.append({"target": "memory", "content": content})
        if apply_skill_draft and skill_candidate is not None:
            applied = self.save_skill_draft(**skill_candidate)
            if applied.get("ok"):
                applied_skill = applied.get("data")
        return ok(
            tool,
            {
                "session_id": session_key,
                "suggested_memory": [{"target": "memory", "content": item} for item in memory_candidates],
                "suggested_skill_draft": skill_candidate,
                "applied": {
                    "memory": applied_memory,
                    "skill_draft": applied_skill,
                },
            },
        )

    def suggest_memories(self, session_id: str, include_conflicts: bool = False) -> dict:
        tool = "suggest_memories"
        if not session_id.strip():
            return fail(tool, "SESSION_NOT_FOUND", "session_id must not be empty", {"field": "session_id"})
        session = self.open_session(session_id)
        if not session.get("ok"):
            return fail(tool, "SESSION_NOT_FOUND", "session_id was not found", {"session_id": session_id})
        payload = session["data"]
        session_key = payload["session"]["session_id"]
        question = payload["session"]["question"] or ""
        answer_summary = payload["session"]["answer_summary"] or ""
        messages = payload.get("messages") or []
        assistant_text = ""
        user_texts: list[str] = []
        for item in messages:
            if item.get("role") == "assistant":
                assistant_text = item.get("content") or ""
            elif item.get("role") == "user":
                user_texts.append(item.get("content") or "")
        candidates = self._suggest_memory_from_texts([question, answer_summary, assistant_text] + user_texts)
        deduped: list[dict] = []
        conflicts: list[dict] = []
        for candidate in candidates:
            result = self._check_memory_novelty(candidate)
            if result.get("is_novel"):
                deduped.append({"content": candidate, "novelty_score": result.get("similarity", 0)})
            else:
                conflicts.append({"content": candidate, "similar_entry": result.get("match"), "similarity": result.get("similarity", 0)})
        return ok(tool, {
            "session_id": session_key,
            "suggested_memories": deduped,
            "total_candidates": len(candidates),
            "new_count": len(deduped),
            "conflict_count": len(conflicts),
            "conflicts": conflicts if include_conflicts else [],
        })

    def analyze_session(self, session_id: str) -> dict:
        tool = "analyze_session"
        if not session_id.strip():
            return fail(tool, "SESSION_NOT_FOUND", "session_id must not be empty", {"field": "session_id"})
        session = self.open_session(session_id)
        if not session.get("ok"):
            return fail(tool, "SESSION_NOT_FOUND", "session_id was not found", {"session_id": session_id})
        payload = session["data"]
        session_key = payload["session"]["session_id"]
        question = payload["session"]["question"] or ""
        answer_summary = payload["session"]["answer_summary"] or ""
        messages = payload.get("messages") or []
        tool_usages: dict[str, int] = {}
        user_turns = 0
        assistant_turns = 0
        error_indicators: list[str] = []
        for item in messages:
            role = item.get("role", "")
            content = item.get("content") or ""
            if role == "user":
                user_turns += 1
            elif role == "assistant":
                assistant_turns += 1
                for marker in ["error", "fail", "错误", "失败", "异常", "cannot", "unable", "not found"]:
                    if marker.lower() in content.lower():
                        if content.strip() not in error_indicators:
                            error_indicators.append(content[:200].strip())
            tool_calls = item.get("tool_calls") or []
            for tc in tool_calls:
                tool_name = tc.get("name") if isinstance(tc, dict) else str(tc)
                tool_usages[tool_name] = tool_usages.get(tool_name, 0) + 1
        patterns: list[str] = []
        if question and len(question) > 10:
            keywords = [w for w in ["搜索", "search", "查", "找", "翻译", "translate", "对比", "compare", "分析", "analyze", "提取", "extract", "合并", "merge"] if w in question]
            if keywords:
                patterns.append({"type": "task_type", "keywords": keywords, "question": question[:120]})
        wins: list[str] = []
        if assistant_turns > 0 and not error_indicators:
            wins.append("会话流畅，无明显错误")
        if answer_summary:
            wins.append(f"成功总结: {answer_summary[:120]}")
        pitfalls: list[dict] = []
        if error_indicators:
            for err in error_indicators[:3]:
                pitfalls.append({"severity": "warning", "description": err})
        top_tools = sorted(tool_usages.items(), key=lambda x: -x[1])[:5]
        memory_candidates = self._suggest_memory_from_texts([question, answer_summary])
        skill_candidate = self._suggest_skill_from_texts(question=question, answer=answer_summary, source_session_id=session_key)
        analysis = {
            "session_id": session_key,
            "summary": {
                "question": question[:200],
                "answer_summary": answer_summary[:200],
                "message_count": len(messages),
                "user_turns": user_turns,
                "assistant_turns": assistant_turns,
            },
            "patterns": patterns,
            "wins": wins,
            "pitfalls": pitfalls,
            "tool_usage": dict(top_tools),
            "suggestions": {
                "memory": [{"content": m} for m in memory_candidates],
                "skill_draft": skill_candidate,
            },
        }
        return ok(tool, analysis)

    def _check_memory_novelty(self, candidate: str) -> dict:
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT id, target, content FROM memory_entries WHERE status='active' ORDER BY id DESC LIMIT 50"
                ).fetchall()
            finally:
                conn.close()
        except Exception:
            return {"is_novel": True, "similarity": 0}
        best_sim = 0.0
        best_match = None
        candidate_norm = candidate.strip().lower()
        for r in row:
            existing = (r["content"] or "").strip().lower()
            sim = self._jaccard_similarity(candidate_norm, existing)
            if sim > best_sim:
                best_sim = sim
                best_match = r["content"][:120]
        return {"is_novel": best_sim < 0.5, "similarity": round(best_sim, 3), "match": best_match}

    @staticmethod
    def _jaccard_similarity(a: str, b: str) -> float:
        set_a = set(a.split())
        set_b = set(b.split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def register_vault(self, path: str, name: str, description: str = "", types: Optional[list[str]] = None) -> dict:
        tool = "register_vault"
        vault_path = Path(path).resolve()
        if not vault_path.exists():
            return fail(tool, "VAULT_PATH_NOT_FOUND", "vault path does not exist", {"path": path})
        vaults = self._read_vaults_registry()
        normalized = str(vault_path)
        for v in vaults:
            if v.get("path") == normalized:
                v["name"] = name
                v["description"] = description
                v["types"] = types or v.get("types", ["knowledge"])
                self._write_vaults_registry(vaults)
                return ok(tool, {"action": "updated", "vault": v})
        entry = {
            "path": normalized,
            "name": name,
            "description": description,
            "types": types or ["knowledge"],
            "registered_at": self._now_iso(),
        }
        vaults.append(entry)
        self._write_vaults_registry(vaults)
        return ok(tool, {"action": "registered", "vault": entry})

    def list_vaults(self) -> dict:
        tool = "list_vaults"
        vaults = self._read_vaults_registry()
        return ok(tool, {"vaults": vaults, "count": len(vaults)})

    def _read_vaults_registry(self) -> list[dict]:
        path = LIBRARY_DIR / "vaults.json"
        if path.exists():
            import json
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _write_vaults_registry(self, vaults: list[dict]) -> None:
        import json
        LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        path = LIBRARY_DIR / "vaults.json"
        path.write_text(json.dumps(vaults, indent=2, ensure_ascii=False), encoding="utf-8")

    def _ensure_dirs(self) -> None:
        LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_ROOT.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_VAULT_DIR.mkdir(parents=True, exist_ok=True)
        SKILLS_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        SKILL_DRAFT_ROOT.mkdir(parents=True, exist_ok=True)
        AGENT_SKILL_ROOT.mkdir(parents=True, exist_ok=True)
        if not MEMORY_FILE.exists():
            MEMORY_FILE.write_text("", encoding="utf-8")
        if not USER_FILE.exists():
            USER_FILE.write_text("", encoding="utf-8")
        if not MEMORY_INDEX_PATH.exists():
            MEMORY_INDEX_PATH.write_text("# Memory Index\n\n| # | Title | Target | Tags | Updated | File |\n|---|-------|--------|------|---------|------|\n", encoding="utf-8")
        if not SKILLS_INDEX_PATH.exists():
            SKILLS_INDEX_PATH.write_text("[]\n", encoding="utf-8")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'").fetchone()
        if row:
            self._ensure_column(conn, "sessions", "session_key", "TEXT")
            self._ensure_column(conn, "sessions", "title", "TEXT")
            self._ensure_column(conn, "sessions", "question_summary", "TEXT")
            self._ensure_column(conn, "sessions", "started_at", "TEXT")
            self._ensure_column(conn, "sessions", "ended_at", "TEXT")
            self._ensure_column(conn, "sessions", "source", "TEXT")
            self._ensure_column(conn, "skills", "version", "TEXT")
            conn.commit()
            return
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                tags TEXT,
                vault_path TEXT NOT NULL UNIQUE,
                source_path TEXT,
                updated_at TEXT NOT NULL,
                file_mtime TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS passages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                heading TEXT,
                text TEXT NOT NULL,
                chunk_order INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT,
                title TEXT,
                question TEXT NOT NULL,
                question_summary TEXT,
                answer_summary TEXT NOT NULL,
                citations TEXT NOT NULL,
                vault_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                source TEXT
            );

            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_name TEXT,
                tool_payload TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL,
                content TEXT NOT NULL,
                source_session_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                vault_path TEXT NOT NULL UNIQUE,
                index_keywords TEXT,
                source_session_id TEXT,
                updated_at TEXT NOT NULL,
                version TEXT
            );

            CREATE TABLE IF NOT EXISTS skill_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id INTEGER NOT NULL,
                version TEXT NOT NULL,
                change_summary TEXT NOT NULL,
                vault_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(skill_id) REFERENCES skills(id) ON DELETE CASCADE
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(
                title,
                heading,
                tags,
                text,
                passage_id UNINDEXED,
                tokenize='trigram'
            );

            CREATE TABLE IF NOT EXISTS price_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                source_note_path TEXT NOT NULL,
                source_path TEXT,
                source_name TEXT NOT NULL,
                material_name TEXT NOT NULL,
                material_name_key TEXT NOT NULL,
                unit TEXT,
                price_text TEXT,
                price_value TEXT,
                price_value_numeric REAL,
                note TEXT,
                page INTEGER,
                table_slug TEXT,
                engine TEXT,
                lookup_key TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_price_index_document_id ON price_index(document_id);
            CREATE INDEX IF NOT EXISTS idx_price_index_material_key ON price_index(material_name_key);
            CREATE INDEX IF NOT EXISTS idx_price_index_source_path ON price_index(source_path);

            CREATE VIRTUAL TABLE IF NOT EXISTS price_fts USING fts5(
                material_name,
                unit,
                price_text,
                note,
                lookup_key,
                source_name,
                record_id UNINDEXED,
                tokenize='trigram'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
                session_key UNINDEXED,
                role,
                content,
                message_id UNINDEXED,
                tokenize='trigram'
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_session_key ON sessions(session_key);
            CREATE INDEX IF NOT EXISTS idx_session_messages_session_id ON session_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_memory_entries_target ON memory_entries(target);
            CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status);
            """
        )
        self._ensure_column(conn, "sessions", "session_key", "TEXT")
        self._ensure_column(conn, "sessions", "title", "TEXT")
        self._ensure_column(conn, "sessions", "question_summary", "TEXT")
        self._ensure_column(conn, "sessions", "started_at", "TEXT")
        self._ensure_column(conn, "sessions", "ended_at", "TEXT")
        self._ensure_column(conn, "sessions", "source", "TEXT")
        self._ensure_column(conn, "skills", "version", "TEXT")
        conn.commit()

    def _iter_markdown_paths(self, prefixes: Iterable[str]) -> list[str]:
        paths: list[str] = []
        for prefix in prefixes:
            base = self.vault_root / prefix
            if not base.exists():
                continue
            for path in base.rglob("*.md"):
                if any(part in {".obsidian", ".library", "temp"} for part in path.parts):
                    continue
                relative_path = str(path.relative_to(self.vault_root)).replace("\\", "/")
                if any(relative_path.startswith(prefix) for prefix in EXCLUDED_INDEX_PREFIXES):
                    continue
                paths.append(relative_path)
        return paths

    def _index_single_path(self, conn: sqlite3.Connection, vault_path: str) -> None:
        path = self.vault_root / vault_path
        try:
            content = path.read_text(encoding="utf-8")
            metadata, body = self._parse_markdown(content)
            file_mtime = self._file_mtime_iso(path)
            document = self._build_document_ref(vault_path, metadata, body, file_mtime)
            chunks = self._build_passages(document["title"], document["type"], document["tags"], body)
            existing = conn.execute("SELECT id FROM documents WHERE vault_path = ?", (vault_path,)).fetchone()
            if existing:
                self._delete_document_contents(conn, existing["id"])
                document_id = existing["id"]
                conn.execute(
                    """
                    UPDATE documents
                    SET title = ?, type = ?, tags = ?, source_path = ?, updated_at = ?, file_mtime = ?
                    WHERE id = ?
                    """,
                    (
                        document["title"],
                        document["type"],
                        json.dumps(document["tags"], ensure_ascii=False),
                        document["source_path"],
                        document["updated_at"],
                        file_mtime,
                        document_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO documents(title, type, tags, vault_path, source_path, updated_at, file_mtime)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document["title"],
                        document["type"],
                        json.dumps(document["tags"], ensure_ascii=False),
                        vault_path,
                        document["source_path"],
                        document["updated_at"],
                        file_mtime,
                    ),
                )
                document_id = cursor.lastrowid
            for chunk in chunks:
                cursor = conn.execute(
                    """
                    INSERT INTO passages(document_id, heading, text, chunk_order, priority)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        chunk["heading"],
                        chunk["text"],
                        chunk["chunk_order"],
                        chunk["priority"],
                    ),
                )
                passage_id = cursor.lastrowid
                conn.execute(
                    """
                    INSERT INTO passage_fts(title, heading, tags, text, passage_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document["title"],
                        chunk["heading"],
                        " ".join(document["tags"]),
                        chunk["text"],
                        passage_id,
                    ),
                )
                if _HAS_EMBED:
                    try:
                        _vi.load_vec(conn)
                        emb = _embedding.encode(chunk["text"])
                        _vi.index_passage(conn, passage_id, emb)
                    except Exception:
                        pass
            self._sync_price_index_for_document(conn, document_id, document, body)
            conn.commit()
        except Exception as exc:
            self._log_index_error(vault_path, exc)
            raise

    def _delete_document(self, conn: sqlite3.Connection, vault_path: str) -> None:
        row = conn.execute("SELECT id FROM documents WHERE vault_path = ?", (vault_path,)).fetchone()
        if not row:
            return
        self._delete_document_contents(conn, row["id"])
        conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
        conn.commit()

    def _delete_document_contents(self, conn: sqlite3.Connection, document_id: int) -> None:
        passage_rows = conn.execute("SELECT id FROM passages WHERE document_id = ?", (document_id,)).fetchall()
        for row in passage_rows:
            conn.execute("DELETE FROM passage_fts WHERE passage_id = ?", (row["id"],))
            if _HAS_EMBED:
                try:
                    _vi.load_vec(conn)
                    conn.execute("DELETE FROM passage_vec WHERE rowid = ?", (row["id"],))
                except Exception:
                    pass
        price_rows = conn.execute("SELECT id FROM price_index WHERE document_id = ?", (document_id,)).fetchall()
        for row in price_rows:
            conn.execute("DELETE FROM price_fts WHERE record_id = ?", (row["id"],))
        conn.execute("DELETE FROM price_index WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM passages WHERE document_id = ?", (document_id,))

    def _parse_markdown(self, content: str) -> tuple[dict, str]:
        match = FRONTMATTER_PATTERN.match(content)
        if not match:
            return {}, content
        raw_meta = match.group(1)
        if not re.search(r"^[A-Za-z0-9_-]+\s*:", raw_meta, re.MULTILINE):
            return {}, content
        body = content[match.end():]
        try:
            metadata = yaml.safe_load(raw_meta) or {}
        except yaml.YAMLError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return metadata, body

    def _build_document_ref(self, vault_path: str, metadata: dict, body: str, file_mtime: str) -> dict:
        title = metadata.get("title") or self._extract_title_from_body(body) or Path(vault_path).stem
        doc_type = str(metadata.get("type") or self._infer_type(vault_path))
        tags = self._normalize_tags(metadata.get("tags"))
        source_path = metadata.get("source_path")
        updated_at = self._normalize_datetime(metadata.get("updated"), fallback=file_mtime)
        return {
            "title": str(title),
            "type": doc_type,
            "vault_path": vault_path,
            "source_path": self._normalize_optional_relative_path(source_path),
            "tags": tags,
            "updated_at": updated_at,
        }

    def _document_row_to_ref(self, row: sqlite3.Row) -> dict:
        tags = json.loads(row["tags"]) if row["tags"] else []
        return {
            "title": row["title"],
            "type": row["type"],
            "vault_path": row["vault_path"],
            "source_path": row["source_path"],
            "tags": tags,
            "updated_at": row["updated_at"],
        }

    def _row_to_passage_ref(self, row: sqlite3.Row) -> dict:
        return {
            "document": self._document_row_to_ref(row),
            "heading": row["heading"],
            "chunk_order": row["chunk_order"],
            "text": row["text"],
            "score": row["score"],
            "priority": row["priority"],
            "decay_score": row["decay_score"],
        }

    def _build_passages(self, title: str, doc_type: str, tags: list[str], body: str) -> list[dict]:
        sections = self._split_sections(title, body)
        priority = self._priority_for_type(doc_type)
        chunks: list[dict] = []
        chunk_order = 1
        for heading, text in sections:
            for chunk_text in self._chunk_text(text):
                if not chunk_text.strip():
                    continue
                chunks.append(
                    {
                        "heading": heading,
                        "text": chunk_text.strip(),
                        "chunk_order": chunk_order,
                        "priority": priority,
                    }
                )
                chunk_order += 1
        if not chunks:
            chunks.append(
                {
                    "heading": title,
                    "text": body.strip() or title,
                    "chunk_order": 1,
                    "priority": priority,
                }
            )
        return chunks

    def _split_sections(self, title: str, body: str) -> list[tuple[str, str]]:
        lines = body.splitlines()
        if not lines:
            return [(title, body)]
        sections: list[tuple[str, str]] = []
        current_heading = title
        current_lines: list[str] = []
        for line in lines:
            match = HEADING_PATTERN.match(line)
            if match:
                if current_lines:
                    sections.append((current_heading, "\n".join(current_lines).strip()))
                current_heading = match.group(2).strip()
                current_lines = []
            elif re.fullmatch(r"[-_*]{3,}", line.strip()):
                continue
            else:
                current_lines.append(line)
        sections.append((current_heading, "\n".join(current_lines).strip()))
        return [(heading, text) for heading, text in sections if text]

    def _chunk_text(self, text: str, max_chars: int = 800) -> list[str]:
        stripped = text.strip()
        if not stripped:
            return []
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", stripped) if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(paragraph) <= max_chars:
                current = paragraph
                continue
            start = 0
            while start < len(paragraph):
                end = start + max_chars
                chunk = paragraph[start:end].strip()
                if chunk:
                    chunks.append(chunk)
                start = end
            current = ""
        if current:
            chunks.append(current)
        return chunks

    def _extract_title_from_body(self, body: str) -> Optional[str]:
        for line in body.splitlines():
            match = HEADING_PATTERN.match(line.strip())
            if match:
                return match.group(2).strip()
        return None

    def _infer_type(self, vault_path: str) -> str:
        if vault_path.startswith("Librarian/SessionNotes/"):
            return "session_note"
        if vault_path.startswith("Librarian/SkillDrafts/"):
            return "skill_draft"
        if vault_path.startswith("Librarian/AgentSkills/"):
            return "agent_skill"
        if vault_path.startswith("Knowledge/"):
            return "summary"
        return "source_note"

    def _priority_for_type(self, doc_type: str) -> int:
        mapping = {
            "summary": 100,
            "topic_map": 95,
            "agent_skill": 90,
            "report": 80,
            "excerpt": 70,
            "session_note": 60,
            "source_note": 40,
            "skill_draft": 20,
        }
        return mapping.get(doc_type, 50)

    def _normalize_tags(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    def _normalize_datetime(self, value: object, fallback: str) -> str:
        if value is None:
            return fallback
        if isinstance(value, datetime):
            return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        text = str(value).strip()
        if not text:
            return fallback
        try:
            normalized = text.replace("Z", "+00:00")
            if len(text) == 10:
                dt = datetime.fromisoformat(f"{text}T00:00:00+00:00")
            else:
                dt = datetime.fromisoformat(normalized)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return fallback

    def _file_mtime_iso(self, path: Path) -> str:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _normalize_relative_path(self, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        if not normalized:
            raise ValueError("path must be relative to vault root")
        if normalized.startswith("/"):
            raise ValueError("path must be relative to vault root")
        if ":" in normalized and not normalized.startswith("@"):
            try:
                abs_path = Path(value)
                return str(abs_path.resolve().relative_to(self.vault_root.resolve())).replace("\\", "/")
            except (ValueError, OSError):
                return normalized
        return normalized

    def _normalize_optional_relative_path(self, value: Optional[object]) -> Optional[str]:
        if value in (None, ""):
            return None
        return self._normalize_relative_path(str(value))

    def _make_safe_phrase_query(self, query: str) -> str:
        text = query.replace('"', " ").strip()
        if not text:
            return query
        return f'"{text}"'

    def _fallback_like_search(self, conn: sqlite3.Connection, query: str, types: Optional[list[str]], normalized_prefixes: Optional[list[str]], limit: int) -> list[sqlite3.Row]:
        like_sql = """
            SELECT
                d.title,
                d.type,
                d.vault_path,
                d.source_path,
                d.tags,
                d.updated_at,
                p.heading,
                p.chunk_order,
                p.text,
                p.priority,
                p.decay_score,
                0 AS score
            FROM passages p
            JOIN documents d ON d.id = p.document_id
            WHERE 1 = 1
        """
        like_params: list[object] = []
        words = query.split()
        if len(words) == 1 and len(words[0]) > 2 and not any(c.isspace() or c.isascii() for c in words[0]):
            words = [words[0][i:i+2] for i in range(0, len(words[0]), 2)]
        for word in words:
            like_pattern = f"%{word}%"
            like_sql += " AND (p.text LIKE ? OR p.heading LIKE ? OR d.title LIKE ?)"
            like_params.extend([like_pattern, like_pattern, like_pattern])
        if types:
            placeholders = ",".join(["?"] * len(types))
            like_sql += f" AND d.type IN ({placeholders})"
            like_params.extend(types)
        else:
            like_sql += " AND d.type != ?"
            like_params.append("skill_draft")
        if normalized_prefixes:
            clauses = []
            for prefix in normalized_prefixes:
                clauses.append("d.vault_path LIKE ?")
                like_params.append(f"{prefix}%")
            like_sql += " AND (" + " OR ".join(clauses) + ")"
        like_sql += " ORDER BY p.priority DESC, p.decay_score DESC, d.updated_at DESC LIMIT ?"
        like_params.append(limit)
        return conn.execute(like_sql, like_params).fetchall()

    def _find_sibling_source_candidates(self, path: Path) -> list[str]:
        candidates: list[str] = []
        if not path.exists():
            return candidates
        for item in sorted(path.parent.iterdir()):
            if item == path or item.suffix.lower() == ".md" or not item.is_file():
                continue
            if item.stem == path.stem or path.stem in item.stem or item.stem in path.stem:
                candidates.append(str(item.relative_to(self.vault_root)).replace("\\", "/"))
        return candidates

    def _find_related_markdown_candidates(self, vault_path: str, limit: int = 8) -> list[str]:
        stem = Path(vault_path).stem.lower()
        candidates: list[str] = []
        for candidate in self._iter_markdown_paths(DEFAULT_INDEX_PREFIXES):
            if candidate == vault_path:
                continue
            candidate_stem = Path(candidate).stem.lower()
            if stem == candidate_stem or stem in candidate_stem or candidate_stem in stem:
                candidates.append(candidate)
            if len(candidates) >= limit:
                break
        return candidates

    def _trim_title(self, question: str, max_length: int = 48) -> str:
        text = " ".join(question.split())
        if len(text) <= max_length:
            return text
        return text[:max_length].rstrip()

    def _sanitize_filename(self, value: str) -> str:
        text = INVALID_FILE_CHARS.sub(" ", value)
        text = re.sub(r"\s+", " ", text).strip().rstrip(".")
        return text or "问答归档"

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
        existing = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if any(row["name"] == column_name for row in existing):
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    # ── vault-based memory storage ──────────────────────────────────────

    @staticmethod
    def _memory_slug(text: str) -> str:
        slug = unicodedata.normalize("NFKD", text)[:60].strip()
        slug = re.sub(r"[^\w\s-]", "", slug).strip().lower()
        slug = re.sub(r"[-\s]+", "-", slug)
        return slug[:50] or "memory-entry"

    def _read_memory_index(self) -> list[dict]:
        if not MEMORY_INDEX_PATH.exists():
            return []
        raw = MEMORY_INDEX_PATH.read_text(encoding="utf-8")
        entries: list[dict] = []
        in_table = False
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("| # |") and "Title" in line:
                in_table = True
                continue
            if line.startswith("|---"):
                continue
            if not in_table or not line.startswith("|"):
                continue
            parts = [c.strip() for c in line.strip("|").split("|")]
            if len(parts) < 6:
                continue
            num, title, target, tags, updated, file_path = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            entries.append({
                "id": num,
                "title": title,
                "target": target,
                "tags": [t.strip() for t in tags.split(",") if t.strip()],
                "updated_at": updated,
                "vault_path": file_path,
            })
        return entries

    def _append_memory_index(self, entry: dict) -> None:
        line = (
            f"| {entry['id']} | {entry['title']} | {entry['target']} | "
            f"{', '.join(entry.get('tags', []))} | {entry['updated_at']} | "
            f"{entry['vault_path']} |\n"
        )
        with MEMORY_INDEX_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def _rewrite_memory_index(self, entries: list[dict]) -> None:
        lines = [
            "# Memory Index\n",
            "\n",
            "| # | Title | Target | Tags | Updated | File |\n",
            "|---|-------|--------|------|---------|------|\n",
        ]
        for e in entries:
            lines.append(
                f"| {e['id']} | {e['title']} | {e['target']} | "
                f"{', '.join(e.get('tags', []))} | {e['updated_at']} | "
                f"{e['vault_path']} |\n"
            )
        MEMORY_INDEX_PATH.write_text("".join(lines), encoding="utf-8")

    def _make_memory_frontmatter(self, title: str, target: str, tags: list[str], source_session_id: Optional[str], created_at: Optional[str] = None) -> str:
        timestamp = self._now_iso()
        created = created_at or timestamp
        if isinstance(created, datetime):
            created = created.strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            "---",
            f"title: {json.dumps(title)}",
            f"target: {target}",
            f"type: memory",
            f"created_at: {created}",
            f"updated_at: {timestamp}",
        ]
        if source_session_id:
            lines.append(f"source_session_id: {json.dumps(source_session_id)}")
        if tags:
            lines.append(f"tags: {json.dumps(tags)}")
        lines.append("---\n")
        return "\n".join(lines)

    def _index_memory_in_fts5(self, conn: sqlite3.Connection, title: str, vault_path: str, content: str, tags: list[str]) -> None:
        timestamp = self._now_iso()
        tags_str = ", ".join(tags)
        cursor = conn.execute(
            "SELECT id FROM documents WHERE vault_path = ? AND type = ?",
            (vault_path, "memory"),
        )
        existing = cursor.fetchone()
        if existing:
            doc_id = existing[0]
            conn.execute(
                "UPDATE documents SET title = ?, tags = ?, updated_at = ?, file_mtime = ? WHERE id = ?",
                (title, tags_str, timestamp, timestamp, doc_id),
            )
            conn.execute("DELETE FROM passages WHERE document_id = ?", (doc_id,))
        else:
            cursor = conn.execute(
                "INSERT INTO documents(title, type, tags, vault_path, source_path, updated_at, file_mtime) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, "memory", tags_str, vault_path, None, timestamp, timestamp),
            )
            doc_id = cursor.lastrowid
        cursor = conn.execute(
            "INSERT INTO passages(document_id, heading, text, chunk_order, priority) VALUES (?, ?, ?, ?, ?)",
            (doc_id, None, content, 1, 10),
        )
        passage_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO passage_fts(title, heading, tags, text, passage_id) VALUES (?, ?, ?, ?, ?)",
            (title, None, tags_str, content, passage_id),
        )

    def _remove_memory_from_fts5(self, conn: sqlite3.Connection, vault_path: str) -> None:
        cursor = conn.execute("SELECT id FROM documents WHERE vault_path = ? AND type = ?", (vault_path, "memory"))
        row = cursor.fetchone()
        if row:
            conn.execute("DELETE FROM documents WHERE id = ?", (row[0],))

    def _find_memory_by_match(self, match: str) -> Optional[dict]:
        index_entries = self._read_memory_index()
        for entry in index_entries:
            file_path = self.vault_root / entry["vault_path"]
            if match in entry["title"] or match in entry["vault_path"]:
                return {"entry": entry, "file": file_path}
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                if match in content:
                    return {"entry": entry, "file": file_path}
        return None

    def _migrate_old_memories(self) -> int:
        migrated = 0
        now_compact = self._now_iso().replace(":", "").replace("-", "")
        for target, old_path in [("memory", MEMORY_FILE), ("user", USER_FILE)]:
            if not old_path.exists():
                continue
            raw = old_path.read_text(encoding="utf-8").strip()
            if not raw:
                continue
            entries = [item.strip() for item in re.split(r"\n?§\n?", raw) if item.strip()]
            existing_count = len(self._read_memory_index())
            for i, content in enumerate(entries):
                title = re.sub(r'^#+\s*', '', content.split("\n")[0][:80].strip())
                slug = self._memory_slug(title or "memory-entry")
                file_name = f"mem-{now_compact}-{i:03d}-{slug}.md"
                file_path = MEMORY_VAULT_DIR / file_name
                frontmatter = self._make_memory_frontmatter(title, target, [], None)
                file_path.write_text(frontmatter + content + "\n", encoding="utf-8")
                index_entry = {
                    "id": str(existing_count + i + 1),
                    "title": title,
                    "target": target,
                    "tags": [],
                    "updated_at": self._now_iso(),
                    "vault_path": f"Librarian/Memory/{file_name}",
                }
                self._append_memory_index(index_entry)
                migrated += 1
            old_path.rename(old_path.with_suffix(".md.bak"))
        return migrated

    def _should_block_memory_content(self, content: str) -> bool:
        lowered = content.lower()
        blocked_markers = [
            "todo",
            "待办",
            "临时",
            "本轮",
            "目前做到",
            "下一步",
            "稍后",
            "猜测",
            "草稿",
        ]
        return any(marker in lowered for marker in blocked_markers)

    def _create_session_key(self) -> str:
        return datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")

    def _insert_session_message(
        self,
        conn: sqlite3.Connection,
        session_row_id: int,
        session_key: str,
        role: str,
        content: str,
        tool_name: Optional[str] = None,
        tool_payload: Optional[dict] = None,
    ) -> None:
        timestamp = self._now_iso()
        cursor = conn.execute(
            """
            INSERT INTO session_messages(session_id, role, content, tool_name, tool_payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_row_id,
                role,
                content,
                tool_name,
                json.dumps(tool_payload, ensure_ascii=False) if tool_payload else None,
                timestamp,
            ),
        )
        conn.execute(
            """
            INSERT INTO session_fts(session_key, role, content, message_id)
            VALUES (?, ?, ?, ?)
            """,
            (session_key, role, content, cursor.lastrowid),
        )

    def _skill_row_to_ref(self, row: sqlite3.Row) -> dict:
        keywords = self._normalize_tags(json.loads(row["index_keywords"]) if row["index_keywords"] else [])
        return {
            "name": row["name"],
            "status": row["status"],
            "summary": row["summary"],
            "vault_path": row["vault_path"],
            "keywords": keywords,
            "version": row["version"] or ("0.1.0" if row["status"] == "draft" else "1.0.0"),
            "source_session_id": row["source_session_id"],
            "updated_at": row["updated_at"],
        }

    def _render_skill_note(
        self,
        frontmatter: dict,
        applicable_when: list[str],
        preconditions: list[str],
        inputs: list[str],
        outputs: list[str],
        steps: list[str],
        checkpoints: list[str],
        failure_modes: list[str],
    ) -> str:
        body_parts = [
            "# 适用场景",
            self._render_bullets(applicable_when) or "",
            "# 前置条件",
            self._render_bullets(preconditions) or "",
            "# 输入",
            self._render_bullets(inputs) or "",
            "# 输出",
            self._render_bullets(outputs) or "",
            "# 标准步骤",
            self._render_bullets(steps) or "",
            "# 检查点",
            self._render_bullets(checkpoints) or "",
            "# 常见失败",
            self._render_bullets(failure_modes) or "",
        ]
        return self._render_markdown_with_frontmatter(frontmatter, "\n\n".join(body_parts))

    def _render_markdown_with_frontmatter(self, frontmatter: dict, body: str) -> str:
        frontmatter_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
        return f"---\n{frontmatter_text}\n---\n\n{body.strip()}\n"

    def _promote_skill_body(self, body: str, change_summary: str) -> str:
        cleaned = body.strip()
        if "## 版本更新" in cleaned:
            return cleaned + f"\n\n- {change_summary.strip()}\n"
        return cleaned + f"\n\n## 版本更新\n\n- {change_summary.strip()}\n"

    def _next_skill_version(self, existing_version: Optional[object]) -> str:
        text = str(existing_version or "").strip()
        if not text:
            return "1.0.0"
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text)
        if not match:
            return "1.0.0"
        major, minor, patch = (int(part) for part in match.groups())
        return f"{major}.{minor}.{patch + 1}"

    def _extract_first_paragraph(self, body: str) -> Optional[str]:
        for paragraph in re.split(r"\n\s*\n", body):
            text = paragraph.strip()
            if not text or text.startswith("#"):
                continue
            return text.replace("\n", " ")
        return None

    def _suggest_memory_from_texts(self, texts: list[str]) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()
        stable_keywords = [
            "默认",
            "原则",
            "规范",
            "约束",
            "必须",
            "不要",
            "优先",
            "路径",
            "目录",
            "索引",
            "工具",
            "引用",
            "记忆",
            "技能",
        ]
        for text in texts:
            for line in (text or "").splitlines():
                normalized = line.strip().lstrip("-").strip()
                if not normalized:
                    continue
                if len(normalized) < 6 or len(normalized) > 120:
                    continue
                if self._should_block_memory_content(normalized):
                    continue
                if not any(keyword in normalized for keyword in stable_keywords):
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append(normalized)
                if len(candidates) >= 8:
                    return candidates
        return candidates

    def _suggest_skill_from_texts(self, question: str, answer: str, source_session_id: str) -> Optional[dict]:
        question_text = " ".join((question or "").split()).strip()
        answer_text = (answer or "").strip()
        if not question_text or not answer_text:
            return None
        steps = self._extract_procedural_steps(answer_text)
        if len(steps) < 2:
            return None
        name = self._derive_skill_name(question_text)
        keywords = self._derive_skill_keywords(question_text)
        summary = self._trim_text_one_line(answer_text, max_length=80) or name
        return {
            "name": name,
            "summary": summary,
            "keywords": keywords,
            "applicable_when": [],
            "preconditions": [],
            "inputs": [],
            "outputs": [],
            "steps": steps,
            "checkpoints": [],
            "failure_modes": [],
            "source_session_id": source_session_id,
        }

    def _extract_procedural_steps(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        extracted: list[str] = []
        for line in lines:
            if line.startswith("- "):
                candidate = line[2:].strip()
                if self._looks_like_step(candidate):
                    extracted.append(candidate)
                continue
            for sentence in re.split(r"[。；;\n]+", line):
                sentence = sentence.strip()
                if not sentence:
                    continue
                if self._looks_like_step(sentence):
                    extracted.append(sentence)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in extracted:
            normalized = item.strip()
            if not normalized or len(normalized) > 120:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
            if len(deduped) >= 8:
                break
        return deduped

    def _looks_like_step(self, text: str) -> bool:
        if len(text) < 4:
            return False
        markers = ["先", "再", "然后", "最后", "如果", "若", "需要", "将", "把", "用"]
        if any(text.startswith(marker) for marker in markers):
            return True
        if any(marker in text for marker in ["先", "再", "然后", "最后"]):
            return True
        return False

    def _derive_skill_name(self, question: str) -> str:
        text = question.strip()
        text = re.sub(r"[？?。！!]+$", "", text).strip()
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 40:
            text = text[:40].rstrip()
        return text or "通用流程"

    def _derive_skill_keywords(self, question: str) -> list[str]:
        tokens: list[str] = []
        for token in re.findall(r"[A-Za-z]{2,}", question):
            tokens.append(token.lower())
        for token in re.findall(r"[\u4e00-\u9fff]{2,}", question):
            tokens.append(token)
        deduped: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            token = token.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            deduped.append(token)
            if len(deduped) >= 8:
                break
        return deduped

    def _trim_text_one_line(self, text: str, max_length: int) -> str:
        normalized = " ".join((text or "").split()).strip()
        if len(normalized) <= max_length:
            return normalized
        return normalized[:max_length].rstrip()

    def _iter_skill_paths(self, include_drafts: bool) -> list[Path]:
        paths: list[Path] = []
        if include_drafts and SKILL_DRAFT_ROOT.exists():
            paths.extend(sorted(SKILL_DRAFT_ROOT.rglob("*.md")))
        if AGENT_SKILL_ROOT.exists():
            paths.extend(sorted(AGENT_SKILL_ROOT.rglob("*.md")))
        return paths

    def _rebuild_skill_index(self, conn: sqlite3.Connection, include_drafts: bool) -> dict:
        skills: list[dict] = []
        seen_paths: set[str] = set()
        for path in self._iter_skill_paths(include_drafts):
            relative_path = str(path.relative_to(self.vault_root)).replace("\\", "/")
            metadata, body = self._parse_markdown(path.read_text(encoding="utf-8"))
            status = str(metadata.get("status") or ("draft" if relative_path.startswith("Librarian/SkillDrafts/") else "active"))
            if not include_drafts and status == "draft":
                continue
            seen_paths.add(relative_path)
            record = {
                "name": str(metadata.get("skill_name") or metadata.get("title") or path.stem).replace("技能草稿 - ", "").strip(),
                "status": status,
                "summary": str(metadata.get("summary") or self._extract_first_paragraph(body) or path.stem),
                "vault_path": relative_path,
                "keywords": self._normalize_tags(metadata.get("keywords")),
                "version": str(metadata.get("version") or ("0.1.0" if status == "draft" else "1.0.0")),
                "source_session_id": metadata.get("source_session_id"),
                "updated_at": self._normalize_datetime(metadata.get("updated"), fallback=self._file_mtime_iso(path)),
            }
            conn.execute(
                """
                INSERT INTO skills(name, status, summary, vault_path, index_keywords, source_session_id, updated_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vault_path) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    summary = excluded.summary,
                    index_keywords = excluded.index_keywords,
                    source_session_id = excluded.source_session_id,
                    updated_at = excluded.updated_at,
                    version = excluded.version
                """,
                (
                    record["name"],
                    record["status"],
                    record["summary"],
                    record["vault_path"],
                    json.dumps(record["keywords"], ensure_ascii=False),
                    record["source_session_id"],
                    record["updated_at"],
                    record["version"],
                ),
            )
            skills.append(record)
        if seen_paths:
            placeholders = ",".join(["?"] * len(seen_paths))
            conn.execute(f"DELETE FROM skills WHERE vault_path NOT IN ({placeholders})", tuple(seen_paths))
        else:
            conn.execute("DELETE FROM skills")
        conn.commit()
        skills.sort(key=lambda item: (0 if item["status"] == "active" else 1, item["name"]))
        SKILLS_INDEX_PATH.write_text(json.dumps(skills, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "include_drafts": include_drafts,
            "count": len(skills),
            "index_path": str(SKILLS_INDEX_PATH.relative_to(self.vault_root)).replace("\\", "/"),
        }

    def _render_session_note(
        self,
        frontmatter: dict,
        question: str,
        conclusion: str,
        key_points: list[str],
        citations: list[dict],
        model_judgement: Optional[str],
        external_sources: list[dict],
        todo: list[str],
    ) -> str:
        frontmatter_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
        sections = [f"---\n{frontmatter_text}\n---", "# 问题", question, "# 结论", conclusion]
        if key_points:
            sections.extend(["# 要点", self._render_bullets(key_points)])
        local_citations = [item for item in citations if item.get("kind") in {"local_summary", "local_source"}]
        history_citations = [item for item in citations if item.get("kind") == "history_recall"]
        skill_citations = [item for item in citations if item.get("kind") == "agent_skill"]
        if local_citations:
            sections.extend(["# 本地依据", self._render_citations(local_citations)])
        if history_citations:
            sections.extend(["# 历史回忆", self._render_citations(history_citations)])
        if skill_citations:
            sections.extend(["# 调用技能", self._render_citations(skill_citations)])
        sections.extend(["# 模型判断", model_judgement or ""])
        if external_sources:
            sections.extend(["# 外部来源", self._render_citations(external_sources)])
        else:
            sections.extend(["# 外部来源", ""])
        sections.extend(["# 后续待办", self._render_bullets(todo) if todo else ""])
        return "\n\n".join(section for section in sections)

    def _render_bullets(self, items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items if item.strip())

    def _render_citations(self, citations: list[dict]) -> str:
        lines: list[str] = []
        for item in citations:
            kind = item.get("kind")
            if kind == "local_summary":
                prefix = "[本地摘要]"
            elif kind == "local_source":
                prefix = "[本地原文]"
            elif kind == "history_recall":
                prefix = "[历史会话]"
            elif kind == "agent_skill":
                prefix = "[正式技能]"
            elif kind == "web_source":
                prefix = "[网络来源]"
            else:
                prefix = "[模型常识]"
            title = item.get("title") or ""
            vault_path = item.get("vault_path") or ""
            url = item.get("url") or ""
            quote = item.get("quote") or ""
            target = vault_path or url or title
            line = f"- {prefix} {target}"
            if quote:
                line += f"：{quote}"
            lines.append(line)
        return "\n".join(lines)

    def _sync_price_index_for_document(self, conn: sqlite3.Connection, document_id: int, document: dict, body: str) -> None:
        if document.get("type") != "source_note":
            return
        records_csv = self._extract_layered_records_csv_path(body)
        if not records_csv:
            return
        records_path = self.vault_root / records_csv
        if not records_path.exists():
            return
        source_path = document.get("source_path")
        source_name = Path(source_path).name if source_path else Path(document["vault_path"]).name
        updated_at = document.get("updated_at") or self._now_iso()
        with records_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                material_name = self._normalize_search_text(row.get("material_name", ""))
                price_value = self._normalize_search_text(row.get("price_value", ""))
                if not material_name or not price_value:
                    continue
                unit = self._normalize_search_text(row.get("unit", ""))
                price_text = self._normalize_search_text(row.get("price_text", "")) or price_value
                note = self._normalize_search_text(row.get("note", ""))
                table_slug = self._normalize_search_text(row.get("table_slug", ""))
                engine = self._normalize_search_text(row.get("engine", ""))
                page = self._parse_int(row.get("page"))
                lookup_key = " ".join(part for part in [material_name, price_value, unit] if part)
                cursor = conn.execute(
                    """
                    INSERT INTO price_index(
                        document_id,
                        source_note_path,
                        source_path,
                        source_name,
                        material_name,
                        material_name_key,
                        unit,
                        price_text,
                        price_value,
                        price_value_numeric,
                        note,
                        page,
                        table_slug,
                        engine,
                        lookup_key,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        document["vault_path"],
                        source_path,
                        source_name,
                        material_name,
                        self._normalize_material_key(material_name),
                        unit,
                        price_text,
                        price_value,
                        self._parse_float(price_value),
                        note,
                        page,
                        table_slug,
                        engine,
                        lookup_key,
                        updated_at,
                    ),
                )
                record_id = cursor.lastrowid
                conn.execute(
                    """
                    INSERT INTO price_fts(material_name, unit, price_text, note, lookup_key, source_name, record_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        material_name,
                        unit,
                        price_text,
                        note,
                        lookup_key,
                        source_name,
                        record_id,
                    ),
                )

    def _extract_layered_records_csv_path(self, body: str) -> Optional[str]:
        pattern = re.compile(r"^- 规范记录表（CSV）[:：]\s*(.+?)\s*$")
        for line in body.splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            value = match.group(1).strip().strip("`")
            try:
                return self._normalize_relative_path(value)
            except ValueError:
                return None
        return None

    def _price_row_to_ref(self, row: sqlite3.Row) -> dict:
        return {
            "material_name": row["material_name"],
            "unit": row["unit"],
            "price_text": row["price_text"],
            "price_value": row["price_value"],
            "note": row["note"],
            "page": row["page"],
            "table_slug": row["table_slug"],
            "engine": row["engine"],
            "source_name": row["source_name"],
            "source_path": row["source_path"],
            "source_note_path": row["source_note_path"],
            "updated_at": row["updated_at"],
        }

    def _normalize_search_text(self, value: object) -> str:
        text = str(value or "").strip()
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _escape_fts5_query(query: str) -> str:
        """Wrap each token in double quotes to prevent FTS5 operator interpretation.

        Special characters like - (NOT), () (grouping), * (prefix) in tokens
        like ''PP-R'', ''WDZ-BYJ'' would otherwise break the query.
        """
        tokens = query.strip().split()
        return " ".join(f'"{token}"' for token in tokens if token)

    def _normalize_material_key(self, value: object) -> str:
        text = self._normalize_search_text(value).lower()
        return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)

    def _parse_float(self, value: object) -> Optional[float]:
        text = self._normalize_search_text(value)
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _parse_int(self, value: object) -> Optional[int]:
        text = self._normalize_search_text(value)
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None

    def _resolve_external_path(self, vault_path_or_source: str) -> Optional[str]:
        """将 @root:relative/path 格式解析为绝对文件系统路径。"""
        match = re.match(r"^@([^:]+):(.+)$", vault_path_or_source)
        if not match:
            return None
        root_name = match.group(1)
        relative = match.group(2)
        root = EXTERNAL_ROOTS.get(root_name)
        if root is None:
            return None
        return str((root / relative).resolve())

    def _log_index_error(self, vault_path: str, exc: Exception) -> None:
        self.error_log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = self._now_iso()
        message = f"[{timestamp}] {vault_path}: {type(exc).__name__}: {exc}\n"
        self.error_log_path.write_text(
            self.error_log_path.read_text(encoding="utf-8") + message if self.error_log_path.exists() else message,
            encoding="utf-8",
        )

    def recalc_decay(
        self,
        target: str = "all",
        lambda_decay: float = 0.01,
        alpha_access: float = 0.3,
    ) -> dict:
        tool = "recalc_decay"
        if target not in ("all", "passages", "memories"):
            return fail(tool, "INVALID_TARGET", "target must be all, passages, or memories", {"target": target})
        lambda_decay = max(0.001, min(float(lambda_decay), 0.1))
        alpha_access = max(0.0, min(float(alpha_access), 2.0))
        now = datetime.now(UTC)
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        updated_passages = 0
        updated_memories = 0
        with self._connect() as conn:
            self._init_schema(conn)
            if target in ("all", "passages"):
                rows = conn.execute(
                    "SELECT id, priority, access_count, last_access_at FROM passages"
                ).fetchall()
                for row in rows:
                    score = self._calc_decay(
                        priority_base=row["priority"] / 100.0,
                        access_count=row["access_count"] or 0,
                        last_access_at=row["last_access_at"],
                        now=now,
                        lambda_decay=lambda_decay,
                        alpha_access=alpha_access,
                    )
                    conn.execute(
                        "UPDATE passages SET decay_score = ? WHERE id = ?",
                        (score, row["id"]),
                    )
                    updated_passages += 1
            if target in ("all", "memories"):
                rows = conn.execute(
                    "SELECT id, access_count, last_access_at FROM memory_entries"
                ).fetchall()
                for row in rows:
                    score = self._calc_decay(
                        priority_base=1.0,
                        access_count=row["access_count"] or 0,
                        last_access_at=row["last_access_at"],
                        now=now,
                        lambda_decay=lambda_decay,
                        alpha_access=alpha_access,
                    )
                    conn.execute(
                        "UPDATE memory_entries SET decay_score = ? WHERE id = ?",
                        (score, row["id"]),
                    )
                    updated_memories += 1
            conn.commit()
        return ok(
            tool,
            {
                "target": target,
                "lambda_decay": lambda_decay,
                "alpha_access": alpha_access,
                "updated_passages": updated_passages,
                "updated_memories": updated_memories,
                "recalculated_at": now_iso,
            },
        )

    def decay_cleanup(
        self,
        target: str = "all",
        threshold: float = 0.05,
        dry_run: bool = True,
    ) -> dict:
        tool = "decay_cleanup"
        if target not in ("all", "passages", "memories"):
            return fail(tool, "INVALID_TARGET", "target must be all, passages, or memories", {"target": target})
        threshold = max(0.0, min(float(threshold), 1.0))
        removed_passages: list[dict] = []
        removed_memories: list[dict] = []
        with self._connect() as conn:
            self._init_schema(conn)
            if target in ("all", "passages"):
                rows = conn.execute(
                    """
                    SELECT p.id, p.heading, p.text, d.vault_path, d.title, p.decay_score
                    FROM passages p
                    JOIN documents d ON d.id = p.document_id
                    WHERE p.decay_score < ?
                    ORDER BY p.decay_score ASC
                    """,
                    (threshold,),
                ).fetchall()
                for row in rows:
                    info = {
                        "passage_id": row["id"],
                        "heading": row["heading"],
                        "vault_path": row["vault_path"],
                        "title": row["title"],
                        "decay_score": round(row["decay_score"], 4),
                        "preview": (row["text"] or "")[:100],
                    }
                    removed_passages.append(info)
                    if not dry_run:
                        conn.execute("DELETE FROM passage_fts WHERE passage_id = ?", (row["id"],))
                        conn.execute("DELETE FROM passages WHERE id = ?", (row["id"],))
            if target in ("all", "memories"):
                rows = conn.execute(
                    """
                    SELECT id, target, content, decay_score, created_at
                    FROM memory_entries
                    WHERE decay_score < ?
                    ORDER BY decay_score ASC
                    """,
                    (threshold,),
                ).fetchall()
                for row in rows:
                    info = {
                        "memory_id": row["id"],
                        "target": row["target"],
                        "decay_score": round(row["decay_score"], 4),
                        "preview": (row["content"] or "")[:100],
                        "created_at": row["created_at"],
                    }
                    removed_memories.append(info)
                    if not dry_run:
                        conn.execute("DELETE FROM memory_entries WHERE id = ?", (row["id"],))
            if not dry_run:
                conn.commit()
        return ok(
            tool,
            {
                "target": target,
                "threshold": threshold,
                "dry_run": dry_run,
                "removed_passages": len(removed_passages),
                "removed_memories": len(removed_memories),
                "passage_details": removed_passages[:20],
                "memory_details": removed_memories[:20],
            },
        )

    @staticmethod
    def _calc_decay(
        priority_base: float,
        access_count: int,
        last_access_at: Optional[str],
        now: datetime,
        lambda_decay: float,
        alpha_access: float,
    ) -> float:
        if last_access_at:
            try:
                last_dt = datetime.fromisoformat(last_access_at.replace("Z", "+00:00"))
            except (ValueError, OSError):
                last_dt = now
        else:
            last_dt = now
        days = (now - last_dt).total_seconds() / 86400.0
        import math
        score = priority_base * math.exp(-lambda_decay * days) * (1.0 + alpha_access * math.log(1.0 + access_count))
        return round(max(0.0, min(score, 10.0)), 6)

    def _now_iso(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
