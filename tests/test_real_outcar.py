"""Offline regression against pinned public logs, plus explicitly derived cases."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from vasp_copilot.cli import main
from vasp_copilot.diagnostics import diagnose_outcar
from vasp_copilot.output_context import inspect_outcar_parameters

FIXTURES = Path(__file__).parent / "fixtures" / "pymatgen"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
# Independently checked against literal lines in the upstream files, not generated
# from this project's parser. All offsets are in the decompressed original bytes.
EXPECTED = {
    "static_silicon": dict(ibrion=-1, nsw=0, ionic=1, electronic=13,
                           header_offset=42249, message_offset=54994, ionic_marker="unknown"),
    "relaxation": dict(ibrion=2, nsw=99, ionic=3, electronic=4,
                       header_offset=86842, message_offset=99982, ionic_marker="marker_found"),
}


def sample(name):
    return gzip.decompress((FIXTURES / MANIFEST["samples"][name]["path"]).read_bytes())


@pytest.mark.parametrize("name", EXPECTED)
def test_public_fixture_integrity(name):
    data = sample(name)
    metadata = MANIFEST["samples"][name]
    assert len(data) == metadata["uncompressed_bytes"]
    assert hashlib.sha256(data).hexdigest() == metadata["sha256"]


@pytest.mark.parametrize("name", EXPECTED)
def test_real_logs_parameters_and_iteration(tmp_path, name):
    data = sample(name)
    path = tmp_path / "OUTCAR"
    path.write_bytes(data)
    expected = EXPECTED[name]
    context = inspect_outcar_parameters(path)
    assert context.error is None and context.issues == []
    assert {p.name: p.value for p in context.parameters} == {
        "IBRION": expected["ibrion"], "NSW": expected["nsw"],
    }
    report = diagnose_outcar(path)
    assert report.error is None
    last = report.last_iteration
    assert (last.ionic_step, last.electronic_step) == (expected["ionic"], expected["electronic"])
    assert last.status == "reached_marker"
    assert last.header.byte_offset == expected["header_offset"]
    assert last.markers[0].byte_offset == expected["message_offset"]
    for evidence in [last.header, *last.markers, *(p.evidence for p in context.parameters)]:
        assert data[evidence.byte_offset:].split(b"\n", 1)[0].decode() == evidence.text
    findings = {f.rule_id: f.status for f in report.findings}
    assert findings["outcar.timing_marker"] == "marker_found"
    assert findings["outcar.ionic_stop_marker"] == expected["ionic_marker"]
    assert report.electronic_convergence == report.ionic_convergence == "unknown"
    assert path.read_bytes() == data


def test_derived_truncation_does_not_inherit_earlier_ionic_step(tmp_path):
    data = sample("relaxation")
    # Keep the third ionic step's first header but remove subsequent lines.
    marker = b"Iteration    3(   1)"
    position = data.index(marker)
    truncated = data[:data.index(b"\n", position) + 1]
    path = tmp_path / "OUTCAR"
    path.write_bytes(truncated)
    last = diagnose_outcar(path).last_iteration
    assert (last.ionic_step, last.electronic_step) == (3, 1)
    assert last.status == "unknown"
    assert last.markers == []


def test_derived_new_run_header_clears_previous_observation(tmp_path):
    data = sample("relaxation") + sample("static_silicon").split(b"\n", 1)[0] + b"\n"
    path = tmp_path / "OUTCAR"
    path.write_bytes(data)
    last = diagnose_outcar(path).last_iteration
    assert last.header is None and last.status == "unknown"


def test_derived_concatenation_keeps_absolute_offsets(tmp_path):
    first, second = sample("relaxation"), sample("static_silicon")
    path = tmp_path / "OUTCAR"
    path.write_bytes(first + second)
    last = diagnose_outcar(path).last_iteration
    assert (last.ionic_step, last.electronic_step) == (1, 13)
    assert last.header.byte_offset == len(first) + EXPECTED["static_silicon"]["header_offset"]


def test_cli_real_log_with_explicitly_synthetic_input(tmp_path, capsys):
    (tmp_path / "OUTCAR").write_bytes(sample("static_silicon"))
    # This INCAR is constructed for integration testing, not an upstream input.
    (tmp_path / "INCAR").write_text("IBRION=-1;NSW=0\n", encoding="ascii")
    assert main([str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["input_context"]["calculation_type"] == "static"
    assert all(p["status"] == "matched" for p in report["context_comparison"]["parameters"])
    assert report["diagnostics"]["last_iteration"]["status"] == "reached_marker"
    assert report["calculation_status"] == "unknown"
