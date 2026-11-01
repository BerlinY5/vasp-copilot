"""SCF settings are evidence from a prefix, never assumed defaults or run identity."""

import copy
import gzip
import json
from pathlib import Path

import pytest

from vasp_copilot import cli
from vasp_copilot.agent.deepseek import DeepSeekBackend
from vasp_copilot.diagnostics import TAIL_BYTES, diagnose_outcar
from vasp_copilot.electronic_diagnosis import diagnose_electronic_step
from vasp_copilot.iterations import NOT_REACHED, observe_last_iteration
from vasp_copilot.reports.generator import render_markdown
from vasp_copilot.scf_settings import HEAD_BYTES, observe_electronic_settings
from vasp_copilot.storage.repository import RunRepository
from vasp_copilot.rag.retriever import KnowledgeRetriever

FAILURE = b"Iteration 1( 13)\n" + NOT_REACHED + b"\n"


def parse(content):
    return observe_electronic_settings(content, len(content))


def parameter(result, name):
    return next(p for p in result.parameters if p.name == name)


def test_true_outcar_semicolon_layout_keeps_exact_offsets_and_no_algo_inference():
    prefix = "\u6807\u9898\r\n".encode("utf-8")
    rows = [b" NELM = 100; NELMIN=2; NELMDL=-5  # steps\r\n", b" EDIFF = .2D-05  stopping criterion\r\n",
            b" ICHARG = 2 charge\r\n", b" IALGO = 68 algorithm\r\n"]
    result = parse(prefix + b"".join(rows))
    for name, value, offset in [("NELM", 100, len(prefix)), ("EDIFF", 2e-6, len(prefix) + len(rows[0])),
                                ("ICHARG", 2, len(prefix) + len(rows[0]) + len(rows[1]))]:
        item = parameter(result, name)
        assert item.status == "observed" and item.value == value
        assert item.evidence[0].byte_offset == offset
    assert parameter(result, "EDIFF").evidence[0].text.encode() == rows[1].rstrip(b"\r\n")
    assert parameter(result, "IALGO").value == 68
    assert parameter(result, "ALGO").status == "missing" and parameter(result, "ALGO").value is None
    assert result.iteration_association == "unknown"


@pytest.mark.parametrize("literal, value", [("1.", 1.0), (".5", .5), ("1e-6", 1e-6), ("+2D-6", 2e-6), ("0", 0.0)])
def test_supported_finite_ediff_literals(literal, value):
    assert parameter(parse(f"EDIFF = {literal}\n".encode()), "EDIFF").value == value


@pytest.mark.parametrize("assignment", [
    "EDIFF=nan", "EDIFF=inf", "EDIFF=-1e-6", "EDIFF=1e999", "EDIFF=1e-999",
    "EDIFF=1e-", "EDIFF=1e-6x", "EDIFF=1e-6 2", "EDIFF=0.1 EDIFFG=2",
    "NELM=0", "NELM=1.5", "NELM=1234567890", "ICHARG=-1", "IALGO=2.0", "ALGO='Normal'",
])
def test_bad_literals_are_ambiguous_not_values_or_defaults(assignment):
    name = assignment.split("=")[0]
    item = parameter(parse((assignment + "\n").encode()), name)
    assert item.status == "ambiguous" and item.value is None and item.issues


@pytest.mark.parametrize("suffix", [b"EDIFF = 1e-6\n", b"EDIFF = 2e-6\n", b"EDIFF = bad\n"])
def test_duplicate_assignments_never_choose_last_value_and_evidence_is_bounded(suffix):
    result = parse(b"EDIFF = 1e-6\n" + suffix * 40)
    item = parameter(result, "EDIFF")
    assert item.status == "ambiguous" and item.value is None and item.occurrences == 41
    assert len(item.evidence) == 2


def test_tag_boundaries_companions_quotes_and_incomplete_lines():
    result = parse(b"EDIFFG = 1e-4\nNELMIN = 3; NELMDL=-5; NELM=100\nSYSTEM = EDIFF=0\nALGO = Old Fast\nICHARG=2")
    assert parameter(result, "EDIFF").status == "missing"
    assert parameter(result, "NELM").value == 100
    assert parameter(result, "ALGO").value == "Old Fast"
    assert parameter(result, "ICHARG").status == "ambiguous"


def test_encoding_damage_even_in_a_comment_does_not_supply_a_reliable_value():
    item = parameter(parse(b"EDIFF=0 # bad encoding \xff\n"), "EDIFF")
    assert item.status == "ambiguous" and item.value is None


@pytest.mark.parametrize("attribute", ["st_size", "st_mtime_ns"])
def test_changed_file_rejects_settings_and_tail_diagnosis(tmp_path, monkeypatch, attribute):
    from types import SimpleNamespace
    from vasp_copilot import diagnostics
    path = tmp_path / "OUTCAR"
    path.write_bytes(b"EDIFF=0\n" + FAILURE)
    initial = path.stat()
    stable = {"st_size": initial.st_size, "st_mtime_ns": initial.st_mtime_ns}
    changed = dict(stable)
    changed[attribute] += 1
    snapshots = iter([SimpleNamespace(**stable), SimpleNamespace(**changed)])
    # Keep the two synthetic samples local; pytest capture also uses os.fstat.
    monkeypatch.setattr(diagnostics, "os", SimpleNamespace(fstat=lambda fd: next(snapshots)))
    result = diagnose_outcar(path)
    assert result.error and result.electronic_settings is None and result.electronic_step_diagnosis is None


def test_prefix_is_bounded_and_truncated_assignment_not_used():
    payload = b"x" * (HEAD_BYTES - 9) + b"\nEDIFF=0.5\n" + b"NELM=100\n"
    result = observe_electronic_settings(payload[:HEAD_BYTES + 1], len(payload))
    assert result.bytes_read == HEAD_BYTES + 1 and result.window_limited
    assert parameter(result, "EDIFF").status == "ambiguous"
    assert parameter(result, "NELM").status == "missing"


@pytest.mark.parametrize("name, prefix, kind", [
    ("EDIFF", b"EDIFF=0\n", "ediff_zero"),
    ("ICHARG", b"ICHARG=11\n", "fixed_charge"),
    ("ALGO", b"ALGO=None\n", "postprocessing"),
    ("ALGO", b"ALGO=Nothing\n", "postprocessing"),
    ("ALGO", b"ALGO=Eigenval\n", "postprocessing"),
])
def test_special_setting_only_adds_conditional_context_never_erases_message(name, prefix, kind):
    settings = parse(prefix + FAILURE)
    observation = observe_last_iteration(prefix + FAILURE, 0)
    before = copy.deepcopy(settings.model_dump())
    diagnosis = diagnose_electronic_step(observation, settings)
    assert diagnosis.status == "reported_not_reached" and diagnosis.severity == "warning"
    note = next(c for c in diagnosis.settings_considerations if c.kind == kind)
    assert "If" in note.summary and note.evidence[0].text.startswith(name)
    assert settings.model_dump() == before


@pytest.mark.parametrize("limit, relation", [(100, "below"), (13, "equal"), (5, "above")])
def test_nelm_comparison_is_numeric_only_not_an_exhaustion_verdict(limit, relation):
    content = f"NELM={limit}\n".encode() + FAILURE
    diagnosis = diagnose_electronic_step(observe_last_iteration(content, 0), parse(content))
    assert diagnosis.status == "reported_not_reached"
    check = next(c for c in diagnosis.settings_considerations if c.kind == "sampled_step_vs_nelm")
    assert check.relation == relation and "this does not establish" in check.summary


@pytest.mark.parametrize("content", [
    b"vasp.6.4.3\nEDIFF=0\nvasp.6.4.3 new run\n" + FAILURE,
    b"EDIFF=0\nvasp.6.4.3 new run\n" + FAILURE,
])
def test_run_restart_does_not_apply_earlier_parameters(content):
    settings = parse(content)
    diagnosis = diagnose_electronic_step(observe_last_iteration(content, 0), settings)
    assert settings.issues and diagnosis.status == "reported_not_reached"
    assert not diagnosis.settings_considerations
    assert "the prefix settings cannot be applied to this loop" in diagnosis.recommendations[1]


def test_unreliable_parameter_does_not_trigger_special_mode_interpretation():
    content = b"EDIFF=0\nEDIFF=1e-6\nNELM=13\nNELM=100\n" + FAILURE
    diagnosis = diagnose_electronic_step(observe_last_iteration(content, 0), parse(content))
    assert diagnosis.status == "reported_not_reached" and not diagnosis.settings_considerations


@pytest.mark.parametrize("query, document", [("ICHARG", "icharg.md"), ("IALGO ALGO", "algo.md")])
def test_new_setting_references_are_packaged_and_keep_project_policy_separate(query, document):
    hit = KnowledgeRetriever().search(query, 1).hits[0]
    assert hit.document == document and hit.sections[0].source_url == hit.source
    assert hit.sections[1].kind == "project_policy" and hit.sections[1].source_url is None


def test_large_file_reads_bounded_head_and_tail_and_detects_later_run(tmp_path, monkeypatch):
    path = tmp_path / "OUTCAR"
    path.write_bytes(b"EDIFF=0\n" + b"x" * (HEAD_BYTES + TAIL_BYTES) + b"\nvasp.6.4.3\n" + FAILURE)
    requests = []
    real_open = Path.open

    class ReadTracker:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()
        def fileno(self):
            return self.handle.fileno()
        def seek(self, *args):
            return self.handle.seek(*args)
        def read(self, size=-1):
            requests.append(size)
            assert 0 <= size <= HEAD_BYTES + 1
            return self.handle.read(size)

    monkeypatch.setattr(Path, "open", lambda p, *a, **kw: ReadTracker(real_open(p, *a, **kw)))
    result = diagnose_outcar(path)
    assert requests == [HEAD_BYTES + 1, TAIL_BYTES]
    assert result.electronic_settings.issues
    assert result.electronic_step_diagnosis.status == "reported_not_reached"
    assert not result.electronic_step_diagnosis.settings_considerations


@pytest.mark.parametrize("sample, icharg, ediff", [("static_silicon", 2, 2e-6), ("relaxation", 1, 5e-5)])
def test_real_public_settings_keep_original_bytes(tmp_path, sample, icharg, ediff):
    fixture = Path(__file__).parent / "fixtures/pymatgen" / f"{sample}.OUTCAR.gz"
    raw = gzip.decompress(fixture.read_bytes())
    path = tmp_path / "OUTCAR"
    path.write_bytes(raw)
    report = diagnose_outcar(path)
    settings = report.electronic_settings
    assert parameter(settings, "NELM").value == 100
    assert parameter(settings, "EDIFF").value == ediff
    assert parameter(settings, "ICHARG").value == icharg
    assert parameter(settings, "IALGO").value == 68
    assert parameter(settings, "ALGO").status == "missing"
    assert report.electronic_step_diagnosis.status == "not_triggered"
    for item in settings.parameters:
        for evidence in item.evidence:
            line = raw[evidence.byte_offset:].splitlines()[0].decode()
            assert evidence.text == line
    assert path.read_bytes() == raw


def test_real_model_message_save_report_and_legacy_snapshot(tmp_path, monkeypatch, capsys):
    (tmp_path / "OUTCAR").write_bytes(b"EDIFF=2D-6\nNELM=100; NELMIN=2\nICHARG=2\nIALGO=68\n" + FAILURE)
    requests = []

    def transport(payload, config):
        requests.append(payload)
        if len(requests) == 1:
            return {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "settings_1", "type": "function", "function": {
                    "name": "diagnose_outcar", "arguments": json.dumps({"directory": str(tmp_path)})}}]}}]}
        data = json.loads(payload["messages"][-1]["content"])["data"]
        values = {p["name"]: p for p in data["electronic_settings"]["parameters"]}
        assert values["EDIFF"]["value"] == 2e-6 and values["ALGO"]["status"] == "missing"
        assert data["electronic_step_diagnosis"]["settings_considerations"][0]["relation"] == "below"
        assert data["electronic_convergence"] == "unknown"
        return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Prefix NELM=100, sampled step number 13; this does not establish exhaustion of the limit."}}]}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(cli, "DeepSeekBackend", lambda config: DeepSeekBackend(config, transport))
    database = tmp_path / "history.sqlite3"
    assert cli.main([str(tmp_path), "--agent", "--backend", "deepseek", "--save-history", "--db", str(database)]) == 0
    result = json.loads(capsys.readouterr().out)
    record = RunRepository(database).get(result["history_record"]["run_id"])
    report = render_markdown(record)
    assert "OUTCAR prefix electronic self-consistency settings" in report and "Conditional notes" in report
    old = copy.deepcopy(record)
    diagnosis = old.run.state.history[0].observation.data
    del diagnosis["electronic_settings"], diagnosis["electronic_step_diagnosis"]["settings_considerations"]
    snapshot = old.model_dump()
    assert "Electronic self-consistency settings were not generated or saved" in render_markdown(old)
    assert old.model_dump() == snapshot
