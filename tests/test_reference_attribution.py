"""Reference attribution must survive tool execution, storage, and old reports."""

import copy
import json
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import ValidationError

from vasp_copilot.agent.deepseek import DeepSeekBackend
from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.config import DeepSeekConfig
from vasp_copilot.rag.retriever import KnowledgeRetriever, ReferenceSection, reference_sections
from vasp_copilot.reports.generator import render_markdown
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.tools.file_inspection import create_registry


@pytest.mark.parametrize("query", ["OUTCAR", "OSZICAR", "EDIFF", "EDIFFG", "INCAR IBRION NSW"])
def test_sections_quote_exact_local_lines_and_only_official_summary_has_external_source(query):
    hit = KnowledgeRetriever().search(query, 1).hits[0]
    lines = files("vasp_copilot.rag").joinpath("knowledge", hit.document).read_text(encoding="utf-8").splitlines()
    assert [section.kind for section in hit.sections] == ["official_summary", "project_policy"]
    for section in hit.sections:
        assert section.text == "\n".join(lines[section.line_start - 1:section.line_end])
        assert f"{hit.document}:{section.line_start}-{section.line_end}" in section.citation
    assert hit.sections[0].source_url == hit.source
    assert hit.sections[1].source_url is None and hit.sections[1].citation.startswith("VASP-Copilot ")


def test_unlabelled_paragraph_is_not_promoted_to_official_source():
    sections = reference_sections(["A local note", "continued", "", "本项目使用限制：policy"], "example.md", "https://example.org")
    assert [(s.kind, s.line_start, s.line_end) for s in sections] == [("unclassified", 6, 7), ("project_policy", 9, 9)]
    assert all(s.source_url is None for s in sections)


@pytest.mark.parametrize("kind, url", [("project_policy", "https://example.org"), ("unclassified", "https://example.org"), ("official_summary", None)])
def test_section_cannot_assign_official_url_to_project_policy(kind, url):
    with pytest.raises(ValidationError):
        ReferenceSection(kind=kind, text="text", line_start=6, line_end=6, citation="note:6", source_url=url)


def saved_search(tmp_path):
    payloads = []

    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            return {"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "reference_1", "type": "function", "function": {
                        "name": "search_knowledge", "arguments": json.dumps({"query": "INCAR IBRION NSW"}),
                    },
                }],
            }}]}
        result = json.loads(payload["messages"][-1]["content"])
        sections = result["data"]["hits"][0]["sections"]
        assert sections[0]["source_url"] == "https://vasp.at/wiki/index.php/INCAR"
        assert sections[1]["kind"] == "project_policy" and sections[1]["source_url"] is None
        assert "VASP-Copilot incar.md:8-8" in sections[1]["citation"]
        return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "保留不确定性"}}]}

    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-key"), transport), create_registry(tmp_path),
                    required_tools=("search_knowledge",)).run("核对参数", str(tmp_path))
    assert run.status == "completed"
    repository = RunRepository(tmp_path / "history.sqlite3")
    summary = repository.save(run, "deepseek")
    return repository.get(summary.id)


def test_attribution_reaches_model_and_report_uses_saved_sections_without_rereading(tmp_path, monkeypatch):
    record = saved_search(tmp_path)
    snapshot = copy.deepcopy(record.model_dump())

    def forbidden(*args, **kwargs):
        raise AssertionError("Report must not re-read current documents")

    monkeypatch.setattr(Path, "open", forbidden)
    report = render_markdown(record)
    view = report.split("## 完整保存快照")[0]
    assert "VASP-Copilot incar.md:8-8" in view
    assert view.index("此段对应的官网来源") < view.index("**本项目使用限制**")
    assert "https://" not in view.split("**本项目使用限制**")[1].split("## 后端回答")[0]
    assert record.model_dump() == snapshot


def test_legacy_hit_without_sections_is_preserved_in_report(tmp_path, monkeypatch):
    record = saved_search(tmp_path)
    hit = record.run.state.history[0].observation.data["hits"][0]
    del hit["sections"]
    old = copy.deepcopy(record.model_dump())

    def forbidden(*args, **kwargs):
        raise AssertionError("Old attribution must not be rebuilt from current files")

    monkeypatch.setattr(Path, "open", forbidden)
    report = render_markdown(record)
    assert "此历史记录没有按段归属" in report and hit["excerpt"] in report
    assert record.model_dump() == old
