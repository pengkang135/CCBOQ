"""Lightweight CLI for OpenClaw agent exec tool — single-call, no REPL needed."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from librarian_mcp.service import LibrarianService


def _svc():
    return LibrarianService()


def cmd_search(args: list[str]) -> None:
    query = " ".join(args) if args else ""
    if not query.strip():
        print(json.dumps({"error": "search requires a query"}, ensure_ascii=False))
        return
    result = _svc().search_summaries(query, limit=5)
    _print(result)


def cmd_excerpt(args: list[str]) -> None:
    if not args:
        print(json.dumps({"error": "usage: excerpt <vault_path> [heading] [chunk_order]"}, ensure_ascii=False))
        return
    vault_path = args[0]
    heading = args[1] if len(args) > 1 else None
    chunk_order = int(args[2]) if len(args) > 2 else None
    result = _svc().get_excerpt(vault_path, heading=heading, chunk_order=chunk_order)
    _print(result)


def cmd_list(args: list[str]) -> None:
    path_prefix = args[0] if args else None
    result = _svc().search_summaries("*", limit=50, path_prefixes=[path_prefix] if path_prefix else None)
    _print(result)


def cmd_memory(args: list[str]) -> None:
    if not args:
        result = _svc().memory_list()
    elif args[0] == "search" and len(args) > 1:
        query = " ".join(args[1:])
        result = _svc().memory_list()
        if result.get("data") and result["data"].get("index"):
            q = query.lower()
            result["data"]["index"] = [
                e for e in result["data"]["index"]
                if q in e.get("title", "").lower() or q in e.get("slug", "").lower()
            ]
            result["data"]["entry_count"] = len(result["data"]["index"])
    elif args[0] == "write":
        print(json.dumps({"error": "memory_write requires structured input"}, ensure_ascii=False))
        return
    else:
        result = _svc().memory_list(target=args[0])
    _print(result)


def cmd_price(args: list[str]) -> None:
    if not args:
        print(json.dumps({"error": "usage: price <material_name>"}, ensure_ascii=False))
        return
    query = " ".join(args)
    result = _svc().search_price_candidates(query)
    _print(result)


def cmd_maintain(args: list[str]) -> None:
    if not args:
        print(json.dumps({"error": "usage: maintain <recalc|stale|cleanup> [args...]"}, ensure_ascii=False))
        return
    sub = args[0]
    if sub == "recalc":
        target = args[1] if len(args) > 1 else "all"
        lamb = float(args[2]) if len(args) > 2 else 0.01
        alpha = float(args[3]) if len(args) > 3 else 0.3
        result = _svc().recalc_decay(target=target, lambda_decay=lamb, alpha_access=alpha)
    elif sub == "stale":
        prefix = [args[1]] if len(args) > 1 else None
        result = _svc().check_stale(prefixes=prefix)
    elif sub == "cleanup":
        target = args[1] if len(args) > 1 else "all"
        threshold = float(args[2]) if len(args) > 2 else 0.05
        dry_run = args[3].lower() != "false" if len(args) > 3 else True
        result = _svc().decay_cleanup(target=target, threshold=threshold, dry_run=dry_run)
    else:
        print(json.dumps({"error": f"unknown maintain sub-command: {sub}", "available": ["recalc", "stale", "cleanup"]}, ensure_ascii=False))
        return
    _print(result)


def cmd_vault(args: list[str]) -> None:
    if not args:
        result = _svc().list_vaults()
    elif args[0] == "list":
        result = _svc().list_vaults()
    elif args[0] == "register":
        if len(args) < 3:
            print(json.dumps({"error": "usage: vault register <path> <name> [description] [type1,type2...]"}, ensure_ascii=False))
            return
        path = args[1]
        name = args[2]
        desc = args[3] if len(args) > 3 else ""
        types = args[4].split(",") if len(args) > 4 else ["knowledge"]
        result = _svc().register_vault(path=path, name=name, description=desc, types=types)
    else:
        print(json.dumps({"error": f"unknown vault sub-command: {args[0]}", "available": ["list", "register"]}, ensure_ascii=False))
        return
    _print(result)


def cmd_session(args: list[str]) -> None:
    if not args:
        print(json.dumps({"error": "usage: session <suggest|analyze|grow> <session_id> [options...]"}, ensure_ascii=False))
        return
    sub = args[0]
    if sub == "suggest":
        if len(args) < 2:
            print(json.dumps({"error": "usage: session suggest <session_id>"}, ensure_ascii=False))
            return
        result = _svc().suggest_memories(args[1], include_conflicts=True)
    elif sub == "analyze":
        if len(args) < 2:
            print(json.dumps({"error": "usage: session analyze <session_id>"}, ensure_ascii=False))
            return
        result = _svc().analyze_session(args[1])
    elif sub == "grow":
        if len(args) < 2:
            print(json.dumps({"error": "usage: session grow <session_id> [apply_memory=true/false] [apply_skill=true/false]"}, ensure_ascii=False))
            return
        apply_memory = args[2].lower() == "true" if len(args) > 2 else False
        apply_skill = args[3].lower() == "true" if len(args) > 3 else False
        result = _svc().grow_session(args[1], apply_memory=apply_memory, apply_skill_draft=apply_skill)
    else:
        print(json.dumps({"error": f"unknown session sub-command: {sub}", "available": ["suggest", "analyze", "grow"]}, ensure_ascii=False))
        return
    _print(result)


def cmd_vec(args: list[str]) -> None:
    if not args:
        print(json.dumps({"error": "usage: vec <search|reindex|stats|hyb> [args...]"}, ensure_ascii=False))
        return
    sub = args[0]
    svc = _svc()
    if sub == "search":
        if len(args) < 2:
            print(json.dumps({"error": "usage: vec search <query> [limit] [target]"}, ensure_ascii=False))
            return
        query = args[1]
        limit = int(args[2]) if len(args) > 2 else 10
        target = args[3] if len(args) > 3 else "passages"
        try:
            from librarian_mcp import embedding, vector_index as vi
            emb = embedding.encode(query)
            db = svc._connect()
            try:
                if target == "memories":
                    results = vi.search_similar_memories(db, embedding=emb, k=limit)
                else:
                    results = vi.search_similar_passages(db, embedding=emb, k=limit)
                print(json.dumps({"ok": True, "tool": "vec_search", "data": {"query": query, "count": len(results), "results": results}}, ensure_ascii=False, default=str))
            finally:
                db.close()
        except ImportError:
            print(json.dumps({"error": "embedding model not available"}, ensure_ascii=False))
    elif sub == "reindex":
        try:
            from librarian_mcp import embedding, vector_index as vi
            db = svc._connect()
            try:
                vi.ensure_vec_tables(db)
                p = vi.reindex_all_passages(db, embedding.encode)
                m = vi.reindex_all_memories(db, embedding.encode)
                print(json.dumps({"ok": True, "tool": "vec_reindex", "data": {"passages": p, "memories": m}}, ensure_ascii=False, default=str))
            finally:
                db.close()
        except ImportError:
            print(json.dumps({"error": "embedding model not available"}, ensure_ascii=False))
    elif sub == "stats":
        try:
            from librarian_mcp import vector_index as vi
            db = svc._connect()
            try:
                vi.ensure_vec_tables(db)
                stats = vi.get_vec_stats(db)
                print(json.dumps({"ok": True, "tool": "vec_stats", "data": stats}, ensure_ascii=False, default=str))
            finally:
                db.close()
        except ImportError:
            print(json.dumps({"error": "vector module not available"}, ensure_ascii=False))
    elif sub == "hyb":
        if len(args) < 2:
            print(json.dumps({"error": "usage: vec hyb <query> [limit] [fts_weight]"}, ensure_ascii=False))
            return
        query = args[1]
        limit = int(args[2]) if len(args) > 2 else 10
        fts_weight = float(args[3]) if len(args) > 3 else 0.4
        try:
            from librarian_mcp import embedding, vector_index as vi
            emb = embedding.encode(query)
            db = svc._connect()
            try:
                results = vi.hybrid_search(db, query_text=query, embedding=emb, k=limit, fts_weight=fts_weight, vec_weight=1.0 - fts_weight)
                print(json.dumps({"ok": True, "tool": "hyb_search", "data": {"query": query, "count": len(results), "results": results}}, ensure_ascii=False, default=str))
            finally:
                db.close()
        except ImportError:
            print(json.dumps({"error": "embedding model not available"}, ensure_ascii=False))
    else:
        print(json.dumps({"error": f"unknown vec sub-command: {sub}", "available": ["search", "reindex", "stats", "hyb"]}, ensure_ascii=False))


def _print(result: dict) -> None:
    out = json.dumps(result, ensure_ascii=False, default=str)
    max_chars = 8000
    if len(out) > max_chars:
        data = result.get("data", [])
        if isinstance(data, list):
            data = data[:5]
        elif isinstance(data, dict):
            data = {"(truncated)": f"dict with {len(data)} keys"}
        truncated = json.dumps({
            "ok": result.get("ok", True),
            "tool": result.get("tool", "unknown"),
            "data": data,
            "truncated": True,
            "original_chars": len(out),
        }, ensure_ascii=False, default=str)
        sys.stdout.buffer.write(truncated.encode("utf-8"))
    else:
        sys.stdout.buffer.write(out.encode("utf-8"))


COMMANDS = {
    "search": cmd_search,
    "excerpt": cmd_excerpt,
    "list": cmd_list,
    "memory": cmd_memory,
    "price": cmd_price,
    "maintain": cmd_maintain,
    "vault": cmd_vault,
    "session": cmd_session,
    "vec": cmd_vec,
}


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": "usage: cli.py <search|excerpt|list|memory|price|maintain|vault|session|vec> [args...]",
            "commands": sorted(COMMANDS.keys()),
        }, ensure_ascii=False))
        return
    cmd = sys.argv[1]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(json.dumps({"error": f"unknown command: {cmd}", "commands": sorted(COMMANDS.keys())}, ensure_ascii=False))
        return
    fn(sys.argv[2:])


if __name__ == "__main__":
    main()
