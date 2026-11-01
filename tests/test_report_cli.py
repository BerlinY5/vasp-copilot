import json

import pytest

from vasp_copilot.cli import main


def save_example(tmp_path, capsys):
    directory = tmp_path / "calculation"
    directory.mkdir()
    (directory / "OUTCAR").write_text("Iteration 1( 3)\naborting loop because EDIFF is reached\n", encoding="ascii")
    database = tmp_path / "history.sqlite3"
    assert main([str(directory), "--agent", "--save-history", "--db", str(database)]) == 0
    result = json.loads(capsys.readouterr().out)
    return database, result["history_record"]["run_id"]


def test_export_from_database_does_not_execute_models_or_tools(tmp_path, monkeypatch, capsys):
    from vasp_copilot import cli
    monkeypatch.chdir(tmp_path)
    database, run_id = save_example(tmp_path, capsys)
    before = database.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError("Export must only read saved records")
    monkeypatch.setattr(cli, "MockBackend", forbidden)
    monkeypatch.setattr(cli, "DeepSeekBackend", forbidden)
    monkeypatch.setattr(cli, "create_registry", forbidden)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert main(["--export-run", str(run_id), "--db", str(database)]) == 0
    result = json.loads(capsys.readouterr().out)
    target = tmp_path / "reports" / "generated" / f"run-{run_id}.md"
    assert result == {"status": "exported", "run_id": run_id, "path": str(target.resolve())}
    assert "参考资料" in target.read_text(encoding="utf-8")
    assert database.read_bytes() == before


def test_export_custom_path_and_existing_file_error(tmp_path, capsys):
    database, run_id = save_example(tmp_path, capsys)
    output = tmp_path / "custom.md"
    args = ["--export-run", str(run_id), "--db", str(database), "--output", str(output)]
    assert main(args) == 0
    capsys.readouterr()
    before = output.read_bytes()
    assert main(args) == 2
    error = json.loads(capsys.readouterr().err)["error"]
    assert error == {"kind": "report_error", "message": "FileExistsError"}
    assert output.read_bytes() == before


def test_missing_record_does_not_create_output(tmp_path, capsys):
    database, _ = save_example(tmp_path, capsys)
    output = tmp_path / "absent" / "report.md"
    assert main(["--export-run", "999", "--db", str(database), "--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["kind"] == "run_not_found"
    assert not output.parent.exists()


def test_bad_output_suffix_does_not_modify_input_file(tmp_path, capsys):
    database, run_id = save_example(tmp_path, capsys)
    target = tmp_path / "calculation" / "OUTCAR"
    before = target.read_bytes()
    assert main(["--export-run", str(run_id), "--db", str(database), "--output", str(target)]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["message"] == "ReportPathError"
    assert target.read_bytes() == before


@pytest.mark.parametrize("args", [
    ["--export-run", "0"], ["--export-run", "-1"], ["--export-run", "1", "--history"],
    ["--export-run", "1", "--show-run", "1"], ["--export-run", "1", "--save-history"],
    ["--export-run", "1", "--agent"], [".", "--export-run", "1"],
    ["--export-run", "1", "--backend", "deepseek"], ["--export-run", "1", "--limit", "5"],
    ["--history", "--output", "report.md"], [".", "--agent", "--output", "report.md"],
])
def test_export_option_validation_does_not_create_files(tmp_path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as caught:
        main(args)
    assert caught.value.code == 2
    assert list(tmp_path.iterdir()) == []
