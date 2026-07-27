"""
Librarian 维护预检与记录工具。

用法:
  python maintenance.py --precheck         # 预检变更，输出维护计划 JSON
  python maintenance.py --record           # 记录维护完成（更新 ref 与时间戳）
  python maintenance.py --lint             # 深度扫描 Knowledge/ 全部 source_note 过期情况
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LIBRARY_DIR = Path("F:/FeynmanLibrary/.library")
MAINTENANCE_REF_FILE = LIBRARY_DIR / "maintenance_ref"
MAINTENANCE_LAST_RUN = LIBRARY_DIR / "maintenance_last_run"
MAINTENANCE_NEEDED = LIBRARY_DIR / "maintenance_needed.json"
COOLDOWN_SECONDS = 2 * 60 * 60  # 2 小时

DOC_TYPES = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".xlsm"}
TEXT_TYPES = {".md", ".txt", ".csv", ".rtf", ".html", ".htm", ".epub", ".odt"}


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(LIBRARY_DIR.parent),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {result.stderr}")
    return result.stdout.strip()


def get_changed_files(baseref: str) -> list[str]:
    """获取从 baseref 到 HEAD 的变更文件列表。"""
    output = run_git("diff", "--name-only", baseref, "HEAD")
    if not output:
        return []
    return [f for f in output.split("\n") if f.strip()]


def get_change_stats(baseref: str, filepath: str) -> tuple[int, int]:
    """返回 (insertions, deletions) 统计。"""
    output = run_git("diff", "--numstat", baseref, "HEAD", "--", filepath)
    if not output:
        return 0, 0
    parts = output.split("\t")
    insertions = int(parts[0]) if parts[0] != "-" else 0
    deletions = int(parts[1]) if parts[1] != "-" else 0
    return insertions, deletions


def get_file_lines(filepath: str) -> int:
    """获取文件当前总行数。"""
    full_path = LIBRARY_DIR.parent / filepath
    if not full_path.exists():
        return 0
    try:
        with open(full_path, encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def classify_file(filepath: str, baseref: str) -> dict:
    """分类单个文件并返回维护级别。"""
    suffix = Path(filepath).suffix.lower()
    full_path = LIBRARY_DIR.parent / filepath

    # 文件已删除
    if not full_path.exists():
        return {
            "path": filepath,
            "status": "deleted",
            "level": "L0",
            "reason": "文件已删除，需从索引移除",
        }

    # 新文件
    is_new = False
    try:
        run_git("cat-file", "-e", f"{baseref}:{filepath}")
    except RuntimeError:
        is_new = True

    if is_new:
        if suffix in DOC_TYPES:
            return {
                "path": filepath,
                "status": "new",
                "level": "L1",
                "reason": "新文档文件，需完整提取摘要",
            }
        else:
            return {
                "path": filepath,
                "status": "new",
                "level": "L0",
                "reason": "新文本文件，FTS5 重建索引即可",
            }

    # 已有文件的变更
    insertions, deletions = get_change_stats(baseref, filepath)
    total_lines = get_file_lines(filepath)
    changed = insertions + deletions

    if changed == 0:
        return {
            "path": filepath,
            "status": "unchanged",
            "level": "skip",
            "reason": "无实际变更",
        }

    # 计算变更比例（以变更行相对于当前总行数）
    ratio = changed / max(total_lines, 1)

    if suffix in DOC_TYPES:
        # 文档文件：任何变更都可能需要 L1
        if ratio < 0.05:
            return {
                "path": filepath,
                "status": "modified",
                "level": "L0",
                "reason": f"文档轻微变更 ({ratio:.1%})，仅重建索引",
                "change_ratio": round(ratio, 4),
                "insertions": insertions,
                "deletions": deletions,
            }
        else:
            return {
                "path": filepath,
                "status": "modified",
                "level": "L1",
                "reason": f"文档显著变更 ({ratio:.1%})，需重新提取摘要",
                "change_ratio": round(ratio, 4),
                "insertions": insertions,
                "deletions": deletions,
            }
    else:
        # 文本文件：通常 L0 足够
        if ratio < 0.20:
            return {
                "path": filepath,
                "status": "modified",
                "level": "L0",
                "reason": f"文本轻微变更 ({ratio:.1%})，FTS5 重建索引",
                "change_ratio": round(ratio, 4),
                "insertions": insertions,
                "deletions": deletions,
            }
        else:
            return {
                "path": filepath,
                "status": "modified",
                "level": "L0",
                "reason": f"文本显著变更 ({ratio:.1%})，重建索引（文本文件无需 LLM 摘要）",
                "change_ratio": round(ratio, 4),
                "insertions": insertions,
                "deletions": deletions,
            }


def check_cooldown() -> tuple[bool, float]:
    """检查冷却期。返回 (elapsed, remaining_seconds)。"""
    if not MAINTENANCE_LAST_RUN.exists():
        return True, 0
    try:
        last_run = float(MAINTENANCE_LAST_RUN.read_text().strip())
    except (ValueError, OSError):
        return True, 0
    elapsed = time.time() - last_run
    remaining = COOLDOWN_SECONDS - elapsed
    return elapsed >= COOLDOWN_SECONDS, max(0, remaining)


def precheck() -> dict:
    """预检主逻辑。"""
    now = datetime.now(timezone.utc).isoformat()

    # 获取维护基线
    if MAINTENANCE_REF_FILE.exists():
        baseref = MAINTENANCE_REF_FILE.read_text().strip()
    else:
        # 首次运行：用最近一次提交作为基线
        baseref = run_git("rev-list", "--max-parents=0", "HEAD")
        if not baseref:
            return {
                "ok": True,
                "action": "init",
                "message": "无基线提交，跳过维护",
                "timestamp": now,
            }

    # 验证 baseref 存在
    try:
        run_git("cat-file", "-e", baseref)
    except RuntimeError:
        # baseref 不存在，重置为最新提交
        baseref = run_git("rev-parse", "HEAD~10")
        if not baseref:
            return {
                "ok": True,
                "action": "skip",
                "message": "无法确定基线，跳过维护",
                "timestamp": now,
            }

    # 获取变更文件
    try:
        changed = get_changed_files(baseref)
    except RuntimeError:
        return {
            "ok": False,
            "action": "error",
            "message": "git diff 执行失败",
            "timestamp": now,
        }

    if not changed:
        return {
            "ok": True,
            "action": "skip",
            "message": "无文件变更",
            "baseref": baseref,
            "changed_count": 0,
            "timestamp": now,
        }

    # 分类文件
    files = []
    l0_files = []
    l1_files = []
    deleted_files = []

    for f in changed:
        info = classify_file(f, baseref)
        files.append(info)
        if info["level"] == "L1":
            l1_files.append(info)
        elif info["status"] == "deleted":
            deleted_files.append(info)
        elif info["level"] == "L0":
            l0_files.append(info)

    # 冷却期检查
    cooldown_ok, cooldown_remaining = check_cooldown()

    should_run = (l0_files or l1_files or deleted_files) and cooldown_ok

    result = {
        "ok": True,
        "action": "maintain" if should_run else "skip",
        "baseref": baseref,
        "current_head": run_git("rev-parse", "HEAD"),
        "changed_count": len(changed),
        "l0_count": len(l0_files),
        "l1_count": len(l1_files),
        "deleted_count": len(deleted_files),
        "cooldown_elapsed": cooldown_ok,
        "cooldown_remaining_seconds": cooldown_remaining,
        "needs_maintenance": bool(l0_files or l1_files or deleted_files),
        "timestamp": now,
        "files": files,
        "summary": {
            "L0": [f["path"] for f in l0_files],
            "L1": [f["path"] for f in l1_files],
            "deleted": [f["path"] for f in deleted_files],
        },
    }

    return result


def record() -> dict:
    """记录维护完成，更新基线引用和时间戳。"""
    now = datetime.now(timezone.utc).isoformat()
    head = run_git("rev-parse", "HEAD")

    MAINTENANCE_REF_FILE.write_text(head)
    MAINTENANCE_LAST_RUN.write_text(str(time.time()))

    # 清理维护需求标记
    if MAINTENANCE_NEEDED.exists():
        MAINTENANCE_NEEDED.unlink()

    return {
        "ok": True,
        "action": "recorded",
        "new_ref": head,
        "timestamp": now,
    }


def lint() -> dict:
    """深度扫描 Knowledge/ 下所有 source_note 的过期情况。"""
    from librarian_mcp.config import DB_PATH

    now = datetime.now(timezone.utc).isoformat()
    stale_notes = []

    if not DB_PATH.exists():
        return {
            "ok": False,
            "action": "error",
            "message": f"数据库不存在: {DB_PATH}",
            "timestamp": now,
        }

    import sqlite3

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 查询 Knowledge/ 和 DocWork/ 下的所有文档
    rows = conn.execute(
        """
        SELECT vault_path, file_mtime, updated_at
        FROM documents
        WHERE vault_path LIKE 'Knowledge/%' OR vault_path LIKE 'DocWork/%'
        ORDER BY vault_path
        """
    ).fetchall()

    vault_root = LIBRARY_DIR.parent

    for row in rows:
        vault_path = row["vault_path"]
        source_path = vault_root / vault_path

        if not source_path.exists():
            stale_notes.append(
                {
                    "vault_path": vault_path,
                    "status": "source_missing",
                    "reason": "源文件已不存在",
                }
            )
            continue

        source_mtime = source_path.stat().st_mtime
        indexed_mtime_str = row["file_mtime"] or ""
        indexed_mtime = 0.0
        if indexed_mtime_str:
            try:
                indexed_mtime = datetime.fromisoformat(indexed_mtime_str).timestamp()
            except (ValueError, OSError):
                indexed_mtime = 0.0

        if source_mtime > indexed_mtime + 1.0:
            stale_notes.append(
                {
                    "vault_path": vault_path,
                    "status": "stale",
                    "reason": "源文件已更新但摘要未刷新",
                    "source_mtime": datetime.fromtimestamp(source_mtime, tz=timezone.utc).isoformat(),
                    "indexed_at": row["updated_at"],
                }
            )

    conn.close()

    return {
        "ok": True,
        "action": "lint",
        "total_notes": len(rows),
        "stale_count": len(stale_notes),
        "stale_notes": stale_notes,
        "timestamp": now,
    }


def main():
    if len(sys.argv) < 2:
        print("用法: maintenance.py --precheck | --record | --lint", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    try:
        if cmd == "--precheck":
            result = precheck()
        elif cmd == "--record":
            result = record()
        elif cmd == "--lint":
            result = lint()
        else:
            print(f"未知命令: {cmd}", file=sys.stderr)
            sys.exit(1)

        print(json.dumps(result, ensure_ascii=False, indent=2))

        if not result.get("ok"):
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
