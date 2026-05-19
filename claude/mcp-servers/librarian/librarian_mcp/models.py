from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from librarian_mcp.config import MAX_SEARCH_LIMIT, MIN_SEARCH_LIMIT


class DocumentType(str, Enum):
    SUMMARY = "summary"
    EXCERPT = "excerpt"
    SOURCE_NOTE = "source_note"
    SESSION_NOTE = "session_note"
    REPORT = "report"
    SKILL_DRAFT = "skill_draft"
    AGENT_SKILL = "agent_skill"
    MEMORY = "memory"


class CitationKind(str, Enum):
    LOCAL_SUMMARY = "local_summary"
    LOCAL_SOURCE = "local_source"
    HISTORY_RECALL = "history_recall"
    AGENT_SKILL = "agent_skill"
    MODEL_KNOWLEDGE = "model_knowledge"
    WEB_SOURCE = "web_source"


class MemoryTarget(str, Enum):
    MEMORY = "memory"
    USER = "user"


class MemoryAction(str, Enum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class SkillStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ProcessorName(str, Enum):
    AUTO = "auto"
    PDF_TABLES = "pdf_tables"
    MARKITDOWN = "markitdown"
    DOCLING = "docling"
    MARKER = "marker"
    PANDOC = "pandoc"


class BaseInputModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class SearchSummariesInput(BaseInputModel):
    query: str = Field(..., min_length=1, description="全文检索查询词")
    type: list[DocumentType] = Field(default_factory=list, description="文档类型过滤")
    path_prefix: list[str] = Field(default_factory=list, description="相对 vault 路径前缀")
    limit: int = Field(default=5, ge=MIN_SEARCH_LIMIT, le=MAX_SEARCH_LIMIT, description="返回条数")

    @field_validator("path_prefix")
    @classmethod
    def validate_path_prefix(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            item = value.replace("\\", "/").strip()
            if item.startswith("/") or ":" in item:
                raise ValueError("path_prefix 必须是相对 vault 根目录的路径")
            normalized.append(item)
        return normalized


class PriceQueryBaseInput(BaseInputModel):
    path_prefix: list[str] = Field(default_factory=list, description="相对 vault 根目录的来源路径前缀")
    limit: int = Field(default=5, ge=MIN_SEARCH_LIMIT, le=MAX_SEARCH_LIMIT, description="返回条数")

    @field_validator("path_prefix")
    @classmethod
    def validate_price_path_prefix(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            item = value.replace("\\", "/").strip()
            if item.startswith("/") or ":" in item:
                raise ValueError("path_prefix 必须是相对 vault 根目录的路径")
            normalized.append(item)
        return normalized


class QueryMaterialPriceInput(PriceQueryBaseInput):
    material_name: str = Field(..., min_length=1, description="材料名称或规格关键词")


class SearchPriceCandidatesInput(PriceQueryBaseInput):
    query: str = Field(..., min_length=1, description="价格检索词，可包含材料名、价格、单位、备注")


class ListPriceSourcesInput(PriceQueryBaseInput):
    material_name: Optional[str] = Field(default=None, description="可选材料名称过滤")


class OpenNoteInput(BaseInputModel):
    vault_path: str = Field(..., min_length=1, description="相对 vault 根目录的 Markdown 路径")

    @field_validator("vault_path")
    @classmethod
    def validate_vault_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or ":" in normalized:
            raise ValueError("vault_path 必须是相对 vault 根目录的路径")
        return normalized


class LocateSourceInput(OpenNoteInput):
    pass


class OpenSessionInput(BaseInputModel):
    session_id: str = Field(..., min_length=1, description="会话 ID")


class GetExcerptInput(OpenNoteInput):
    heading: Optional[str] = Field(default=None, description="标题名")
    chunk_order: Optional[int] = Field(default=None, ge=1, description="分块序号")

    @model_validator(mode="after")
    def validate_selector(self) -> "GetExcerptInput":
        if bool(self.heading) == bool(self.chunk_order):
            raise ValueError("heading 和 chunk_order 必须二选一")
        return self


class CitationModel(BaseInputModel):
    kind: CitationKind
    title: Optional[str] = None
    vault_path: Optional[str] = None
    heading: Optional[str] = None
    chunk_order: Optional[int] = Field(default=None, ge=1)
    quote: Optional[str] = None
    source_path: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None

    @field_validator("vault_path", "source_path")
    @classmethod
    def normalize_optional_paths(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or ":" in normalized:
            raise ValueError("路径字段必须是相对路径")
        return normalized


class SaveSessionNoteInput(BaseInputModel):
    question: str = Field(..., min_length=1)
    conclusion: str = Field(..., min_length=1)
    key_points: list[str] = Field(default_factory=list)
    citations: list[CitationModel] = Field(default_factory=list)
    model_judgement: Optional[str] = None
    external_sources: list[CitationModel] = Field(default_factory=list)
    todo: list[str] = Field(default_factory=list)
    auto_grow: bool = Field(default=False, description="是否在保存归档后触发成长反思（仅建议或可选执行）")
    apply_memory: bool = Field(default=False, description="auto_grow 时是否实际写入热记忆")
    apply_skill_draft: bool = Field(default=False, description="auto_grow 时是否实际生成技能草稿")

    @field_validator("external_sources")
    @classmethod
    def validate_external_sources(cls, value: list[CitationModel]) -> list[CitationModel]:
        for item in value:
            if item.kind != CitationKind.WEB_SOURCE:
                raise ValueError("external_sources 只能包含 web_source")
        return value


class SearchSessionsInput(BaseInputModel):
    query: str = Field(..., min_length=1, description="历史会话检索词")
    limit: int = Field(default=5, ge=MIN_SEARCH_LIMIT, le=MAX_SEARCH_LIMIT, description="返回条数")


class GrowSessionInput(BaseInputModel):
    session_id: str = Field(..., min_length=1, description="会话 ID")
    apply_memory: bool = Field(default=False, description="是否实际写入热记忆")
    apply_skill_draft: bool = Field(default=False, description="是否实际生成技能草稿")


class MemoryWriteInput(BaseInputModel):
    action: MemoryAction
    target: MemoryTarget
    content: Optional[str] = Field(default=None, description="新增内容或替换后的内容")
    match: Optional[str] = Field(default=None, description="replace/remove 时用于定位旧条目")
    source_session_id: Optional[str] = Field(default=None, description="来源会话 ID")

    @model_validator(mode="after")
    def validate_memory_action(self) -> "MemoryWriteInput":
        if self.action == MemoryAction.ADD and not self.content:
            raise ValueError("add 必须提供 content")
        if self.action == MemoryAction.REPLACE and (not self.content or not self.match):
            raise ValueError("replace 必须同时提供 content 和 match")
        if self.action == MemoryAction.REMOVE and not self.match:
            raise ValueError("remove 必须提供 match")
        return self


class MemoryListInput(BaseInputModel):
    target: Optional[MemoryTarget] = Field(default=None, description="可选目标 memory/user")


class ListSkillsInput(BaseInputModel):
    query: Optional[str] = Field(default=None, description="可选技能检索词")
    status: list[SkillStatus] = Field(default_factory=list, description="技能状态过滤")
    limit: int = Field(default=10, ge=MIN_SEARCH_LIMIT, le=MAX_SEARCH_LIMIT, description="返回条数")


class RebuildSkillIndexInput(BaseInputModel):
    include_drafts: bool = Field(default=True, description="是否包含草稿技能")


class SaveSkillDraftInput(BaseInputModel):
    name: str = Field(..., min_length=1, description="技能名称")
    summary: str = Field(..., min_length=1, description="技能摘要")
    keywords: list[str] = Field(default_factory=list, description="触发关键词")
    applicable_when: list[str] = Field(default_factory=list, description="适用场景")
    preconditions: list[str] = Field(default_factory=list, description="前置条件")
    inputs: list[str] = Field(default_factory=list, description="输入")
    outputs: list[str] = Field(default_factory=list, description="输出")
    steps: list[str] = Field(default_factory=list, description="标准步骤")
    checkpoints: list[str] = Field(default_factory=list, description="检查点")
    failure_modes: list[str] = Field(default_factory=list, description="常见失败")
    source_session_id: Optional[str] = Field(default=None, description="来源会话 ID")

    @field_validator(
        "keywords",
        "applicable_when",
        "preconditions",
        "inputs",
        "outputs",
        "steps",
        "checkpoints",
        "failure_modes",
    )
    @classmethod
    def normalize_string_list(cls, values: list[str]) -> list[str]:
        return [item.strip() for item in values if item and item.strip()]


class PromoteSkillInput(BaseInputModel):
    draft_vault_path: str = Field(..., min_length=1, description="技能草稿路径")
    target_name: Optional[str] = Field(default=None, description="正式技能名称，可覆盖草稿名")
    change_summary: str = Field(..., min_length=1, description="本次晋升或更新摘要")

    @field_validator("draft_vault_path")
    @classmethod
    def validate_draft_vault_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or ":" in normalized:
            raise ValueError("draft_vault_path 必须是相对 vault 根目录的路径")
        return normalized


class IngestSourceInput(BaseInputModel):
    source_path: str = Field(..., min_length=1, description="原始资料路径（相对 vault；external_root 时相对外部根）")
    processor: ProcessorName = Field(default=ProcessorName.AUTO, description="处理器选择")
    title: Optional[str] = Field(default=None, description="可选标题覆盖")
    force: bool = Field(default=False, description="是否覆盖已有 source_note")
    reindex: bool = Field(default=False, description="生成后是否立即重建索引")
    index_only: bool = Field(default=False, description="仅索引，不在源文件旁创建 .source_note.md")
    external_root: Optional[str] = Field(default=None, description="外部根路径简称（如 onedrive），启用后 source_path 相对该根")

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or (":" in normalized and not normalized.startswith("@") and len(normalized) > 2 and normalized[1] != ":"):
            raise ValueError("source_path 必须是相对路径或 @root:path 格式")
        return normalized

    @field_validator("external_root")
    @classmethod
    def validate_external_root(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        from librarian_mcp.config import EXTERNAL_ROOTS
        if value not in EXTERNAL_ROOTS:
            raise ValueError(f"external_root 必须是 {list(EXTERNAL_ROOTS.keys())} 之一")
        return value


class IngestInboxInput(BaseInputModel):
    path_prefix: list[str] = Field(
        default_factory=lambda: ["DocWork"],
        description="相对 vault 根目录的扫描路径前缀",
    )
    force: bool = Field(default=False, description="强制重新处理所有文件（即使未修改）")
    dry_run: bool = Field(default=False, description="仅扫描报告，不实际处理")
    reindex: bool = Field(default=False, description="处理完成后重建索引")

    @field_validator("path_prefix")
    @classmethod
    def validate_path_prefix(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            item = value.replace("\\", "/").strip()
            if item.startswith("/") or ":" in item:
                raise ValueError("path_prefix 必须是相对 vault 根目录的路径")
            normalized.append(item)
        return normalized


class VecSearchInput(BaseModel):
    """向量语义搜索的输入模型"""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="搜索查询文本（将被转换为嵌入向量）")
    limit: int = Field(default=10, ge=MIN_SEARCH_LIMIT, le=MAX_SEARCH_LIMIT)
    path_prefix: Optional[list[str]] = Field(
        default=None, description="限制搜索的路径前缀列表（可选）"
    )
    target: str = Field(
        default="passages",
        description="搜索目标: 'passages' 或 'memories'",
    )


class HybSearchInput(BaseModel):
    """混合搜索（FTS5 关键词 + 向量语义）的输入模型"""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="搜索查询文本")
    limit: int = Field(default=10, ge=MIN_SEARCH_LIMIT, le=MAX_SEARCH_LIMIT)
    path_prefix: Optional[list[str]] = Field(
        default=None, description="限制搜索的路径前缀列表（可选）"
    )
    fts_weight: float = Field(
        default=0.4, ge=0.0, le=1.0,
        description="FTS5 关键词权重（0.0-1.0），剩余为向量语义权重",
    )
