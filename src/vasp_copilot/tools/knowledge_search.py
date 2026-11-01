"""Expose curated reference search through the existing tool contract."""

from ..agent.tool_registry import ToolRegistry
from ..rag.retriever import KnowledgeRetriever, KnowledgeSearchResult, SearchKnowledgeArgs


def register_knowledge_tool(registry: ToolRegistry) -> None:
    @registry.register(
        "search_knowledge",
        "Search local VASP reference notes by keywords. Returns sources and passages, not evidence about the current run. No network access.",
        SearchKnowledgeArgs, KnowledgeSearchResult,
    )
    def search(args: SearchKnowledgeArgs) -> KnowledgeSearchResult:
        return KnowledgeRetriever().search(args.query, args.top_k)
