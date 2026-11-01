"""Test that the evaluator detects regressions, not just the successful baseline."""

import gzip
import hashlib
import socket
from pathlib import Path

import pytest

from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.config import DeepSeekConfig
from vasp_copilot.evaluation.cases import FixtureError, build_scenarios, load_samples
from vasp_copilot.evaluation.runner import evaluate, run_scenario

FIXTURES = Path(__file__).parent / "fixtures" / "pymatgen"


def test_suite_is_offline_repeatable_and_does_not_change_fixtures(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation must not load API configuration or access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(DeepSeekConfig, "from_env", forbidden)
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in FIXTURES.iterdir() if path.is_file()}
    first, second = evaluate(FIXTURES), evaluate(FIXTURES)
    assert first == second
    assert (first.total, first.passed, first.failed, first.status) == (16, 16, 0, "passed")
    assert first.suite == "mock-agent-v2"
    assert first.fixture_sha256["static_silicon_oszicar"] == "1e3f219d8da90386d1f354cb7a8476084a7f4aea0d43514a21eda19d18c3664f"
    assert all(case.checks and all(check.passed for check in case.checks) for case in first.cases)
    assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in FIXTURES.iterdir() if path.is_file()}


@pytest.mark.parametrize("fault, expected_check", [
    ("offset", "iteration"),
    ("evidence_text", "outcar_evidence_1"),
    ("missing_evidence", "outcar.timing_marker.evidence_count"),
    ("tool_order", "tools"),
    ("verdict", "overall_verdicts"),
    ("reference", "reference_source_0"),
    ("answer", "answer_source_0"),
    ("input_mutation", "inputs_unchanged"),
    ("question", "question_preserved"),
])
def test_detects_deliberate_trace_corruption(monkeypatch, tmp_path, fault, expected_check):
    original = AgentLoop.run

    def corrupted(self, question, directory):
        run = original(self, question, directory)
        diagnosis = run.state.history[1].observation.data
        if fault == "offset":
            diagnosis["last_iteration"]["markers"][0]["byte_offset"] += 1
        elif fault == "evidence_text":
            diagnosis["last_iteration"]["markers"][0]["text"] = "invented evidence"
        elif fault == "missing_evidence":
            diagnosis["findings"][0]["evidence"] = []
        elif fault == "tool_order":
            run.state.history[0], run.state.history[1] = run.state.history[1], run.state.history[0]
        elif fault == "verdict":
            diagnosis["electronic_convergence"] = "converged"
        elif fault == "reference":
            run.state.history[2].observation.data["hits"][0]["source"] = "https://example.invalid/invented"
        elif fault == "answer":
            run.answer = "An answer without the reference URL"
        elif fault == "input_mutation":
            (Path(directory) / "OUTCAR").write_bytes(b"changed input")
        elif fault == "question":
            run.state.question = "changed question"
        return run

    monkeypatch.setattr(AgentLoop, "run", corrupted)
    case = build_scenarios(load_samples(FIXTURES))[0]
    result = run_scenario(case, tmp_path)
    assert result.status == "failed"
    assert expected_check in {check.name for check in result.checks if not check.passed}


def test_case_exception_is_recorded_and_other_cases_continue(monkeypatch):
    original = AgentLoop.run

    def broken(self, question, directory):
        if Path(directory).name == "static_silicon":
            raise RuntimeError("private diagnostic detail")
        return original(self, question, directory)

    monkeypatch.setattr(AgentLoop, "run", broken)
    result = evaluate(FIXTURES)
    assert (result.status, result.passed, result.failed) == ("failed", 15, 1)
    assert result.cases[0].status == "error"
    assert result.cases[0].error.message == "RuntimeError"
    assert "private diagnostic detail" not in result.model_dump_json()


@pytest.mark.parametrize("raw", [b"short", b"x" * 61474, b"x" * 61475], ids=["short", "changed_hash", "oversized"])
def test_changed_or_oversized_fixture_rejected(tmp_path, raw):
    (tmp_path / "static_silicon.OUTCAR.gz").write_bytes(gzip.compress(raw))
    with pytest.raises(FixtureError, match="size or SHA-256"):
        load_samples(tmp_path)


def test_invalid_gzip_rejected(tmp_path):
    (tmp_path / "static_silicon.OUTCAR.gz").write_bytes(b"invalid")
    with pytest.raises(FixtureError, match="Cannot read"):
        load_samples(tmp_path)


def test_keyboard_interrupt_is_not_hidden(monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(AgentLoop, "run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        evaluate(FIXTURES)
