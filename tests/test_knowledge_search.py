import json
from importlib.resources import files

import pytest

from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.mock import MockBackend
from vasp_copilot.cli import main
from vasp_copilot.rag.retriever import KnowledgeRetriever, MAX_DOCUMENT_BYTES
from vasp_copilot.tools.file_inspection import create_registry


@pytest.mark.parametrize("query,document", [
    ("What does EDIFF mean?", "electronic.md"),
    ("How should electronic self-consistency be understood?", "electronic.md"),
    ("ediffg", "ionic.md"),
    ("ionic convergence", "ionic.md"),
    ("Does termination prove convergence?", "outcar.md"),
    ("OSZICAR", "oszicar.md"),
    ("step numbering for an electronic row and energy summary", "oszicar.md"),
    ("INCAR IBRION NSW parameter checking", "incar.md"),
])
def test_search_returns_sources_and_exact_passage(query, document):
    result = KnowledgeRetriever().search(query, top_k=1)
    hit = result.hits[0]
    assert hit.document == document
    assert hit.evidence_type == "reference"
    assert hit.source.startswith("https://vasp.at/wiki/index.php/")
    lines = files("vasp_copilot.rag").joinpath("knowledge", document).read_text(encoding="utf-8").splitlines()
    assert "\n".join(lines[hit.line_start - 1:hit.line_end]) == hit.excerpt


def test_parameter_boundaries_and_no_match():
    retriever = KnowledgeRetriever()
    assert [hit.document for hit in retriever.search("EDIFFG").hits] == ["ionic.md"]
    assert retriever.search("MY_EDIFF_TAG").hits == []
    assert retriever.search("a completely unrelated banana question").hits == []


@pytest.mark.parametrize("query,document,keyword", [
    ("\u7535\u5b50\u7b97\u6cd5", "algo.md", "electronic algorithm"),
    ("\u5982\u4f55\u7406\u89e3\u7535\u5b50\u81ea\u6d3d", "electronic.md", "electronic self-consistency"),
    ("ICHARG \u975e\u81ea\u6d3d\u8bbe\u7f6e", "icharg.md", "non-self-consistent settings"),
    ("\u53c2\u6570\u4e0d\u4e00\u81f4", "incar.md", "parameter mismatch"),
    ("\u7ed3\u6784\u4f18\u5316", "ionic.md", "structural optimization"),
    ("\u7535\u5b50\u8fed\u4ee3\u4e0a\u9650", "nelm.md", "electronic iteration limit"),
    ("\u7535\u5b50\u884c\u548c\u80fd\u91cf\u6458\u8981\u7684\u6b65\u7f16\u53f7", "oszicar.md", "step numbering"),
    ("\u7a0b\u5e8f\u7ed3\u675f\u53ef\u4ee5\u8bc1\u660e\u6536\u655b\u5417", "outcar.md", "termination"),
])
def test_legacy_queries_return_english_keywords(query, document, keyword):
    hit = KnowledgeRetriever().search(query, top_k=1).hits[0]
    assert hit.document == document
    assert keyword in hit.matched_keywords
    assert hit.title.isascii() and all(word.isascii() for word in hit.matched_keywords)


def test_legacy_alias_and_english_keyword_count_as_one_match():
    query = "structural optimization \u7ed3\u6784\u4f18\u5316"
    hit = KnowledgeRetriever().search(query, top_k=1).hits[0]
    assert hit.document == "ionic.md"
    assert hit.matched_keywords == ["structural optimization"] and hit.score == 1


def test_run7_query_retrieves_oszicar_reference_with_traceable_passage():
    # This exact query previously returned only the generic OUTCAR note.
    query = "OUTCAR OSZICAR step numbering alignment ionic step iteration correspondence"
    result = create_registry().execute("search_knowledge", {"query": query, "top_k": 4})
    assert result.status == "success"
    hits = result.data["hits"]
    assert [hit["document"] for hit in hits] == ["oszicar.md", "outcar.md"]
    hit = hits[0]
    assert hit["source"] == "https://vasp.at/wiki/index.php/OSZICAR"
    lines = files("vasp_copilot.rag").joinpath("knowledge", hit["document"]).read_text(encoding="utf-8").splitlines()
    assert "\n".join(lines[hit["line_start"] - 1:hit["line_end"]]) == hit["excerpt"]
    assert hit["matched_keywords"] == ["oszicar", "step numbering"]
    assert KnowledgeRetriever().search("MY_OSZICAR_TAG").hits == []


def test_ranking_is_deterministic_and_limit_applies():
    retriever = KnowledgeRetriever()
    query = "OUTCAR EDIFF EDIFFG structural optimization"
    first = retriever.search(query, 2)
    assert [hit.document for hit in first.hits] == ["ionic.md", "electronic.md"]
    assert first == retriever.search(query, 2)
    assert first.hits[0].score == 2


@pytest.mark.parametrize("arguments", [
    {}, {"query": " "}, {"query": "x" * 501}, {"query": 12},
    {"query": "EDIFF", "top_k": 0}, {"query": "EDIFF", "top_k": 6},
    {"query": "EDIFF", "top_k": True}, {"query": "EDIFF", "top_k": "2"},
    {"query": "EDIFF", "directory": "C:/private"},
])
def test_tool_rejects_invalid_arguments_and_paths(arguments):
    result = create_registry().execute("search_knowledge", arguments)
    assert result.error.kind == "invalid_arguments"


def test_search_is_independent_of_calculation_directory(tmp_path):
    result = create_registry(tmp_path / "nonexistent").execute("search_knowledge", {"query": "EDIFF"})
    assert result.status == "success"
    assert result.data["hits"][0]["evidence_type"] == "reference"


@pytest.mark.parametrize("content", [b"# Missing source\n", b"x" * (MAX_DOCUMENT_BYTES + 1), b"\xff"],
                         ids=["bad-metadata", "oversized", "invalid-encoding"])
def test_invalid_corpus_is_not_silently_used(tmp_path, content):
    (tmp_path / "bad.md").write_bytes(content)
    with pytest.raises((ValueError, UnicodeError)):
        KnowledgeRetriever(tmp_path).search("EDIFF")


def test_empty_corpus_returns_no_matches(tmp_path):
    assert KnowledgeRetriever(tmp_path).search("EDIFF").hits == []


@pytest.mark.parametrize("content,query,documents", [
    ("Iteration 1( 3)\naborting loop because EDIFF is reached\n", "EDIFF", ["electronic.md"]),
    ("reached required accuracy - stopping structural energy minimisation\n", "EDIFFG", ["ionic.md"]),
    ("unrecognized output\n", "OUTCAR", ["outcar.md"]),
])
def test_observation_selects_reference_topic_and_keeps_unknown(tmp_path, content, query, documents):
    path = tmp_path / "OUTCAR"
    path.write_text(content, encoding="ascii")
    before = path.read_bytes()
    run = AgentLoop(MockBackend(), create_registry(tmp_path)).run("Inspect the calculation", str(tmp_path))
    assert run.status == "completed" and run.decision_steps == 4
    search = run.state.history[-1]
    assert search.call.tool_name == "search_knowledge" and search.call.arguments["query"] == query
    assert [hit["document"] for hit in search.observation.data["hits"]] == documents
    assert "File evidence" in run.answer and "References (general explanation)" in run.answer
    assert "unknown" in run.answer and "https://vasp.at/wiki/" in run.answer
    assert path.read_bytes() == before


@pytest.mark.parametrize("mode", ["error", "empty"])
def test_search_failure_or_no_match_preserves_file_observation(tmp_path, monkeypatch, mode):
    (tmp_path / "OUTCAR").write_text("Iteration 1( 3)\naborting loop because EDIFF is reached\n", encoding="ascii")
    original = KnowledgeRetriever.search
    def search(self, query, top_k=3):
        if mode == "error":
            raise OSError("private detail")
        return original(self, "not-in-corpus", top_k)
    monkeypatch.setattr(KnowledgeRetriever, "search", search)
    run = AgentLoop(MockBackend(), create_registry()).run("Inspect", str(tmp_path))
    assert run.status == "completed"
    assert "reached_marker" in run.answer and "unknown" in run.answer
    assert "private detail" not in run.model_dump_json()
    assert ("Retrieval failed" if mode == "error" else "no matching entries") in run.answer


def test_cli_mock_runs_retrieval_without_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / "OUTCAR").write_text("example\n", encoding="ascii")
    assert main([str(tmp_path), "--agent"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"]["history"][-1]["call"]["tool_name"] == "search_knowledge"
    assert "References" in result["answer"]
