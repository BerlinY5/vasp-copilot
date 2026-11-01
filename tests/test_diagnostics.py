import json

import pytest
from pydantic import ValidationError

from vasp_copilot.cli import main
from vasp_copilot.diagnostics import IONIC, TIMING, TAIL_BYTES, diagnose_outcar
from vasp_copilot.schemas import Evidence, FileInspection, Finding


@pytest.mark.parametrize("marker,index", [(TIMING, 0), (IONIC, 1)])
def test_markers_are_independent(tmp_path, marker, index):
    path = tmp_path / "OUTCAR"
    payload = b"prefix\r\n" + b"  " + marker.encode() + b"\r\n"
    path.write_bytes(payload)
    report = diagnose_outcar(path)
    assert report.findings[index].status == "marker_found"
    assert report.findings[1-index].status == "unknown"
    assert report.findings[index].evidence[0].byte_offset == 8
    assert report.electronic_convergence == report.ionic_convergence == report.normal_termination == "unknown"
    assert path.read_bytes() == payload


@pytest.mark.parametrize("content", [b"", b"invalid\xff\x00\n", TIMING.encode(), b"quoted " + TIMING.encode() + b"\n"])
def test_incomplete_or_unrecognized_text(tmp_path, content):
    path = tmp_path / "OUTCAR"
    path.write_bytes(content)
    assert all(f.status == "unknown" for f in diagnose_outcar(path).findings)


@pytest.mark.parametrize("kind", ["missing", "directory", "permission"])
def test_read_error(tmp_path, monkeypatch, kind):
    path = tmp_path / "OUTCAR"
    if kind == "directory":
        path.mkdir()
    elif kind == "permission":
        from pathlib import Path
        def denied(*args, **kwargs):
            raise PermissionError("test denied")
        monkeypatch.setattr(Path, "open", denied)
    report = diagnose_outcar(path)
    assert report.error is not None
    assert all(f.status == "unknown" and not f.evidence for f in report.findings)


def test_bounded_tail_does_not_claim_failure(tmp_path):
    path = tmp_path / "OUTCAR"
    path.write_bytes(TIMING.encode() + b"\n" + b"x" * (TAIL_BYTES + 10))
    report = diagnose_outcar(path)
    assert report.bytes_read == TAIL_BYTES
    assert report.read_start > 0
    assert report.findings[0].status == "unknown"


def test_tail_offsets_and_latest_evidence(tmp_path):
    path = tmp_path / "OUTCAR"
    prefix = b"x" * (TAIL_BYTES + 10) + b"\n"
    line = TIMING.encode() + b"\n"
    path.write_bytes(prefix + line + line)
    report = diagnose_outcar(path)
    assert len(report.findings[0].evidence) == 1
    assert report.findings[0].evidence[0].byte_offset == len(prefix) + len(line)


def test_schema_rejects_invalid_data():
    with pytest.raises(ValidationError):
        Evidence(byte_offset=-1, text="invalid")
    with pytest.raises(ValidationError):
        Finding(rule_id="test", status="success", explanation="", sources=[])
    with pytest.raises(ValidationError):
        FileInspection(name="OUTCAR", exists="yes", readable=True, status="readable")


def test_cli_serializes_evidence(tmp_path, capsys):
    (tmp_path / "OUTCAR").write_text(TIMING + "\n" + IONIC + "\n", encoding="ascii")
    assert main([str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert all(f["status"] == "marker_found" and f["sources"] for f in report["diagnostics"]["findings"])
    assert report["calculation_status"] == "unknown"
