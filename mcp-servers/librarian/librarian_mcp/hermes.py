"""
Hermes 记忆引擎 — 批处理 pipeline
从历史 session 中提取记忆并写入 librarian
可作为 cron job 定期运行
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from librarian_mcp.service import LibrarianService


def run(apply_memory: bool = False) -> dict:
    svc = LibrarianService()
    db = svc._connect()

    sessions = db.execute(
        "SELECT session_key FROM sessions ORDER BY created_at DESC"
    ).fetchall()

    results = []
    total_memories = 0
    total_skills = 0

    try:
        for (session_key,) in sessions:
            growth = svc.grow_session(
                session_id=session_key,
                apply_memory=apply_memory,
                apply_skill_draft=apply_memory,
            )
            if growth.get("ok"):
                data = growth["data"]
                mem_count = len(data.get("suggested_memory", []))
                has_skill = data.get("suggested_skill_draft") is not None
                applied_mem = len(data.get("applied", {}).get("memory", []))
                applied_skill = 1 if data.get("applied", {}).get("skill_draft") else 0
                results.append({
                    "session_id": session_key,
                    "suggested_memories": mem_count,
                    "suggested_skill": has_skill,
                    "applied_memories": applied_mem,
                    "applied_skill": applied_skill,
                })
                total_memories += applied_mem
                total_skills += applied_skill
            else:
                results.append({
                    "session_id": session_key,
                    "error": growth.get("error", {}).get("message", "unknown"),
                })
    finally:
        db.close()

    return {
        "sessions_processed": len(results),
        "total_memories_applied": total_memories,
        "total_skills_applied": total_skills,
        "details": results,
    }


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    result = run(apply_memory=apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
