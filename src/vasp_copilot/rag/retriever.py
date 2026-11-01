"""Search short, curated Markdown notes with English and legacy query keywords."""

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

# Preserve existing Chinese queries while the maintained corpus uses English.
# Each alias belongs to one canonical keyword and never adds a second score.
LEGACY_KEYWORD_ALIASES: dict[str, tuple[str, ...]] = {
    "electronic algorithm": ("\u7535\u5b50\u7b97\u6cd5",),
    "post-processing settings": ("\u540e\u5904\u7406\u8bbe\u7f6e",),
    "electronic convergence": ("\u7535\u5b50\u6536\u655b",),
    "electronic self-consistency": ("\u7535\u5b50\u81ea\u6d3d",),
    "self-consistency": ("\u81ea\u6d3d",),
    "fixed charge": ("\u56fa\u5b9a\u7535\u8377",),
    "non-self-consistent settings": ("\u975e\u81ea\u6d3d\u8bbe\u7f6e",),
    "parameter checking": ("\u53c2\u6570\u6838\u5bf9",),
    "parameter mismatch": ("\u53c2\u6570\u4e0d\u4e00\u81f4",),
    "input-output": ("\u8f93\u5165\u8f93\u51fa",),
    "ionic convergence": ("\u79bb\u5b50\u6536\u655b",),
    "structural optimization": ("\u7ed3\u6784\u4f18\u5316",),
    "force convergence": ("\u529b\u6536\u655b",),
    "electronic iteration limit": ("\u7535\u5b50\u8fed\u4ee3\u4e0a\u9650",),
    "SCF problems": ("\u81ea\u6d3d\u5f02\u5e38",),
    "EDIFF not reached": ("\u672a\u8fbeEDIFF",),
    "step numbering": ("\u6b65\u7f16\u53f7",),
    "step index": ("\u6b65\u53f7",),
    "electronic row": ("\u7535\u5b50\u884c",),
    "energy summary": ("\u80fd\u91cf\u6458\u8981",),
    "output file": ("\u8f93\u51fa\u6587\u4ef6",),
    "termination": ("\u7a0b\u5e8f\u7ed3\u675f",),
    "timing": ("\u8ba1\u65f6",),
}
LEGACY_KEYWORD_ALIASES = {keyword.casefold(): aliases for keyword, aliases in LEGACY_KEYWORD_ALIASES.items()}
OFFICIAL_SUMMARY_LABELS = ("Official-source summary:", "\u5b98\u65b9\u8d44\u6599\u6458\u8981\uff1a")
PROJECT_POLICY_LABELS = ("Project policy:", "\u672c\u9879\u76ee\u4f7f\u7528\u9650\u5236\uff1a")


class SearchKnowledgeArgs(Schema):
    query: str = Field(min_length=1, max_length=500, description="VASP terms or a short question in English or Chinese")
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
        "The local knowledge base is reference material, not file evidence for this calculation; "
        "no matches do not indicate a calculation problem. "
        "'Official-source summary:' in an excerpt is the project's paraphrase of the source, "
        "not a direct quotation. 'Project policy:' comes from VASP-Copilot and must not be "
        "attributed to the official source. Result sections identify attribution by paragraph: "
        "external source URLs support only official_summary sections; cite project_policy "
        "using its citation (the project note and line numbers), without reusing an official-source citation."
    )


def keyword_matches(keyword: str, query: str) -> bool:
    """Keep ASCII parameter boundaries: EDIFF must not match EDIFFG."""
    keyword, query = keyword.casefold(), query.casefold()
    if keyword.isascii():
        return re.search(r"(?<![a-z0-9_])" + re.escape(keyword) + r"(?![a-z0-9_])", query) is not None
    return keyword in query


def query_matches_keyword(keyword: str, query: str) -> bool:
    """Accept legacy aliases without duplicating a canonical keyword's score."""
    return keyword_matches(keyword, query) or any(
        keyword_matches(alias, query) for alias in LEGACY_KEYWORD_ALIASES.get(keyword.casefold(), ())
    )


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
        kind = ("official_summary" if paragraph[0].startswith(OFFICIAL_SUMMARY_LABELS) else
                "project_policy" if paragraph[0].startswith(PROJECT_POLICY_LABELS) else "unclassified")
        location = f"{document}:{start}-{number - 1}"
        citation = (f"{location} (official-source summary; project paraphrase)" if kind == "official_summary" else
                    f"VASP-Copilot {location}" if kind == "project_policy" else
                    f"{location} (unclassified attribution)")
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
            matched = [word for word in keywords if query_matches_keyword(word, args.query)]
            if matched:
                hits.append(KnowledgeHit(
                    document=document.name, title=title, source=source, reviewed_on=reviewed,
                    excerpt=excerpt, line_start=6, line_end=5 + len(body),
                    score=len(matched), matched_keywords=matched,
                    sections=reference_sections(body, document.name, source),
                ))
        hits.sort(key=lambda hit: (-hit.score, hit.document))
        return KnowledgeSearchResult(query=args.query, hits=hits[:args.top_k])
