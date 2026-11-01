import json
from pathlib import Path

import pytest

from vasp_copilot.cli import main
from vasp_copilot.input_context import inspect_incar
from vasp_copilot.output_context import HEAD_BYTES, compare_contexts, inspect_outcar_parameters


def compare_files(tmp_path, output, input_text="IBRION=2;NSW=20"):
    (tmp_path / "INCAR").write_text(input_text, encoding="ascii")
    (tmp_path / "OUTCAR").write_bytes(output)
    observed = inspect_outcar_parameters(tmp_path / "OUTCAR")
    return observed, compare_contexts(inspect_incar(tmp_path / "INCAR"), observed)


def test_comparison_keeps_values_and_exact_evidence(tmp_path):
    prefix = "title: 测试\r\n".encode()
    observed, report = compare_files(tmp_path, prefix + b" IBRION = 2 ionic relaxation\r\n NSW = 30 steps\r\n")
    assert [p.status for p in report.parameters] == ["matched", "mismatched"]
    assert report.parameters[1].incar_value == 20
    assert report.parameters[1].outcar_value == 30
    assert observed.parameters[0].evidence.byte_offset == len(prefix)
    assert observed.parameters[0].evidence.text == " IBRION = 2 ionic relaxation"


@pytest.mark.parametrize("output", [
    b"IBRION=2; NSW=20\n", b"IBRION=2 NSW=20\n",
    b"IBRION=2\nNSW=20\nIBRION=0\n", b"IBRION=2\nNSW=20\nNSW=20\n",
    b"IBRION=2.5\nNSW=20\n", b"IBRION=2\nNSW=20e0\n",
    b"IBRION=2\nNSW=20", b"IBRION=2\nNSW broken\n",
    b"IBRION=2\x00\nNSW=20\n", b"IBRION=2 invalid\xff\nNSW=20\n",
])
def test_ambiguous_output_is_unknown(tmp_path, output):
    observed, report = compare_files(tmp_path, output)
    assert observed.issues or observed.error
    assert all(p.status == "unknown" for p in report.parameters)


def test_missing_parameter_is_unknown_not_mismatch(tmp_path):
    _, report = compare_files(tmp_path, b"IBRION=2\n")
    assert [p.status for p in report.parameters] == ["matched", "unknown"]
    assert report.parameters[1].outcar_value is None


def test_embedded_assignment_is_not_parameter_line(tmp_path):
    observed, report = compare_files(tmp_path, b"SYSTEM = IBRION=2\n# NSW=20\n")
    assert observed.parameters == []
    assert all(p.status == "unknown" for p in report.parameters)


@pytest.mark.parametrize("input_text", ["IBRION=2", "IBRION=2;NSW=20;NSW=30"])
def test_ambiguous_input_blocks_comparison(tmp_path, input_text):
    _, report = compare_files(tmp_path, b"IBRION=2\nNSW=20\n", input_text)
    assert all(p.status == "unknown" for p in report.parameters)


def test_read_limit_is_enforced_and_split_line_discarded(tmp_path, monkeypatch):
    payload = b"x" * (HEAD_BYTES - 8) + b"\nNSW=20000\n"
    path = tmp_path / "OUTCAR"
    path.write_bytes(payload)
    original_open = Path.open
    reads = []
    class ReadProbe:
        def __enter__(self):
            self.stream = original_open(path, "rb")
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size=-1):
            reads.append(size)
            return self.stream.read(size)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: ReadProbe())
    observed = inspect_outcar_parameters(path)
    assert reads == [HEAD_BYTES + 1]
    assert observed.bytes_read == HEAD_BYTES + 1
    assert observed.window_limited
    assert not observed.parameters
    assert observed.issues


@pytest.mark.parametrize("kind", ["missing", "directory", "permission"])
def test_file_errors(tmp_path, monkeypatch, kind):
    path = tmp_path / "OUTCAR"
    if kind == "directory":
        path.mkdir()
    elif kind == "permission":
        def denied(*args, **kwargs):
            raise PermissionError("test denied")
        monkeypatch.setattr(Path, "open", denied)
    observed = inspect_outcar_parameters(path)
    assert observed.error is not None


def test_cli_reports_mismatch_without_changing_originals(tmp_path, capsys):
    compare_files(tmp_path, b"IBRION=0\nNSW=20\n")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert main([str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["context_comparison"]["parameters"][0]["status"] == "mismatched"
    assert report["calculation_status"] == "unknown"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
