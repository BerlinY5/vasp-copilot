import json
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.mock import MockBackend
from vasp_copilot.storage.repository import RunRepository, StoragePathError, StorageRecordError, StorageSchemaError
from vasp_copilot.tools.file_inspection import create_registry


def sample_run(tmp_path, question="检查计算", max_steps=6):
    directory = tmp_path / "calculation"
    directory.mkdir(exist_ok=True)
    (directory / "OUTCAR").write_text("Iteration 1( 3)\naborting loop because EDIFF is reached\n", encoding="ascii")
    return AgentLoop(MockBackend(), create_registry(directory), max_steps).run(question, str(directory))


def test_snapshot_roundtrip_keeps_evidence_and_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-not-to-persist")
    run = sample_run(tmp_path)
    path = tmp_path / "records" / "history.sqlite3"
    saved = RunRepository(path).save(run, "mock")
    assert datetime.fromisoformat(saved.saved_at).utcoffset().total_seconds() == 0
    # A fresh repository instance reads the committed state; no process memory cache.
    record = RunRepository(path).get(saved.id)
    assert record.summary == saved and record.run == run
    assert record.run.state.history[1].observation.data["last_iteration"]["markers"]
    assert record.run.state.history[2].observation.data["hits"][0]["source"].startswith("https://")
    assert b"secret-not-to-persist" not in path.read_bytes()
    run.state.history.clear()
    assert len(RunRepository(path).get(saved.id).run.state.history) == 3


def test_list_is_newest_first_bounded_and_excludes_full_payload(tmp_path):
    repository = RunRepository(tmp_path / "history.sqlite3")
    run = sample_run(tmp_path)
    saved = [repository.save(run, "mock") for _ in range(3)]
    rows = repository.list_runs(limit=2)
    assert [row.id for row in rows] == [saved[2].id, saved[1].id]
    assert all("run_json" not in row.model_dump() and "answer" not in row.model_dump() for row in rows)


@pytest.mark.parametrize("status", ["max_steps", "backend_error"])
def test_incomplete_runs_are_saved_with_prior_history(tmp_path, status):
    run = sample_run(tmp_path, max_steps=1)
    if status == "backend_error":
        run.status = status
        run.error.kind = status
        run.error.message = "DeepSeekProtocolError"
    repository = RunRepository(tmp_path / "history.sqlite3")
    saved = repository.save(run, "deepseek")
    loaded = repository.get(saved.id)
    assert loaded.run.status == status and loaded.run.answer is None
    assert loaded.run.state.history == run.state.history
    assert loaded.summary.backend == "deepseek"


def test_sql_special_characters_are_data_not_commands(tmp_path):
    question = "中文 '); DROP TABLE runs; -- \" \\"
    run = sample_run(tmp_path, question=question)
    repository = RunRepository(tmp_path / "history.sqlite3")
    saved = repository.save(run, "mock")
    assert repository.get(saved.id).run.state.question == question
    assert len(repository.list_runs()) == 1


def test_read_only_queries_do_not_create_missing_database(tmp_path):
    path = tmp_path / "absent" / "history.sqlite3"
    repository = RunRepository(path)
    with pytest.raises(FileNotFoundError):
        repository.list_runs()
    with pytest.raises(FileNotFoundError):
        repository.get(1)
    assert not path.parent.exists()


def test_read_only_queries_preserve_database_and_handle_encoded_paths(tmp_path):
    path = tmp_path / "history # 中文.sqlite3"
    repository = RunRepository(path)
    saved = repository.save(sample_run(tmp_path), "mock")
    before = path.read_bytes()
    assert repository.list_runs()[0].id == saved.id
    assert repository.get(saved.id) is not None
    assert repository.get(saved.id + 100) is None
    assert path.read_bytes() == before


@pytest.mark.parametrize("limit", [0, 101, True, "2"])
def test_invalid_list_limit_does_not_create_database(tmp_path, limit):
    repository = RunRepository(tmp_path / "history.sqlite3")
    with pytest.raises(ValueError):
        repository.list_runs(limit)
    assert not repository.path.exists()


@pytest.mark.parametrize("run_id", [0, -1, True, "1 OR 1=1"])
def test_invalid_id_does_not_access_database(tmp_path, run_id):
    with pytest.raises(ValueError):
        RunRepository(tmp_path / "history.sqlite3").get(run_id)


def test_unrelated_database_is_not_modified(tmp_path):
    path = tmp_path / "unrelated.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE private_data (value TEXT)")
        connection.execute("INSERT INTO private_data VALUES ('original')")
        connection.commit()
    before = path.read_bytes()
    with pytest.raises(StorageSchemaError):
        RunRepository(path).save(sample_run(tmp_path), "mock")
    assert path.read_bytes() == before


def test_future_schema_is_rejected_without_changes(tmp_path):
    repository = RunRepository(tmp_path / "future.sqlite3")
    run = sample_run(tmp_path)
    repository.save(run, "mock")
    with closing(sqlite3.connect(repository.path)) as connection:
        connection.execute("PRAGMA user_version=99")
    before = repository.path.read_bytes()
    with pytest.raises(StorageSchemaError):
        repository.list_runs()
    with pytest.raises(StorageSchemaError):
        repository.save(run, "mock")
    assert repository.path.read_bytes() == before


def test_failed_insert_rolls_back_without_losing_existing_run(tmp_path):
    repository = RunRepository(tmp_path / "history.sqlite3")
    run = sample_run(tmp_path)
    first = repository.save(run, "mock")
    with closing(sqlite3.connect(repository.path)) as connection:
        connection.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON runs BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repository.save(run, "mock")
    assert [row.id for row in repository.list_runs()] == [first.id]
    assert repository.get(first.id).run == run


@pytest.mark.parametrize("tamper", ["bad-json", "invalid-shape", "summary-mismatch"])
def test_corrupt_record_is_not_returned_as_valid(tmp_path, tamper):
    repository = RunRepository(tmp_path / "history.sqlite3")
    run = sample_run(tmp_path)
    saved = repository.save(run, "mock")
    if tamper == "bad-json":
        serialized = "private invalid json"
    elif tamper == "invalid-shape":
        serialized = json.dumps({"private": "bad shape"})
    else:
        run.state.question = "changed after save"
        serialized = run.model_dump_json()
    with closing(sqlite3.connect(repository.path)) as connection:
        connection.execute("UPDATE runs SET run_json=? WHERE id=?", (serialized, saved.id))
        connection.commit()
    with pytest.raises(StorageRecordError) as caught:
        repository.get(saved.id)
    assert "private" not in str(caught.value)


def test_non_database_file_remains_intact(tmp_path):
    path = tmp_path / "not-a-database.sqlite3"
    path.write_bytes(b"original content")
    with pytest.raises(sqlite3.DatabaseError):
        RunRepository(path).save(sample_run(tmp_path), "mock")
    assert path.read_bytes() == b"original content"


def test_empty_outcar_cannot_become_a_history_database(tmp_path):
    path = tmp_path / "OUTCAR"
    path.write_bytes(b"")
    with pytest.raises(StoragePathError):
        RunRepository(path)
    assert path.read_bytes() == b""
