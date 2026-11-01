import json
import sqlite3

import pytest

from vasp_copilot.cli import main
from vasp_copilot.storage.repository import RunRepository


def test_save_list_and_show_work_without_api_key(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    directory = tmp_path / "calculation"
    directory.mkdir()
    (directory / "OUTCAR").write_text("Iteration 1( 3)\naborting loop because EDIFF is reached\n", encoding="ascii")
    before = (directory / "OUTCAR").read_bytes()
    assert main([str(directory), "--agent", "--save-history"]) == 0
    result = json.loads(capsys.readouterr().out)
    saved = result.pop("history_record")
    assert saved["status"] == "saved"
    assert main(["--history", "--limit", "1"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["runs"][0]["id"] == saved["run_id"]
    assert main(["--show-run", str(saved["run_id"])]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["run"] == result
    assert (directory / "OUTCAR").read_bytes() == before


def test_history_queries_do_not_invoke_backend_or_tools(tmp_path, monkeypatch, capsys):
    from vasp_copilot import cli
    database = tmp_path / "history.sqlite3"
    assert main([str(tmp_path), "--agent", "--save-history", "--db", str(database)]) == 0
    saved = json.loads(capsys.readouterr().out)["history_record"]
    def forbidden(*args, **kwargs):
        raise AssertionError("Query must not initialize models or file tools")
    monkeypatch.setattr(cli, "MockBackend", forbidden)
    monkeypatch.setattr(cli, "DeepSeekBackend", forbidden)
    monkeypatch.setattr(cli, "create_registry", forbidden)
    assert main(["--history", "--db", str(database)]) == 0
    capsys.readouterr()
    assert main(["--show-run", str(saved["run_id"]), "--db", str(database)]) == 0


def test_default_agent_does_not_create_history(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main([str(tmp_path), "--agent"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "history_record" not in result
    assert not (tmp_path / "data").exists()


def test_step_limit_run_is_saved_with_original_exit_code(tmp_path, capsys):
    database = tmp_path / "history.sqlite3"
    assert main([str(tmp_path), "--agent", "--max-steps", "1", "--save-history", "--db", str(database)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "max_steps" and result["history_record"]["status"] == "saved"
    saved = RunRepository(database).get(result["history_record"]["run_id"])
    assert len(saved.run.state.history) == 1


def test_backend_failure_is_saved(tmp_path, monkeypatch, capsys):
    from vasp_copilot import cli
    class BrokenBackend:
        def decide(self, state, tools):
            raise RuntimeError("private detail")
    monkeypatch.setattr(cli, "MockBackend", BrokenBackend)
    database = tmp_path / "history.sqlite3"
    assert main([str(tmp_path), "--agent", "--save-history", "--db", str(database)]) == 2
    result = json.loads(capsys.readouterr().out)
    saved = RunRepository(database).get(result["history_record"]["run_id"])
    assert saved.run.status == "backend_error" and "private detail" not in saved.model_dump_json()


def test_save_failure_preserves_completed_answer_and_reports_it(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("private database detail")
    monkeypatch.setattr(RunRepository, "save", fail)
    assert main([str(tmp_path), "--agent", "--save-history", "--db", str(tmp_path / "history.sqlite3")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed" and result["answer"]
    assert result["history_record"]["status"] == "error"
    assert result["history_record"]["error"]["message"] == "OperationalError"
    assert "private database detail" not in json.dumps(result)


def test_missing_database_and_unknown_id_are_clear_errors(tmp_path, capsys):
    database = tmp_path / "history.sqlite3"
    assert main(["--history", "--db", str(database)]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["message"] == "FileNotFoundError"
    assert not database.exists()
    assert main([str(tmp_path), "--agent", "--save-history", "--db", str(database)]) == 0
    capsys.readouterr()
    assert main(["--show-run", "999", "--db", str(database)]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["kind"] == "run_not_found"


@pytest.mark.parametrize("args", [
    [], ["--save-history"], [".", "--save-history"], ["--history", "--agent"],
    [".", "--history"], ["--history", "--backend", "deepseek"],
    ["--history", "--limit", "0"], ["--history", "--limit", "101"],
    ["--show-run", "0"], ["--show-run", "1", "--limit", "2"],
    [".", "--db", "unused.sqlite3"], ["--history", "--save-history"],
])
def test_invalid_option_combinations_do_not_create_files(tmp_path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as caught:
        main(args)
    assert caught.value.code == 2
    assert list(tmp_path.iterdir()) == []
