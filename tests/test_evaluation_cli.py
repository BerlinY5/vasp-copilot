import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vasp_copilot.evaluation import __main__ as cli
from vasp_copilot.evaluation.runner import evaluate

FIXTURES = Path(__file__).parent / "fixtures" / "pymatgen"


def test_module_entry_point_without_key(tmp_path):
    environment = os.environ.copy()
    environment.pop("DEEPSEEK_API_KEY", None)
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    result = subprocess.run([sys.executable, "-m", "vasp_copilot.evaluation", "--fixtures", str(FIXTURES)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout)["passed"] == 16
    assert json.loads(result.stdout)["suite"] == "mock-agent-v2"


def test_json_output_is_utf8_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    report = evaluate(FIXTURES)
    unicode_note = "\u56fa\u5b9a\u79bb\u7ebf\u573a\u666f"
    report.scope += " " + unicode_note
    monkeypatch.setattr(cli, "evaluate", lambda _: report)
    output = tmp_path / "\u62a5\u544a" / "result.json"
    args = ["--fixtures", str(FIXTURES), "--output", str(output)]
    assert cli.main(args) == 0
    saved = output.read_bytes()
    assert json.loads(saved.decode("utf-8")) == json.loads(capsys.readouterr().out)
    assert "fixed offline scenarios" in saved.decode("utf-8")
    assert unicode_note.encode("utf-8") in saved
    assert cli.main(args) == 2
    error = json.loads(capsys.readouterr().err)["error"]
    assert error == {"kind": "evaluation_output_error", "message": "FileExistsError"}
    assert output.read_bytes() == saved


def test_missing_fixtures_do_not_create_report(tmp_path, capsys):
    output = tmp_path / "result.json"
    assert cli.main(["--fixtures", str(tmp_path), "--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["kind"] == "fixture_error"
    assert not output.exists()


def test_invalid_suffix_does_not_run_or_touch_file(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Should reject arguments first")
    monkeypatch.setattr(cli, "evaluate", forbidden)
    output = tmp_path / "OUTCAR"
    output.write_bytes(b"original")
    with pytest.raises(SystemExit) as error:
        cli.main(["--output", str(output)])
    assert error.value.code == 2 and output.read_bytes() == b"original"


def test_failed_checks_return_one_and_can_be_saved(tmp_path, monkeypatch, capsys):
    report = evaluate(FIXTURES)
    report.cases[0].checks[0].passed = False
    report.cases[0].status = "failed"
    report.status, report.passed, report.failed = "failed", 15, 1
    monkeypatch.setattr(cli, "evaluate", lambda _: report)
    output = tmp_path / "failed.json"
    assert cli.main(["--output", str(output)]) == 1
    assert json.loads(capsys.readouterr().out)["failed"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "failed"


def test_partial_output_is_removed_on_write_error(tmp_path, monkeypatch, capsys):
    output = tmp_path / "result.json"
    original = Path.open

    class BrokenWriter:
        def __enter__(self):
            self.handle = original(output, "x", encoding="utf-8")
            return self
        def write(self, value):
            self.handle.write("partial")
            raise OSError("private details")
        def __exit__(self, *args):
            self.handle.close()

    def open_file(path, *args, **kwargs):
        return BrokenWriter() if path == output and args and args[0] == "x" else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    assert cli.main(["--fixtures", str(FIXTURES), "--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["message"] == "OSError"
    assert not output.exists()
