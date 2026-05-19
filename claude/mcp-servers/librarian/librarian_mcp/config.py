from pathlib import Path

VAULT_ROOT = Path("F:/FeynmanLibrary")
LIBRARY_DIR = VAULT_ROOT / ".library"
DB_PATH = LIBRARY_DIR / "library.db"
ERROR_LOG_PATH = LIBRARY_DIR / "index-errors.log"
MEMORY_DIR = LIBRARY_DIR / "memory"
MEMORY_FILE = MEMORY_DIR / "MEMORY.md"
USER_FILE = MEMORY_DIR / "USER.md"
SKILLS_LIBRARY_DIR = LIBRARY_DIR / "skills"
SKILLS_INDEX_PATH = SKILLS_LIBRARY_DIR / "index.json"
LIBRARIAN_ROOT = VAULT_ROOT / "Librarian"
MEMORY_VAULT_DIR = LIBRARIAN_ROOT / "Memory"
MEMORY_INDEX_PATH = MEMORY_VAULT_DIR / "MEMORY_INDEX.md"
SESSION_ROOT = LIBRARIAN_ROOT / "SessionNotes"
SKILL_DRAFT_ROOT = LIBRARIAN_ROOT / "SkillDrafts"
AGENT_SKILL_ROOT = LIBRARIAN_ROOT / "AgentSkills"
DEFAULT_INDEX_PREFIXES = (
    "Knowledge",
    "DocWork",
    "Librarian/SessionNotes",
    "Librarian/AgentSkills",
    "Librarian/Memory",
)
EXCLUDED_INDEX_PREFIXES = (
    "Knowledge/Agent_Design/",
    "Librarian/Agent_Design/",
    "Librarian/Templates/",
    "Librarian/SkillDrafts/",
)
MAX_SEARCH_LIMIT = 20
MIN_SEARCH_LIMIT = 1

# 外部根路径映射 — 用于索引 vault 外的文件（如共享网盘）。
# key 是简称，value 是绝对路径，在路径中以 @key: 前缀引用。
EXTERNAL_ROOTS: dict[str, Path] = {
    "onedrive": Path("f:\\OneDriveCHEC\\OneDrive - China Harbour Engineering Company Ltd"),
}
SOURCE_NOTES_DIR = LIBRARY_DIR / "source_notes"

# 文件类型过滤：白名单（可提取文本的后缀）和临时文件黑名单
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".xlsm",
    ".csv", ".md", ".txt", ".rtf", ".html", ".htm", ".epub", ".odt",
})

TEMP_SUFFIXES: frozenset[str] = frozenset({".tmp", ".temp", ".bak"})

# ingest_inbox 默认扫描前缀
INBOX_PREFIXES: tuple[str, ...] = ("DocWork",)


def is_supported_source_file(path: Path) -> bool:
    """可提取文本的文件类型白名单。"""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def is_temp_file(path: Path) -> bool:
    """检测临时文件 / Office 锁文件 / 隐藏文件。"""
    name = path.name
    if name.startswith("~$") or name.startswith("._"):
        return True
    if name.startswith("."):
        return True
    if path.suffix.lower() in TEMP_SUFFIXES:
        return True
    return False
