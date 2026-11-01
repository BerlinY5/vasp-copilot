"""Local electronic-loop warnings must never become whole-run verdicts."""

import copy
import gzip
import json
from pathlib import Path

import pytest

from vasp_copilot import cli
from vasp_copilot.agent.deepseek import DeepSeekBackend
from vasp_copilot.diagnostics import TAIL_BYTES, diagnose_outcar
from vasp_copilot.electronic_diagnosis import diagnose_electronic_step
from vasp_copilot.iterations import NOT_REACHED, REACHED, observe_last_iteration
from vasp_copilot.reports.generator import render_markdown
from vasp_copilot.storage.repository import RunRepository


def header(ionic=1, electronic=60):
    return f"---- Iteration {ionic}( {electronic}) ----\n".encode("ascii")


FAILURE = header() + b"---- " + NOT_REACHED + b" ----\n"


def inspect(tmp_path, content):
    path = tmp_path / "OUTCAR"
    path.write_bytes(content)
    result = diagnose_outcar(path)
    assert path.read_bytes() == content
    assert result.electronic_convergence == result.ionic_convergence == result.normal_termination == "unknown"
    return result.electronic_step_diagnosis


def test_explicit_last_loop_report_produces_warning_with_impact_checks_and_exact_evidence(tmp_path):
    prefix = "样例前缀\r\n".encode("utf-8")
    result = inspect(tmp_path, prefix + FAILURE)
    assert result.status == "reported_not_reached" and result.severity == "warning"
    assert (result.ionic_step, result.electronic_step) == (1, 60)
    assert [e.byte_offset for e in result.evidence] == [len(prefix), len(prefix) + len(header())]
    assert [e.text.encode("ascii") for e in result.evidence] == FAILURE.splitlines()
    assert result.impact and len(result.recommendations) == 4
    assert any("NELM" in item for item in result.recommendations)
    assert all(url.startswith("https://") for url in result.sources)


@pytest.mark.parametrize("content", [
    NOT_REACHED + b"\n",  # no header
    header(),  # no stopping message
    FAILURE + header(2, 1),  # new cycle clears the old report
    FAILURE + b"vasp.6.4.3 new run\n",
    FAILURE + b"Iteration broken\n",
    FAILURE + b"unfinished final line",
    header() + b"quoted: " + NOT_REACHED + b"\n",
    header() + REACHED + b"\n" + NOT_REACHED + b"\n",
    header() + NOT_REACHED + b"\n" + REACHED + b"\n",
    b"NELM = 60\nEDIFF = 0\nICHARG = 11\n" + header(),
])
def test_no_warning_for_ambiguous_stale_or_count_only_evidence(tmp_path, content):
    result = inspect(tmp_path, content)
    assert result.status == "unknown" and result.severity is None
    assert not result.recommendations and not result.evidence and result.impact is None


def test_later_reached_message_does_not_inherit_old_warning_or_prove_convergence(tmp_path):
    result = inspect(tmp_path, FAILURE + header(2, 13) + REACHED + b"\n")
    assert result.status == "not_triggered" and result.severity is None
    assert not result.recommendations and result.impact is None
    assert result.ionic_step == 2 and result.evidence[-1].text == REACHED.decode("ascii")


def test_later_unreached_loop_takes_precedence_over_earlier_reached(tmp_path):
    prefix = header(1, 13) + REACHED + b"\n"
    result = inspect(tmp_path, prefix + header(2, 60) + NOT_REACHED + b"\n")
    assert result.status == "reported_not_reached" and result.ionic_step == 2
    assert result.evidence[0].byte_offset == len(prefix)


def test_tail_window_requires_a_header_inside_the_retained_sample(tmp_path):
    result = inspect(tmp_path, header() + b"x" * TAIL_BYTES + b"\n" + NOT_REACHED + b"\n")
    assert result.status == "unknown" and not result.recommendations


def test_missing_outcar_does_not_generate_an_abnormality(tmp_path):
    report = diagnose_outcar(tmp_path / "missing")
    assert report.error and report.electronic_step_diagnosis is None


def test_pure_rule_requires_sane_message_order_and_does_not_mutate_observation():
    observation = observe_last_iteration(FAILURE, 0)
    original = observation.model_dump()
    result = diagnose_electronic_step(observation)
    result.evidence[0].text = "changed by consumer"
    assert observation.model_dump() == original
    observation.markers[0].byte_offset = 0
    assert diagnose_electronic_step(observation).status == "unknown"


@pytest.mark.parametrize("sample", ["static_silicon", "relaxation"])
def test_existing_public_reached_logs_do_not_get_a_false_warning(tmp_path, sample):
    fixture = Path(__file__).parent / "fixtures/pymatgen" / f"{sample}.OUTCAR.gz"
    result = inspect(tmp_path, gzip.decompress(fixture.read_bytes()))
    assert result.status == "not_triggered" and result.severity is None


def test_native_agent_gets_local_warning_and_references_then_saves_and_renders(tmp_path, monkeypatch, capsys):
    (tmp_path / "OUTCAR").write_bytes(FAILURE)
    payloads = []

    def transport(payload, config):
        payloads.append(payload)
        turn = len(payloads)
        if turn in (1, 2):
            name = "diagnose_outcar" if turn == 1 else "search_knowledge"
            args = {"directory": str(tmp_path)} if turn == 1 else {"query": "EDIFF NELM"}
            if turn == 2:
                data = json.loads(payload["messages"][-1]["content"])["data"]
                assert data["electronic_step_diagnosis"]["status"] == "reported_not_reached"
                assert data["electronic_convergence"] == "unknown"
            return {"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": f"call_{turn}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}}],
            }}]}
        hits = json.loads(payload["messages"][-1]["content"])["data"]["hits"]
        assert {hit["document"] for hit in hits} == {"electronic.md", "nelm.md"}
        return {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "最后采样循环报告未达 EDIFF；应先核对模式与设置。整体状态未知。",
        }}]}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli, "DeepSeekBackend", lambda config: DeepSeekBackend(config, transport))
    database = tmp_path / "history.sqlite3"
    assert cli.main([str(tmp_path), "--agent", "--backend", "deepseek", "--require-knowledge",
                     "--save-history", "--db", str(database)]) == 0
    output = json.loads(capsys.readouterr().out)
    record = RunRepository(database).get(output["history_record"]["run_id"])
    report = render_markdown(record)
    assert "reported\\_not\\_reached" in report and "影响与风险" in report
    assert "建议人工核查" in report and record.run.state.history[0].observation.data["electronic_convergence"] == "unknown"
    old = copy.deepcopy(record)
    del old.run.state.history[0].observation.data["electronic_step_diagnosis"]
    snapshot = old.model_dump()
    legacy_report = render_markdown(old)
    assert "此记录未生成或未保存电子循环局部诊断" in legacy_report
    assert "**最后采样电子循环的局部诊断**" not in legacy_report
    assert old.model_dump() == snapshot  # No rule backfill into an older snapshot.
