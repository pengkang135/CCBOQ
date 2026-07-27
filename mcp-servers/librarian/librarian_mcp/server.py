from __future__ import annotations

from typing import Optional

from librarian_mcp.ingest import SourceIngestService
from librarian_mcp.models import (
    GetExcerptInput,
    GrowSessionInput,
    IngestSourceInput,
    IngestInboxInput,
    ListPriceSourcesInput,
    ListSkillsInput,
    LocateSourceInput,
    MemoryListInput,
    MemoryWriteInput,
    OpenNoteInput,
    OpenSessionInput,
    PromoteSkillInput,
    QueryMaterialPriceInput,
    RebuildSkillIndexInput,
    SaveSessionNoteInput,
    SaveSkillDraftInput,
    SearchSessionsInput,
    SearchPriceCandidatesInput,
    SearchSummariesInput,
    VecSearchInput,
    HybSearchInput,
)
from librarian_mcp.ingest_queue import queue_ingest, ingest_status, list_queue, start_worker, stop_worker
from librarian_mcp.service import LibrarianService

try:
    from librarian_mcp import vector_index as vecidx
    _HAS_VEC = True
except ImportError:
    _HAS_VEC = False

_HAS_EMBED = False

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None


service = LibrarianService()
ingest_service = SourceIngestService()

if FastMCP is not None:
    mcp = FastMCP("librarian_mcp")

    @mcp.tool(
        name="inspect_processors",
        annotations={
            "title": "查看资料处理器可用性",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def inspect_processors() -> dict:
        return ingest_service.inspect_processors()

    @mcp.tool(
        name="search_summaries",
        annotations={
            "title": "搜索本地摘要",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def search_summaries(
        query: str,
        type: Optional[list[str]] = None,
        path_prefix: Optional[list[str]] = None,
        limit: int = 5,
    ) -> dict:
        service._auto_refresh_if_needed()
        params = SearchSummariesInput(
            query=query,
            type=type or [],
            path_prefix=path_prefix or [],
            limit=limit,
        )
        return service.search_summaries(
            query=params.query,
            types=[item.value for item in params.type],
            path_prefixes=params.path_prefix,
            limit=params.limit,
        )

    @mcp.tool(
        name="query_material_price",
        annotations={
            "title": "查询材料价格",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def query_material_price(
        material_name: str,
        path_prefix: Optional[list[str]] = None,
        limit: int = 5,
    ) -> dict:
        service._auto_refresh_if_needed()
        params = QueryMaterialPriceInput(
            material_name=material_name,
            path_prefix=path_prefix or [],
            limit=limit,
        )
        return service.query_material_price(
            material_name=params.material_name,
            path_prefixes=params.path_prefix,
            limit=params.limit,
        )

    @mcp.tool(
        name="search_price_candidates",
        annotations={
            "title": "模糊搜索价格候选",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def search_price_candidates(
        query: str,
        path_prefix: Optional[list[str]] = None,
        limit: int = 5,
    ) -> dict:
        service._auto_refresh_if_needed()
        params = SearchPriceCandidatesInput(
            query=query,
            path_prefix=path_prefix or [],
            limit=limit,
        )
        return service.search_price_candidates(
            query=params.query,
            path_prefixes=params.path_prefix,
            limit=params.limit,
        )

    @mcp.tool(
        name="list_price_sources",
        annotations={
            "title": "列出价格来源文档",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def list_price_sources(
        material_name: Optional[str] = None,
        path_prefix: Optional[list[str]] = None,
        limit: int = 10,
    ) -> dict:
        service._auto_refresh_if_needed()
        params = ListPriceSourcesInput(
            material_name=material_name,
            path_prefix=path_prefix or [],
            limit=limit,
        )
        return service.list_price_sources(
            material_name=params.material_name,
            path_prefixes=params.path_prefix,
            limit=params.limit,
        )

    @mcp.tool(
        name="open_note",
        annotations={
            "title": "打开笔记全文",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def open_note(vault_path: str) -> dict:
        params = OpenNoteInput(vault_path=vault_path)
        return service.open_note(params.vault_path)

    @mcp.tool(
        name="locate_source",
        annotations={
            "title": "定位来源文件",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def locate_source(vault_path: str) -> dict:
        params = LocateSourceInput(vault_path=vault_path)
        return service.locate_source(params.vault_path)

    @mcp.tool(
        name="search_sessions",
        annotations={
            "title": "搜索历史会话",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def search_sessions(query: str, limit: int = 5) -> dict:
        service._auto_refresh_if_needed()
        params = SearchSessionsInput(query=query, limit=limit)
        return service.search_sessions(query=params.query, limit=params.limit)

    @mcp.tool(
        name="open_session",
        annotations={
            "title": "打开历史会话",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def open_session(session_id: str) -> dict:
        params = OpenSessionInput(session_id=session_id)
        return service.open_session(params.session_id)

    @mcp.tool(
        name="grow_session",
        annotations={
            "title": "会话后成长反思",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def grow_session(session_id: str, apply_memory: bool = False, apply_skill_draft: bool = False) -> dict:
        params = GrowSessionInput(session_id=session_id, apply_memory=apply_memory, apply_skill_draft=apply_skill_draft)
        return service.grow_session(
            session_id=params.session_id,
            apply_memory=params.apply_memory,
            apply_skill_draft=params.apply_skill_draft,
        )

    @mcp.tool(
        name="memory_write",
        annotations={
            "title": "写入长期记忆",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def memory_write(
        action: str,
        target: str,
        content: Optional[str] = None,
        match: Optional[str] = None,
        source_session_id: Optional[str] = None,
    ) -> dict:
        params = MemoryWriteInput(
            action=action,
            target=target,
            content=content,
            match=match,
            source_session_id=source_session_id,
        )
        return service.memory_write(
            action=params.action.value,
            target=params.target.value,
            content=params.content,
            match=params.match,
            source_session_id=params.source_session_id,
        )

    @mcp.tool(
        name="memory_list",
        annotations={
            "title": "查看长期记忆",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def memory_list(target: Optional[str] = None) -> dict:
        params = MemoryListInput(target=target)
        return service.memory_list(target=params.target.value if params.target else None)

    @mcp.tool(
        name="get_excerpt",
        annotations={
            "title": "读取局部片段",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_excerpt(
        vault_path: str,
        heading: Optional[str] = None,
        chunk_order: Optional[int] = None,
    ) -> dict:
        params = GetExcerptInput(
            vault_path=vault_path,
            heading=heading,
            chunk_order=chunk_order,
        )
        return service.get_excerpt(
            vault_path=params.vault_path,
            heading=params.heading,
            chunk_order=params.chunk_order,
        )

    @mcp.tool(
        name="list_skills",
        annotations={
            "title": "查看技能索引",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def list_skills(
        query: Optional[str] = None,
        status: Optional[list[str]] = None,
        limit: int = 10,
    ) -> dict:
        params = ListSkillsInput(
            query=query,
            status=status or [],
            limit=limit,
        )
        return service.list_skills(
            query=params.query,
            statuses=[item.value for item in params.status],
            limit=params.limit,
        )

    @mcp.tool(
        name="open_skill",
        annotations={
            "title": "打开技能正文",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def open_skill(vault_path: str) -> dict:
        params = OpenNoteInput(vault_path=vault_path)
        return service.open_skill(params.vault_path)

    @mcp.tool(
        name="save_skill_draft",
        annotations={
            "title": "保存技能草稿",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def save_skill_draft(
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
        params = SaveSkillDraftInput(
            name=name,
            summary=summary,
            keywords=keywords or [],
            applicable_when=applicable_when or [],
            preconditions=preconditions or [],
            inputs=inputs or [],
            outputs=outputs or [],
            steps=steps or [],
            checkpoints=checkpoints or [],
            failure_modes=failure_modes or [],
            source_session_id=source_session_id,
        )
        return service.save_skill_draft(
            name=params.name,
            summary=params.summary,
            keywords=params.keywords,
            applicable_when=params.applicable_when,
            preconditions=params.preconditions,
            inputs=params.inputs,
            outputs=params.outputs,
            steps=params.steps,
            checkpoints=params.checkpoints,
            failure_modes=params.failure_modes,
            source_session_id=params.source_session_id,
        )

    @mcp.tool(
        name="promote_skill",
        annotations={
            "title": "晋升正式技能",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def promote_skill(
        draft_vault_path: str,
        target_name: Optional[str] = None,
        change_summary: str = "",
    ) -> dict:
        params = PromoteSkillInput(
            draft_vault_path=draft_vault_path,
            target_name=target_name,
            change_summary=change_summary,
        )
        return service.promote_skill(
            draft_vault_path=params.draft_vault_path,
            target_name=params.target_name,
            change_summary=params.change_summary,
        )

    @mcp.tool(
        name="rebuild_skill_index",
        annotations={
            "title": "重建技能索引",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def rebuild_skill_index(include_drafts: bool = True) -> dict:
        params = RebuildSkillIndexInput(include_drafts=include_drafts)
        return service.rebuild_skill_index(include_drafts=params.include_drafts)

    @mcp.tool(
        name="save_session_note",
        annotations={
            "title": "保存问答归档",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def save_session_note(
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
        params = SaveSessionNoteInput(
            question=question,
            conclusion=conclusion,
            key_points=key_points or [],
            citations=citations or [],
            model_judgement=model_judgement,
            external_sources=external_sources or [],
            todo=todo or [],
            auto_grow=auto_grow,
            apply_memory=apply_memory,
            apply_skill_draft=apply_skill_draft,
        )
        return service.save_session_note(
            question=params.question,
            conclusion=params.conclusion,
            key_points=params.key_points,
            citations=[item.model_dump() for item in params.citations],
            model_judgement=params.model_judgement,
            external_sources=[item.model_dump() for item in params.external_sources],
            todo=params.todo,
            auto_grow=params.auto_grow,
            apply_memory=params.apply_memory,
            apply_skill_draft=params.apply_skill_draft,
        )

    @mcp.tool(
        name="ingest_source",
        annotations={
            "title": "导入原始资料并生成提取稿",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def ingest_source(
        source_path: str,
        processor: str = "auto",
        title: Optional[str] = None,
        force: bool = False,
        reindex: bool = False,
        index_only: bool = False,
        external_root: Optional[str] = None,
    ) -> dict:
        params = IngestSourceInput(
            source_path=source_path,
            processor=processor,
            title=title,
            force=force,
            reindex=reindex,
            index_only=index_only,
            external_root=external_root,
        )
        return ingest_service.ingest_source(
            source_path=params.source_path,
            processor=params.processor.value,
            title=params.title,
            force=params.force,
            reindex=params.reindex,
            index_only=params.index_only,
            external_root=params.external_root,
        )

    @mcp.tool(
        name="ingest_inbox",
        annotations={
            "title": "批量增量导入 DocWork 新资料",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def ingest_inbox(
        path_prefix: Optional[list[str]] = None,
        force: bool = False,
        dry_run: bool = False,
        reindex: bool = False,
    ) -> dict:
        params = IngestInboxInput(
            path_prefix=path_prefix or ["DocWork"],
            force=force,
            dry_run=dry_run,
            reindex=reindex,
        )
        return ingest_service.ingest_inbox(
            path_prefixes=params.path_prefix,
            force=params.force,
            dry_run=params.dry_run,
            reindex=params.reindex,
        )

    @mcp.tool(
        name="queue_ingest",
        annotations={
            "title": "将摄入任务放入后台队列（立即返回 task_id）",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def queue_ingest(
        source_path: str,
        processor: str = "auto",
        title: Optional[str] = None,
        force: bool = False,
        external_root: Optional[str] = None,
    ) -> dict:
        return queue_ingest(
            source_path=source_path,
            processor=processor,
            title=title,
            force=force,
            external_root=external_root,
        )

    @mcp.tool(
        name="ingest_status",
        annotations={
            "title": "查询摄入任务状态",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def ingest_status(task_id: str) -> dict:
        return ingest_status(task_id=task_id)

    @mcp.tool(
        name="list_ingest_queue",
        annotations={
            "title": "列出摄入队列中的任务",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def list_ingest_queue(
        status: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        return list_queue(status=status, limit=limit)

    @mcp.tool(
        name="check_stale",
        annotations={
            "title": "检测过期摘要（源文件已更新但 source_note 未刷新）",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def check_stale(
        path_prefix: Optional[list[str]] = None,
    ) -> dict:
        return service.check_stale(prefixes=path_prefix)

    @mcp.tool(
        name="recalc_decay",
        annotations={
            "title": "重新计算时间衰减分数",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def recalc_decay(
        target: str = "all",
        lambda_decay: float = 0.01,
        alpha_access: float = 0.3,
    ) -> dict:
        return service.recalc_decay(
            target=target,
            lambda_decay=lambda_decay,
            alpha_access=alpha_access,
        )

    @mcp.tool(
        name="decay_cleanup",
        annotations={
            "title": "清理低衰减分数条目",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def decay_cleanup(
        target: str = "all",
        threshold: float = 0.05,
        dry_run: bool = True,
    ) -> dict:
        return service.decay_cleanup(
            target=target,
            threshold=threshold,
            dry_run=dry_run,
        )

    @mcp.tool(
        name="suggest_memories",
        annotations={
            "title": "从会话中提取记忆建议，含去重检查",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def suggest_memories(
        session_id: str,
        include_conflicts: bool = False,
    ) -> dict:
        return service.suggest_memories(
            session_id=session_id,
            include_conflicts=include_conflicts,
        )

    @mcp.tool(
        name="analyze_session",
        annotations={
            "title": "深度分析会话，提取模式/成功策略/错误教训/改进建议",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def analyze_session(
        session_id: str,
    ) -> dict:
        return service.analyze_session(session_id=session_id)

    @mcp.tool(
        name="register_vault",
        annotations={
            "title": "注册新知识库 vault",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def register_vault(
        path: str,
        name: str,
        description: str = "",
        types: Optional[list[str]] = None,
    ) -> dict:
        return service.register_vault(
            path=path,
            name=name,
            description=description,
            types=types or ["knowledge"],
        )

    @mcp.tool(
        name="list_vaults",
        annotations={
            "title": "列出已注册的知识库 vault",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def list_vaults() -> dict:
        return service.list_vaults()

    if _HAS_VEC:

        try:
            from librarian_mcp import embedding
            _HAS_EMBED = True
        except ImportError:
            _HAS_EMBED = False

        def _vec_db():
            import sqlite3
            conn = sqlite3.connect(service.db_path)
            vecidx.ensure_vec_tables(conn)
            return conn

        @mcp.tool(
            name="vec_search",
            annotations={
                "title": "向量语义搜索（bge-large-zh）",
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def vec_search(
            query: str,
            limit: int = 10,
            path_prefix: Optional[list[str]] = None,
            target: str = "passages",
        ) -> dict:
            service._auto_refresh_if_needed()
            if not _HAS_EMBED:
                return {"error": "embedding model not available"}
            params = VecSearchInput(
                query=query, limit=limit,
                path_prefix=path_prefix, target=target,
            )
            emb = embedding.encode(params.query)
            db = _vec_db()
            try:
                if params.target == "memories":
                    results = vecidx.search_similar_memories(db, embedding=emb, k=params.limit)
                    return {"query": query, "target": "memories", "count": len(results), "results": results}
                results = vecidx.search_similar_passages_filtered(
                    db, embedding=emb, k=params.limit, path_prefix=params.path_prefix,
                )
                return {"query": query, "target": "passages", "count": len(results), "results": results}
            finally:
                db.close()

        @mcp.tool(
            name="vec_reindex",
            annotations={
                "title": "重建向量索引（bge-large-zh 嵌入）",
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": False,
            },
        )
        async def vec_reindex(
            target: str = "passages",
            batch_size: int = 32,
        ) -> dict:
            if not _HAS_EMBED:
                return {"error": "embedding model not available"}
            db = _vec_db()
            try:
                if target == "memories":
                    result = vecidx.reindex_all_memories(db, embedding.encode)
                else:
                    result = vecidx.reindex_all_passages(db, embedding.encode)
                db.commit()
                stats = vecidx.get_vec_stats(db)
                result["stats"] = stats
                return result
            finally:
                db.close()

        @mcp.tool(
            name="vec_stats",
            annotations={
                "title": "查看向量索引统计",
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )
        async def vec_stats() -> dict:
            db = _vec_db()
            try:
                return vecidx.get_vec_stats(db)
            finally:
                db.close()

        @mcp.tool(
            name="hyb_search",
            annotations={
                "title": "混合搜索（FTS5 关键词 + bge-large-zh 语义）",
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def hyb_search(
            query: str,
            limit: int = 10,
            path_prefix: Optional[list[str]] = None,
            fts_weight: float = 0.4,
        ) -> dict:
            service._auto_refresh_if_needed()
            if not _HAS_EMBED:
                return {"error": "embedding model not available"}
            params = HybSearchInput(
                query=query, limit=limit,
                path_prefix=path_prefix, fts_weight=fts_weight,
            )
            emb = embedding.encode(params.query) if _HAS_EMBED else None
            db = _vec_db()
            try:
                results = vecidx.hybrid_search(
                    db, query_text=params.query, embedding=emb,
                    k=params.limit, path_prefix=params.path_prefix,
                    fts_weight=params.fts_weight,
                    vec_weight=1.0 - params.fts_weight,
                )
                return {
                    "query": query, "fts_weight": fts_weight,
                    "vec_weight": 1.0 - fts_weight,
                    "count": len(results), "results": results,
                }
            finally:
                db.close()
else:
    mcp = None


def main() -> None:
    if mcp is None:
        raise RuntimeError("mcp package is not installed. Install librarian_mcp/requirements.txt first.")
    service.initialize()
    if _HAS_EMBED:
        from librarian_mcp import embedding
        embedding.preload()
    if _HAS_VEC:
        from librarian_mcp import vector_index as _vi
    start_worker()
    try:
        mcp.run()
    finally:
        stop_worker()


if __name__ == "__main__":
    main()
