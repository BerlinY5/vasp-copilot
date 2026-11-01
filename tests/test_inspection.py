import json
from pathlib import Path

import pytest

from vasp_copilot.cli import main
from vasp_copilot.inspection import VASP_FILES, inspect_file, scan_directory


def test_missing_files(tmp_path):
    report = scan_directory(tmp_path)
    assert len(report["files"]) == 8
    assert all(f["status"] == "missing" for f in report["files"])
    assert report["calculation_status"] == "unknown"


def test_present_files_are_unchanged(tmp_path):
    for name in VASP_FILES:
        (tmp_path / name).write_bytes(b"example\x00\xff")
    report = scan_directory(tmp_path)
    assert all(f["exists"] and f["readable"] for f in report["files"])
    assert all((tmp_path / name).read_bytes() == b"example\x00\xff" for name in VASP_FILES)


def test_empty_file(tmp_path):
    path = tmp_path / "OUTCAR"
    path.touch()
    assert inspect_file(path)["status"] == "readable"


def test_directory_is_not_file(tmp_path):
    (tmp_path / "INCAR").mkdir()
    result = inspect_file(tmp_path / "INCAR")
    assert result["exists"] is True
    assert result["readable"] is False
    assert result["status"] == "not_file"


def test_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "INCAR"
    path.touch()
    def denied(*args, **kwargs):
        raise PermissionError("test denied")
    monkeypatch.setattr(Path, "open", denied)
    result = inspect_file(path)
    assert result["exists"] is True
    assert result["readable"] is False
    assert "PermissionError" in result["error"]


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_cli_invalid_directory(tmp_path, capsys, kind):
    path = tmp_path / "target"
    if kind == "file":
        path.touch()
    assert main([str(path)]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_cli_json(tmp_path, capsys):
    (tmp_path / "INCAR").write_text("ENCUT = 400", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files"][0]["status"] == "readable"
    assert report["files"][1]["status"] == "missing"
