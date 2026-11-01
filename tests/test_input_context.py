import json
from pathlib import Path

import pytest

from vasp_copilot.cli import main
from vasp_copilot.input_context import MAX_INCAR_BYTES, inspect_incar


def inspect_text(tmp_path, text):
    path = tmp_path / "INCAR"
    path.write_text(text, encoding="utf-8")
    return inspect_incar(path)


@pytest.mark.parametrize("ibrion,nsw,expected", [
    (-1, 0, "static"), (-1, 10, "static"), (2, 0, "static"),
    (0, 10, "molecular_dynamics"),
    (1, 10, "relaxation"), (2, 10, "relaxation"), (3, 10, "relaxation"),
])
def test_explicit_modes(tmp_path, ibrion, nsw, expected):
    report = inspect_text(tmp_path, f"IBRION={ibrion}\nNSW={nsw}")
    assert report.calculation_type == expected
    assert not report.issues


def test_comments_case_semicolons_bom_and_evidence(tmp_path):
    report = inspect_text(tmp_path, "\ufeff# example\n  ibrion = +2 ; nsw = 20 ! comment\nENCUT=400")
    assert report.calculation_type == "relaxation"
    assert [(p.name, p.value, p.line_number) for p in report.parameters] == [("IBRION", 2, 2), ("NSW", 20, 2)]
    assert report.parameters[0].text == "  ibrion = +2 ; nsw = 20 ! comment"


@pytest.mark.parametrize("text", [
    "", "NSW=10", "IBRION=2", "IBRION=2; NSW=-1", "IBRION=0; NSW=0",
    "IBRION=6; NSW=10", "IBRION=2.0; NSW=10", "IBRION=2; NSW=1e2",
    "IBRION=2; NSW=10; IBRION=0", "IBRION=2; NSW=10; NSW=10",
    "IBRION=2; NSW=10\nNSW broken", "IBRION=2; NSW=10\\\n0",
    'SYSTEM="a; b"\nIBRION=2; NSW=10', "IBRION=2; NSW=10\x00",
])
def test_ambiguous_input_is_unknown(tmp_path, text):
    report = inspect_text(tmp_path, text)
    assert report.calculation_type == "unknown"
    assert report.issues


def test_oversize_is_not_partially_classified(tmp_path):
    report = inspect_text(tmp_path, "IBRION=2;NSW=10\n#" + "x" * MAX_INCAR_BYTES)
    assert report.calculation_type == "unknown"
    assert report.parameters == []
    assert "64 KiB" in report.issues[0]


def test_comment_contents_do_not_change_mode(tmp_path):
    report = inspect_text(tmp_path, 'IBRION=2; NSW=10 # "NSW=0"; IBRION=0\\')
    assert report.calculation_type == "relaxation"


@pytest.mark.parametrize("kind", ["missing", "directory", "encoding", "permission"])
def test_file_errors(tmp_path, monkeypatch, kind):
    path = tmp_path / "INCAR"
    if kind == "directory":
        path.mkdir()
    elif kind == "encoding":
        path.write_bytes(b"\xffIBRION=2;NSW=10")
    elif kind == "permission":
        def denied(*args, **kwargs):
            raise PermissionError("test denied")
        monkeypatch.setattr(Path, "open", denied)
    report = inspect_incar(path)
    assert report.error is not None
    assert report.calculation_type == "unknown"


def test_cli_input_intent_does_not_assert_convergence(tmp_path, capsys):
    payload = b"IBRION=2;NSW=10\n"
    (tmp_path / "INCAR").write_bytes(payload)
    assert main([str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["input_context"]["calculation_type"] == "relaxation"
    assert report["diagnostics"]["ionic_convergence"] == "unknown"
    assert report["calculation_status"] == "unknown"
    assert (tmp_path / "INCAR").read_bytes() == payload
