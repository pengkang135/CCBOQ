from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional
import re

from librarian_mcp.config import (
    EXTERNAL_ROOTS,
    SOURCE_NOTES_DIR,
    VAULT_ROOT,
    is_supported_source_file,
    is_temp_file,
)
from librarian_mcp.service import LibrarianService, fail, ok

HF_HOME = VAULT_ROOT / "Models" / "huggingface"
HF_HUB_CACHE = HF_HOME / "hub"
TRANSFORMERS_CACHE = HF_HOME / "transformers"
DATALAB_MODEL_CACHE = VAULT_ROOT / "Models" / "datalab"
PDF_TABLES_PYTHON = VAULT_ROOT / ".venvs" / "pdf_tables" / "Scripts" / "python.exe"
PDF_TABLES_SCRIPT = Path(__file__).resolve().parent / "scripts" / "extract_pdf_tables.py"
TABLE_HEAVY_KEYWORDS = ("信息价", "价格", "报价", "市场价", "苗木", "报表", "清单")
PRICE_FILE_SIGNALS = ("信息价", "价格表", "报价单", "市场价", "材料价", "设备价", "苗木", "造价")
PRICES_DIR = VAULT_ROOT / ".library" / "prices"
JAVA_HOME_CANDIDATES = sorted((Path(r"C:\Program Files\Java")).glob("jdk-*"), reverse=True) if Path(r"C:\Program Files\Java").exists() else []
JAVA_HOME = next((candidate for candidate in JAVA_HOME_CANDIDATES if (candidate / "bin" / "server" / "jvm.dll").exists()), None)


@dataclass(frozen=True)
class ProcessorInfo:
    name: str
    command_path: Optional[Path]

    @property
    def available(self) -> bool:
        return self.command_path is not None


@dataclass(frozen=True)
class QualityAssessment:
    accepted: bool
    reason: str
    metrics: dict[str, int]


PROCESSOR_CANDIDATES: dict[str, list[str]] = {
    "pdf_tables": [
        str(PDF_TABLES_PYTHON),
        str(VAULT_ROOT / ".venv" / "Scripts" / "python.exe"),
    ],
    "markitdown": [
        "markitdown",
        str(VAULT_ROOT / ".venvs" / "source_ingest" / "Scripts" / "markitdown.exe"),
        str(VAULT_ROOT / ".venvs" / "source_ingest" / "Scripts" / "markitdown"),
    ],
    "docling": [
        "docling",
        str(VAULT_ROOT / ".venvs" / "docling" / "Scripts" / "docling.exe"),
        str(VAULT_ROOT / ".venvs" / "docling" / "Scripts" / "docling"),
        str(VAULT_ROOT / ".venvs" / "source_ingest" / "Scripts" / "docling.exe"),
    ],
    "marker": [
        "marker_single",
        str(VAULT_ROOT / ".venvs" / "marker" / "Scripts" / "marker_single.exe"),
        str(VAULT_ROOT / ".venvs" / "source_ingest" / "Scripts" / "marker_single.exe"),
    ],
    "pandoc": [
        "pandoc",
        str(VAULT_ROOT / ".tools" / "pandoc" / "pandoc.exe"),
        str(VAULT_ROOT / ".venvs" / "pandoc" / "Lib" / "site-packages" / "pypandoc" / "files" / "pandoc.exe"),
        str(VAULT_ROOT / ".venvs" / "pandoc" / "Lib" / "site-packages" / "pypandoc" / "files" / "pandoc"),
    ],
}

PROCESSOR_ORDER_BY_SUFFIX: dict[str, list[str]] = {
    ".pdf": ["markitdown", "docling", "marker"],
    ".doc": ["markitdown", "pandoc", "docling"],
    ".docx": ["markitdown", "pandoc", "docling"],
    ".ppt": ["markitdown", "pandoc", "docling"],
    ".pptx": ["markitdown", "pandoc", "docling"],
    ".xls": ["markitdown", "pandoc", "docling"],
    ".xlsx": ["markitdown", "pandoc", "docling"],
    ".xlsm": ["markitdown", "pandoc", "docling"],
    ".csv": ["markitdown", "pandoc"],
    ".html": ["markitdown", "pandoc", "docling"],
    ".htm": ["markitdown", "pandoc", "docling"],
    ".epub": ["markitdown", "pandoc"],
    ".md": ["pandoc", "markitdown"],
    ".txt": ["pandoc", "markitdown"],
    ".rtf": ["pandoc", "markitdown"],
    ".odt": ["pandoc", "markitdown"],
}


class SourceIngestService:
    def __init__(self, vault_root: Path = VAULT_ROOT) -> None:
        self.vault_root = Path(vault_root)
        self.temp_root = self.vault_root / "temp" / "ingest"

    def inspect_processors(self) -> dict:
        processors = [self._processor_to_dict(info) for info in self._all_processors().values()]
        return ok("inspect_processors", {"processors": processors})

    def ingest_inbox(
        self,
        path_prefixes: list[str] | None = None,
        force: bool = False,
        dry_run: bool = False,
        reindex: bool = False,
    ) -> dict:
        tool = "ingest_inbox"
        prefixes = path_prefixes or ["DocWork"]
        normalized_prefixes = [p.replace("\\", "/").strip().rstrip("/") for p in prefixes]

        scanned_files: list[tuple[Path, str]] = []
        for prefix in normalized_prefixes:
            scan_root = self.vault_root / prefix
            if not scan_root.exists():
                continue
            for file_path in scan_root.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() == ".md":
                    continue
                if not is_supported_source_file(file_path):
                    continue
                if is_temp_file(file_path):
                    continue
                rel = self._to_vault_relative(file_path)
                scanned_files.append((file_path, rel))

        # Query existing documents
        from librarian_mcp.service import LibrarianService

        svc = LibrarianService(self.vault_root)
        existing: dict[str, tuple[str, str]] = {}  # source_path -> (vault_path, file_mtime)
        with svc._connect() as conn:
            svc._init_schema(conn)
            clauses = " OR ".join(["d.source_path LIKE ?"] * len(normalized_prefixes))
            rows = conn.execute(
                f"""
                SELECT d.source_path, d.vault_path, d.file_mtime
                FROM documents d
                WHERE d.source_path IS NOT NULL
                  AND ({clauses})
                """,
                [f"{p}%" for p in normalized_prefixes],
            ).fetchall()
            for row in rows:
                existing[row["source_path"]] = (row["vault_path"], row["file_mtime"])

        new_files: list[tuple[Path, str]] = []
        modified_files: list[tuple[Path, str]] = []
        skipped_count = 0

        for file_path, rel in scanned_files:
            existing_entry = existing.get(rel)
            if existing_entry is None:
                new_files.append((file_path, rel))
            else:
                current_mtime = svc._file_mtime_iso(file_path)
                _, indexed_mtime = existing_entry
                if force or current_mtime > indexed_mtime:
                    modified_files.append((file_path, rel))
                else:
                    skipped_count += 1

        if dry_run:
            return ok(
                tool,
                {
                    "scanned": len(scanned_files),
                    "new": len(new_files),
                    "modified": len(modified_files),
                    "skipped": skipped_count,
                    "dry_run": True,
                    "new_files": [rel for _, rel in new_files],
                    "modified_files": [rel for _, rel in modified_files],
                },
            )

        details: list[dict] = []
        succeeded = 0
        failed = 0
        for file_path, rel in new_files:
            result = self.ingest_source(source_path=rel, force=force)
            status = "succeeded" if result.get("status") == "ok" else "failed"
            if status == "succeeded":
                succeeded += 1
            else:
                failed += 1
            details.append({
                "source_path": rel,
                "status": f"new/{status}",
                "error": result.get("error") if status == "failed" else None,
            })

        for file_path, rel in modified_files:
            result = self.ingest_source(source_path=rel, force=True)
            status = "succeeded" if result.get("status") == "ok" else "failed"
            if status == "succeeded":
                succeeded += 1
            else:
                failed += 1
            details.append({
                "source_path": rel,
                "status": f"modified/{status}",
                "error": result.get("error") if status == "failed" else None,
            })

        reindex_result = None
        if reindex:
            reindex_result = svc.reindex(prefixes=normalized_prefixes)

        return ok(
            tool,
            {
                "scanned": len(scanned_files),
                "new": len(new_files),
                "modified": len(modified_files),
                "skipped": skipped_count,
                "processed": succeeded + failed,
                "succeeded": succeeded,
                "failed": failed,
                "reindexed": reindex_result,
                "details": details,
            },
        )

    def ingest_source(
        self,
        source_path: str,
        processor: str = "auto",
        force: bool = False,
        reindex: bool = False,
        title: Optional[str] = None,
        index_only: bool = False,
        external_root: Optional[str] = None,
    ) -> dict:
        tool = "ingest_source"

        if external_root:
            root = EXTERNAL_ROOTS.get(external_root)
            if root is None:
                return fail(tool, "UNKNOWN_EXTERNAL_ROOT", f"unknown external root: {external_root}", {"external_root": external_root})
            normalized_source = Path(source_path)
            absolute_source = (root / source_path).resolve()
            if not absolute_source.exists():
                return fail(tool, "SOURCE_NOT_FOUND", "source file does not exist", {"source_path": source_path, "resolved": str(absolute_source)})
            if absolute_source.is_dir():
                return fail(tool, "SOURCE_IS_DIRECTORY", "source_path must point to a file", {"source_path": source_path})
            external_source_prefix = f"@{external_root}:"
            relative_source_str = f"{external_source_prefix}{normalized_source.as_posix()}"
        else:
            try:
                normalized_source = self._resolve_input_path(source_path)
            except ValueError as exc:
                return fail(tool, "INVALID_SOURCE_PATH", str(exc), {"source_path": source_path})
            absolute_source = self.vault_root / normalized_source
            if not absolute_source.exists():
                return fail(tool, "SOURCE_NOT_FOUND", "source file does not exist", {"source_path": normalized_source.as_posix()})
            if absolute_source.is_dir():
                return fail(tool, "SOURCE_IS_DIRECTORY", "source_path must point to a file", {"source_path": normalized_source.as_posix()})
            external_source_prefix = ""
            relative_source_str = self._to_vault_relative(normalized_source)

        if not is_supported_source_file(absolute_source):
            return fail(
                tool,
                "UNSUPPORTED_FILE_TYPE",
                f"file type '{absolute_source.suffix}' is not in the supported extensions whitelist",
                {"source_path": normalized_source.as_posix(), "suffix": absolute_source.suffix},
            )
        if is_temp_file(absolute_source):
            return fail(
                tool,
                "TEMP_FILE_SKIPPED",
                "temporary or lock file detected, skipping",
                {"source_path": normalized_source.as_posix(), "filename": absolute_source.name},
            )

        suffix = absolute_source.suffix.lower()
        route = PROCESSOR_ORDER_BY_SUFFIX.get(suffix)
        if not route:
            return fail(
                tool,
                "UNSUPPORTED_FORMAT",
                "no processor route is defined for this file type",
                {"source_path": normalized_source.as_posix(), "suffix": suffix},
            )

        processors = self._all_processors()
        if processor != "auto" and processor not in processors:
            return fail(tool, "UNKNOWN_PROCESSOR", "processor must be auto or a known processor", {"processor": processor})

        candidate_names = self._resolve_candidate_names(absolute_source, route, processor)
        available_candidates = [name for name in candidate_names if processors[name].available]
        if not available_candidates:
            return fail(
                tool,
                "PROCESSOR_NOT_AVAILABLE",
                "no available processor found for this file",
                {
                    "source_path": normalized_source.as_posix(),
                    "requested_processor": processor,
                    "route": candidate_names,
                    "processors": [self._processor_to_dict(info) for info in processors.values()],
                },
            )

        attempts: list[dict] = []
        work_root = self._work_root_for_source(normalized_source)
        work_root.mkdir(parents=True, exist_ok=True)

        converted_markdown: Optional[Path] = None
        extracted_content: Optional[str] = None
        selected_processor: Optional[str] = None
        for candidate_name in available_candidates:
            processor_info = processors[candidate_name]
            attempt_root = work_root / candidate_name
            if attempt_root.exists():
                shutil.rmtree(attempt_root)
            attempt_root.mkdir(parents=True, exist_ok=True)
            try:
                candidate_markdown = self._run_processor(candidate_name, processor_info.command_path, absolute_source, attempt_root)
                candidate_content = self._load_markdown(candidate_markdown)
                quality = self._assess_markdown_quality(candidate_content, suffix)
                if quality.accepted:
                    converted_markdown = candidate_markdown
                    extracted_content = candidate_content
                    selected_processor = candidate_name
                    attempts.append(
                        {
                            "processor": candidate_name,
                            "status": "success",
                            "work_markdown_path": self._to_vault_relative(candidate_markdown),
                            "quality": {
                                "accepted": True,
                                "reason": quality.reason,
                                "metrics": quality.metrics,
                            },
                        }
                    )
                    break
                attempts.append(
                    {
                        "processor": candidate_name,
                        "status": "rejected",
                        "message": quality.reason,
                        "work_markdown_path": self._to_vault_relative(candidate_markdown),
                        "quality": {
                            "accepted": False,
                            "reason": quality.reason,
                            "metrics": quality.metrics,
                        },
                    }
                )
            except RuntimeError as exc:
                attempts.append({"processor": candidate_name, "status": "failed", "message": str(exc)})

        if converted_markdown is None or selected_processor is None:
            return fail(
                tool,
                "CONVERSION_FAILED",
                "all available processors failed",
                {
                    "source_path": normalized_source.as_posix(),
                    "attempts": attempts,
                },
            )

        if extracted_content is None or not extracted_content.strip():
            return fail(
                tool,
                "EMPTY_OUTPUT",
                "processor completed but produced empty markdown",
                {
                    "source_path": normalized_source.as_posix(),
                    "processor": selected_processor,
                    "work_markdown_path": self._to_vault_relative(converted_markdown),
                },
            )

        if index_only:
            slug = "__".join(Path(relative_source_str.replace(":", "__").replace("@", "")).with_suffix("").parts)
            source_note_path = SOURCE_NOTES_DIR / f"{slug}.source_note.md"
            source_note_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            source_note_path = absolute_source.with_name(f"{absolute_source.stem}.source_note.md")
            if source_note_path.exists() and not force:
                return fail(
                    tool,
                    "TARGET_EXISTS",
                    "source note already exists; use force to overwrite",
                    {"target_path": self._to_vault_relative(source_note_path)},
                )

        relative_source_for_note = relative_source_str if external_root else normalized_source

        # Forked conversion: price-signal PDFs get parallel pdf_tables run for structured CSV
        price_csv_path: Optional[str] = None
        if suffix == ".pdf" and self._has_price_file_signals(absolute_source):
            price_csv_path = self._run_price_table_extraction(absolute_source, work_root)

        layered_outputs = self._collect_layered_outputs(selected_processor, converted_markdown)
        # Merge price CSV into layered outputs so it appears in the metadata section
        if price_csv_path and not layered_outputs:
            layered_outputs = {"paths": {"records_csv": price_csv_path}, "stats": {}, "lookup_content": ""}
        elif price_csv_path and layered_outputs:
            paths = layered_outputs.setdefault("paths", {})
            if "records_csv" not in paths:
                paths["records_csv"] = price_csv_path

        source_note_text = self._render_source_note(
            source_file=absolute_source,
            relative_source=relative_source_for_note,
            converted_markdown=converted_markdown,
            processor=selected_processor,
            content=extracted_content,
            layered_outputs=layered_outputs,
            title=title,
        )
        source_note_path.write_text(source_note_text, encoding="utf-8")

        index_result = None
        relative_source_note = self._to_vault_relative(source_note_path)
        try:
            librarian = LibrarianService(self.vault_root)
            with librarian._connect() as conn:
                librarian._init_schema(conn)
                librarian._index_single_path(conn, relative_source_note)
            index_result = {
                "indexed": True,
                "vault_path": relative_source_note,
            }
        except Exception as exc:
            index_result = {
                "indexed": False,
                "vault_path": relative_source_note,
                "error": str(exc),
            }

        reindex_result = None
        if reindex:
            prefix = normalized_source.parts[0]
            reindex_result = LibrarianService(self.vault_root).reindex([prefix])

        return ok(
            tool,
            {
                "source_path": self._to_vault_relative(absolute_source) if not external_root else relative_source_str,
                "source_note_path": self._to_vault_relative(source_note_path),
                "selected_processor": selected_processor,
                "index_only": index_only,
                "external_root": external_root,
                "route": candidate_names,
                "auto_switched": processor == "auto" and selected_processor != candidate_names[0],
                "attempts": attempts,
                "work_markdown_path": self._to_vault_relative(converted_markdown),
                "index_result": index_result,
                "reindex_result": reindex_result,
                "processors": [self._processor_to_dict(info) for info in processors.values()],
            },
        )

    def _all_processors(self) -> dict[str, ProcessorInfo]:
        return {name: ProcessorInfo(name=name, command_path=self._resolve_processor_path(name)) for name in PROCESSOR_CANDIDATES}

    def _resolve_processor_path(self, name: str) -> Optional[Path]:
        for candidate in PROCESSOR_CANDIDATES[name]:
            resolved = shutil.which(candidate)
            if resolved:
                return Path(resolved)
            candidate_path = Path(candidate)
            if candidate_path.exists():
                return candidate_path
        return None

    def _resolve_candidate_names(self, source_file: Path, route: list[str], processor: str) -> list[str]:
        if processor != "auto":
            return [processor]
        candidate_names = list(route)
        if source_file.suffix.lower() == ".pdf" and self._looks_like_table_heavy_pdf(source_file) and not self._has_price_file_signals(source_file):
            candidate_names = ["pdf_tables"] + candidate_names
        return list(dict.fromkeys(candidate_names))

    def _looks_like_table_heavy_pdf(self, source_file: Path) -> bool:
        name = source_file.stem
        try:
            relative = self._to_vault_relative(source_file)
            text = f"{relative} {name}"
        except ValueError:
            text = name
        return any(keyword in text for keyword in TABLE_HEAVY_KEYWORDS)

    @staticmethod
    def _has_price_file_signals(source_file: Path) -> bool:
        """Price-specific signals distinct from generic table-heavy heuristics."""
        text = f"{source_file}"
        return any(kw in text for kw in PRICE_FILE_SIGNALS)

    def _run_processor(self, processor: str, command_path: Optional[Path], source_file: Path, output_root: Path) -> Path:
        if command_path is None:
            raise RuntimeError(f"{processor} is not available")
        target_md = output_root / f"{source_file.stem}.md"
        effective_source = source_file
        env = os.environ.copy()

        if HF_HOME.exists():
            env["HF_HOME"] = str(HF_HOME)
            env["HF_HUB_CACHE"] = str(HF_HUB_CACHE)
            env["HUGGINGFACE_HUB_CACHE"] = str(HF_HUB_CACHE)
            env["TRANSFORMERS_CACHE"] = str(TRANSFORMERS_CACHE)
        env["MODEL_CACHE_DIR"] = str(DATALAB_MODEL_CACHE)
        if JAVA_HOME is not None:
            env["JAVA_HOME"] = str(JAVA_HOME)
            env["PATH"] = f"{JAVA_HOME / 'bin'};{env.get('PATH', '')}"

        if processor == "markitdown":
            command = [str(command_path), str(effective_source), "-o", str(target_md)]
        elif processor == "pdf_tables":
            effective_source = self._prepare_ascii_alias(source_file, output_root)
            command = [
                str(command_path),
                str(PDF_TABLES_SCRIPT),
                "--input",
                str(effective_source),
                "--output-dir",
                str(output_root),
                "--engine",
                "auto_lattice",
                "--stem",
                source_file.stem,
                "--source-name",
                source_file.name,
            ]
        elif processor == "docling":
            effective_source = self._prepare_ascii_alias(source_file, output_root)
            command = [str(command_path), str(effective_source), "--to", "md", "--output", str(output_root)]
        elif processor == "marker":
            effective_source = self._prepare_ascii_alias(source_file, output_root)
            command = [str(command_path), str(effective_source), "--output_format", "markdown", "--output_dir", str(output_root)]
        elif processor == "pandoc":
            command = [str(command_path), str(effective_source), "-t", "gfm", "-o", str(target_md)]
        else:
            raise RuntimeError(f"unsupported processor: {processor}")

        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or f"{processor} exited with code {completed.returncode}"
            raise RuntimeError(message)

        discovered = self._discover_markdown_output(output_root, source_file.stem, target_md)
        if not discovered:
            raise RuntimeError(f"{processor} did not produce a markdown output")
        return discovered

    def _discover_markdown_output(self, output_root: Path, stem: str, preferred: Path) -> Optional[Path]:
        if preferred.exists():
            return preferred
        direct_match = output_root / f"{stem}.md"
        if direct_match.exists():
            return direct_match
        candidates = sorted(output_root.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    def _prepare_ascii_alias(self, source_file: Path, output_root: Path) -> Path:
        alias = output_root / f"input{source_file.suffix.lower()}"
        shutil.copy2(source_file, alias)
        return alias

    def _load_markdown(self, markdown_path: Path) -> str:
        content = markdown_path.read_text(encoding="utf-8", errors="replace")
        content = content.replace("\r\n", "\n")
        lines = [line.rstrip() for line in content.split("\n")]
        cleaned = "\n".join(lines).strip()
        return cleaned + "\n"

    def _assess_markdown_quality(self, content: str, suffix: str) -> QualityAssessment:
        stripped = content.strip()
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        char_count = len(stripped)
        word_char_count = len(re.findall(r"\w", stripped, flags=re.UNICODE))
        nontrivial_line_count = sum(1 for line in lines if len(re.sub(r"[\W_]+", "", line, flags=re.UNICODE)) >= 8)
        heading_count = sum(1 for line in lines if line.startswith("#"))
        metrics = {
            "char_count": char_count,
            "word_char_count": word_char_count,
            "line_count": len(lines),
            "nontrivial_line_count": nontrivial_line_count,
            "heading_count": heading_count,
        }

        if not stripped:
            return QualityAssessment(False, "markdown output is empty", metrics)
        if char_count < 80:
            return QualityAssessment(False, "markdown output is too short", metrics)
        if word_char_count < 50:
            return QualityAssessment(False, "markdown output has too little readable text", metrics)
        if nontrivial_line_count < 3:
            return QualityAssessment(False, "markdown output does not contain enough meaningful lines", metrics)

        if suffix == ".pdf" and heading_count == 0 and nontrivial_line_count < 5 and char_count < 300:
            return QualityAssessment(False, "pdf output looks too sparse for a reliable extraction", metrics)

        return QualityAssessment(True, "markdown quality is acceptable", metrics)

    def _format_source_path(self, path: object) -> str:
        """格式化 source_path 用于 frontmatter。处理 @root:path 格式。"""
        if isinstance(path, str) and path.startswith("@"):
            return path
        return self._to_vault_relative(Path(path))

    def _render_source_note(
        self,
        source_file: Path,
        relative_source: object,
        converted_markdown: Path,
        processor: str,
        content: str,
        layered_outputs: Optional[dict],
        title: Optional[str],
    ) -> str:
        source_title = title or source_file.stem
        today = date.today().isoformat()
        source_type = source_file.suffix.lower().lstrip(".")
        relative_work = self._to_vault_relative(converted_markdown)
        layered_outputs = layered_outputs or {}
        layered_paths = layered_outputs.get("paths", {})
        layered_stats = layered_outputs.get("stats", {})
        lookup_content = layered_outputs.get("lookup_content", "").strip()
        formatted_source = self._format_source_path(relative_source)
        frontmatter = [
            "---",
            f"title: {source_title}（提取稿）",
            "type: source_note",
            "domain: DocWork",
            f"source_type: {source_type}",
            f"source_path: \"{formatted_source}\"",
            f"ingest_processor: {processor}",
            "tags:",
            f"  - {source_type}",
            "  - source-note",
            "  - ingest",
            "status: active",
            f"updated: {today}",
            "---",
            "",
        ]
        body = [
            "# 资料说明",
            "",
            f"- 标题：{source_title}",
            f"- 原始文件：{formatted_source}",
            f"- 文件类型：{source_file.suffix.lower()}",
            f"- 转换处理器：{processor}",
            f"- 工作副本：{relative_work}",
            f"- 提取时间：{today}",
            "",
        ]

        if layered_paths:
            body = [
                "# 资料说明",
                "",
                f"- 标题：{source_title}",
                f"- 原始文件：{formatted_source}",
                f"- 文件类型：{source_file.suffix.lower()}",
                f"- 转换处理器：{processor}",
                f"- 工作副本：{relative_work}",
                f"- 提取时间：{today}",
                "",
                "# 分层输出",
                "",
            ]
            display_order = [
                ("preview_markdown", "原始抽取预览"),
                ("raw_workbook", "原始汇总表"),
                ("raw_csv_dir", "原始表格目录"),
                ("records_csv", "规范记录表（CSV）"),
                ("records_workbook", "规范记录表（XLSX）"),
                ("lookup_markdown", "检索索引"),
            ]
            for key, label in display_order:
                value = layered_paths.get(key)
                if value:
                    body.append(f"- {label}：{value}")
            if layered_stats.get("records_count"):
                body.append(f"- 可检索记录数：{layered_stats['records_count']}")
            if layered_stats.get("table_count"):
                body.append(f"- 识别表格总数：{layered_stats['table_count']}")
            body.extend(
                [
                    "",
                    "# 提取说明",
                    "",
                    "- 这是统一原始资料处理入口自动生成的提取稿初版。",
                    "- 对表格型 PDF，会同时保留原始抽取版、规范记录版和检索索引版，优先服务本地检索与后续清洗。",
                    "",
                ]
            )
            if lookup_content:
                body.extend(
                    [
                        "# 检索友好索引",
                        "",
                        lookup_content,
                        "",
                    ]
                )
            body.extend(
                [
                    "# 自动提取正文",
                    "",
                    content.strip(),
                    "",
                ]
            )
            return "\n".join(frontmatter + body)

        body = [
            "# 资料说明",
            "",
            f"- 标题：{source_title}",
            f"- 原始文件：{self._format_source_path(relative_source)}",
            f"- 文件类型：{source_file.suffix.lower()}",
            f"- 转换处理器：{processor}",
            f"- 工作副本：{relative_work}",
            f"- 提取时间：{today}",
            "",
            "# 提取说明",
            "",
            "- 这是统一原始资料处理入口自动生成的提取稿初版。",
            "- 当前目标是先得到可检索、可回溯的 Markdown 工作副本，再按需要继续人工清洗、补摘要或升级为 Knowledge 知识页。",
            "",
            "# 自动提取正文",
            "",
            content.strip(),
            "",
        ]
        return "\n".join(frontmatter + body)

    def _collect_layered_outputs(self, processor: str, converted_markdown: Path) -> Optional[dict]:
        if processor != "pdf_tables":
            return None
        base_dir = converted_markdown.parent
        stem = converted_markdown.stem
        manifest_path = base_dir / f"{stem}.manifest.json"
        lookup_path = base_dir / f"{stem}.lookup.md"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
        artifacts = manifest.get("artifacts", {}) if isinstance(manifest, dict) else {}
        resolved_paths: dict[str, str] = {}
        for key, value in artifacts.items():
            if not value:
                continue
            candidate = base_dir / value
            if candidate.exists():
                resolved_paths[key] = self._to_vault_relative(candidate)
        stats = {
            "records_count": manifest.get("records_count"),
            "table_count": manifest.get("table_count"),
        }
        lookup_content = ""
        if lookup_path.exists():
            try:
                lookup_content = lookup_path.read_text(encoding="utf-8").strip()
            except OSError:
                lookup_content = ""
        return {
            "paths": resolved_paths,
            "stats": stats,
            "lookup_content": lookup_content,
        }

    def _run_price_table_extraction(self, source_file: Path, work_root: Path) -> Optional[str]:
        """Run pdf_tables as parallel step for price-signal PDFs.

        Returns the vault-relative path to the copied records CSV in .library/prices/,
        or None if extraction failed or produced no records.
        """
        processors = self._all_processors()
        pdf_info = processors.get("pdf_tables")
        if not pdf_info or not pdf_info.available:
            return None
        attempt_root = work_root / "pdf_tables_price"
        if attempt_root.exists():
            shutil.rmtree(attempt_root)
        attempt_root.mkdir(parents=True, exist_ok=True)
        try:
            self._run_processor("pdf_tables", pdf_info.command_path, source_file, attempt_root)
        except RuntimeError:
            return None
        stem = source_file.stem
        manifest_path = attempt_root / f"{stem}.manifest.json"
        records_csv = None
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                artifacts = manifest.get("artifacts", {})
                records_rel = artifacts.get("records_csv")
                if records_rel:
                    candidate = attempt_root / records_rel
                    if candidate.exists():
                        records_csv = candidate
            except (OSError, json.JSONDecodeError):
                pass
        if not records_csv:
            csv_files = sorted(attempt_root.rglob("*.csv"), key=lambda p: p.stat().st_size, reverse=True)
            for csv_file in csv_files:
                if csv_file.stem.endswith(".records"):
                    records_csv = csv_file
                    break
            if not records_csv and csv_files:
                records_csv = csv_files[0]
        if not records_csv:
            return None
        PRICES_DIR.mkdir(parents=True, exist_ok=True)
        dest = PRICES_DIR / f"{stem}.csv"
        shutil.copy2(records_csv, dest)
        return self._to_vault_relative(dest)

    def _resolve_input_path(self, source_path: str) -> Path:
        raw = Path(source_path)
        if raw.is_absolute():
            resolved = raw.resolve()
            try:
                return resolved.relative_to(self.vault_root)
            except ValueError as exc:
                raise ValueError("absolute source_path must be inside the vault root") from exc
        normalized = (self.vault_root / raw).resolve()
        try:
            return normalized.relative_to(self.vault_root)
        except ValueError as exc:
            raise ValueError("source_path must stay inside the vault root") from exc

    def _work_root_for_source(self, relative_source: Path) -> Path:
        slug = "__".join(relative_source.with_suffix("").parts)
        return self.temp_root / slug

    def _to_vault_relative(self, path: Path) -> str:
        absolute = path if path.is_absolute() else self.vault_root / path
        return absolute.resolve().relative_to(self.vault_root).as_posix()

    def _processor_to_dict(self, info: ProcessorInfo) -> dict:
        return {
            "name": info.name,
            "available": info.available,
            "command_path": str(info.command_path) if info.command_path else None,
        }
