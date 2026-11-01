"""Search short, curated Markdown notes by explicit bilingual keywords."""

import re
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from ..schemas import Schema

MAX_DOCUMENT_BYTES = 16 * 1024
MAX_DOCUMENTS = 32
MAX_EXCERPT_CHARS = 4000


class SearchKnowledgeArgs(Schema):
    query: str = Field(min_length=1, max_length=500, description="VASP terms or a short Chinese/English question")
    top_k: int = Field(default=3, ge=1, le=5, description="Maximum number of reference passages")

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query must not be blank")
        return value.strip()


class ReferenceSection(Schema):
    kind: Literal["official_summary", "project_policy", "unclassified"]
    text: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    citation: str
    source_url: str | None = None

    @model_validator(mode="after")
    def check_attribution(self) -> "ReferenceSection":
        if self.line_end < self.line_start:
            raise ValueError("Reference section has reversed line numbers")
        if (self.kind == "official_summary") != (self.source_url is not None):
            raise ValueError("Only official summaries carry the external source URL")
        return self


class KnowledgeHit(Schema):
    evidence_type: Literal["reference"] = "reference"
    document: str
    title: str
    source: str
    reviewed_on: str
    excerpt: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    score: int = Field(ge=1)
    matched_keywords: list[str]
    # Old saved hits have only excerpt/source; never rebuild them from today's corpus.
    sections: list[ReferenceSection] = Field(default_factory=list)


class KnowledgeSearchResult(Schema):
    query: str
    hits: list[KnowledgeHit]
    notice: str = (
        "本地知识库不是本次计算的文件证据；没有命中不表示计算异常。"
        "excerpt 中的“官方资料摘要”是本项目对 source 的转述，不是官方原文引语；"
        "“本项目使用限制”来自 VASP-Copilot，不能归因于 source 对应的官方资料。"
        "新结果的 sections 按段标明归属：官网链接仅支持 official_summary；"
        "project_policy 应引用其 citation（项目笔记与行号），不要写“同上官网来源”。"
    )


def keyword_matches(keyword: str, query: str) -> bool:
    """Keep ASCII parameter boundaries: EDIFF must not match EDIFFG."""
    keyword, query = keyword.casefold(), query.casefold()
    if keyword.isascii():
        return re.search(r"(?<![a-z0-9_])" + re.escape(keyword) + r"(?![a-z0-9_])", query) is not None
    return keyword in query


def reference_sections(body: list[str], document: str, source: str) -> list[ReferenceSection]:
    """Attribute explicit paragraph labels, preserving exact local source lines."""
    sections = []
    paragraph = []
    start = 6
    for number, line in enumerate([*body, ""], start=6):
        if line.strip():
            if not paragraph:
                start = number
            paragraph.append(line)
            continue
        if not paragraph:
            continue
        text = "\n".join(paragraph)
        kind = ("official_summary" if paragraph[0].startswith("官方资料摘要：") else
                "project_policy" if paragraph[0].startswith("本项目使用限制：") else "unclassified")
        location = f"{document}:{start}-{number - 1}"
        citation = (f"{location}（官方资料摘要，项目转述）" if kind == "official_summary" else
                    f"VASP-Copilot {location}" if kind == "project_policy" else
                    f"{location}（归属未分类）")
        sections.append(ReferenceSection(
            kind=kind, text=text, line_start=start, line_end=number - 1, citation=citation,
            source_url=source if kind == "official_summary" else None,
        ))
        paragraph = []
    return sections


class KnowledgeRetriever:
    def __init__(self, root: Path | None = None):
        # root is a developer/test injection point, never a tool argument.
        self.root = root if root is not None else files("vasp_copilot.rag").joinpath("knowledge")

    def search(self, query: str, top_k: int = 3) -> KnowledgeSearchResult:
        args = SearchKnowledgeArgs(query=query, top_k=top_k)
        documents = []
        for document in self.root.iterdir():
            if document.name.endswith(".md") and document.is_file():
                documents.append(document)
                if len(documents) > MAX_DOCUMENTS:
                    raise ValueError("Too many knowledge documents")
        hits = []
        for document in sorted(documents, key=lambda item: item.name):
            with document.open("rb") as handle:
                raw = handle.read(MAX_DOCUMENT_BYTES + 1)
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise ValueError("Knowledge document exceeds size limit")
            lines = raw.decode("utf-8-sig").splitlines()
            # Small notes use a deliberately simple four-line metadata format.
            if (len(lines) < 6 or not lines[0].startswith("# ") or
                    not lines[1].startswith("Source: ") or not lines[2].startswith("Keywords: ") or
                    not lines[3].startswith("Reviewed: ") or lines[4].strip()):
                raise ValueError("Invalid knowledge metadata")
            title = lines[0][2:].strip()
            source = lines[1][8:].strip()
            keywords = list(dict.fromkeys(word.strip().casefold() for word in lines[2][10:].split(",") if word.strip()))
            reviewed = lines[3][10:].strip()
            date.fromisoformat(reviewed)
            url = urlsplit(source)
            if not title or not keywords or url.scheme != "https" or not url.netloc or url.username or url.password:
                raise ValueError("Knowledge title, keywords and HTTPS source are required")
            body = lines[5:]
            while body and not body[-1].strip():
                body.pop()
            excerpt = "\n".join(body)
            if not excerpt.strip() or len(excerpt) > MAX_EXCERPT_CHARS:
                raise ValueError("Knowledge passage is empty or too long")
            matched = [word for word in keywords if keyword_matches(word, args.query)]
            if matched:
                hits.append(KnowledgeHit(
                    document=document.name, title=title, source=source, reviewed_on=reviewed,
                    excerpt=excerpt, line_start=6, line_end=5 + len(body),
                    score=len(matched), matched_keywords=matched,
                    sections=reference_sections(body, document.name, source),
                ))
        hits.sort(key=lambda hit: (-hit.score, hit.document))
        return KnowledgeSearchResult(query=args.query, hits=hits[:args.top_k])
