# Stage 5: SQLite diagnostic history

This stage adds basic storage and queries. The database uses Python's standard library sqlite3, with no server or new dependencies to install. Existing scan and Agent commands remain compatible; history is written only when --save-history is explicitly supplied.

## What is saved

Each record contains an integer ID unique within the database, the UTC save time, backend name, user question, calculation directory, run status, decision count, tool-call count, and a complete AgentRun JSON snapshot. The JSON preserves actual tool calls, arguments, observations, inspected files, evidence positions, reference sources, final answer, and errors.

The database does not separately open or copy complete calculation files, nor does it save backend configuration, API keys, or the entire environment. The question, directory path, sampled log text, and answer are retained; do not put keys in the question. History captures that run, does not update when source files later change, and does not establish scientific correctness.

The save time is when the completed run is inserted, not the VASP calculation time or Agent start time. Records currently identify the backend category mock/deepseek, without the model version, cost, or per-step duration.

completed, max_steps, and backend_error runs can all be saved. Key configuration errors occur before AgentRun is created and are therefore not stored; forced process termination or user interruption also does not guarantee a record. This version has no step-by-step checkpoints or resume support.

## File responsibilities and reading order

1. RunSummary and StoredRun in `storage/repository.py`: list summaries and complete records, respectively; complete run data reuses AgentRun.
2. RunRepository.save(): serialize the snapshot and insert it using SQL placeholders; initialize and write in one transaction, roll back on failure, and finally close the connection.
3. RunRepository.list_runs() / get(): open the database with SQLite mode=ro. Lists query summaries only, returning IDs in descending order; details validate consistency between JSON and the summary. Queries neither create a database nor run models or tools.
4. `cli.py`: parse save/query options and pass the AgentLoop result to the repository; the loop itself does not depend on SQLite.
5. `tests/test_storage.py` and `tests/test_history_cli.py`: cover record round trips, evidence and citation retention, SQL special characters, read-only queries, rollback on failure, corrupt records, and CLI compatibility.

The table is named runs. application_id identifies a project database; user_version=1 identifies the current schema. Incompatible versions or databases from other applications are rejected, without automatic migration or overwrite. Questions, paths, IDs, and limit values are SQL parameters, not interpolated into commands.

## Run offline and save

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$result = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --save-history | ConvertFrom-Json
$result | Format-List status, decision_steps, history_record
```

The first two lines locate the project and source; the third uses offline Mock to complete a diagnosis and save it; the fourth displays run status and the saved ID. The default database is data/local/diagnostics.sqlite3 relative to the current working directory. In this example it is inside the project directory and covered by the existing Git ignore rules.

Expect top-level status=completed, decision_steps=4, and history_record.status=saved, with run_id, saved_at, and database returned. Each save inserts a new record rather than overwriting the previous one.

## Query recent records and the full process

```powershell
$history = & .\.venv\Scripts\python.exe -m vasp_copilot --history --limit 5 | ConvertFrom-Json
$history.runs | Format-Table id, saved_at, backend, status, decision_steps, tool_calls

$record = & .\.venv\Scripts\python.exe -m vasp_copilot --show-run $result.history_record.run_id | ConvertFrom-Json
$record.run.answer
$record.run.state.history | ForEach-Object { $_.call.tool_name }
```

The first two lines list the latest five summaries; the last three use the previously saved ID to read the full record, answer, and tool order. The answer in this historical example was in Chinese. The database remains after closing the terminal; in a new window, set PYTHONPATH again and replace the detail command's ID with one actually present in the list, such as --show-run 1. Queries need no key and incur no API usage.

--history lists the latest 10 records by default; --limit accepts 1–100. There are currently no pagination, filtering, deletion, or import commands. --show-run reads history only and does not rerun a diagnosis.

## Specify another database

```powershell
& .\.venv\Scripts\python.exe -m vasp_copilot --history --db 'D:\projects\vasp-copilot\data\local\diagnostics.sqlite3'
```

--db works with --save-history, --history, or --show-run; saves and queries must point to the same file. Only .sqlite3, .sqlite, and .db suffixes are accepted, to avoid accidentally using a file such as OUTCAR as a database. Relative paths resolve against the current terminal directory; absolute paths are recommended when querying from another directory.

## Run online

In a terminal with the key configured, where connectivity on the current computer works with the VPN disabled, append --save-history to the previously successful online command, for example:

```powershell
$result = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --backend deepseek --question 'Inspect the file evidence, retrieve relevant reference material, and distinguish observations from inferences.' --max-steps 6 --save-history | ConvertFrom-Json
$result | Format-List status, decision_steps, history_record, error
```

Real model calls still incur provider usage. Even after a backend error, the saved run_id can show tool history completed before the error. Disabling the VPN was an observed working condition in the user's environment, not a universal network requirement.

## Output compatibility and errors

Without --save-history, existing Agent JSON gains no fields and no database is created. With the option, the CLI adds history_record; AgentRun and AgentLoop interfaces remain unchanged.

- Diagnosis completed and saved successfully: exit code 0.
- Diagnosis max_steps / backend_error, even if saved successfully: exit code remains 2.
- Save failure: retain the complete run result and answer; history_record.status=error includes a safe error type, with exit code 2. Top-level completed means only that diagnosis finished and does not establish successful storage.
- Query failure: error JSON goes to stderr, exit code 2; run_not_found means the ID does not exist.
- Database missing: FileNotFoundError; save a record first or check the --db path. Queries do not create an empty database automatically.
- StoragePathError: use an allowed database suffix.
- StorageSchemaError: the database belongs to another application or has an incompatible version; choose a new path rather than deleting the original database to hide the problem.
- OperationalError: the database may be locked or the directory unwritable; connections wait approximately 5 seconds at most for a lock, and the diagnostic answer remains in the terminal result.
- StorageRecordError / DatabaseError: the record or database is corrupt; no data is returned disguised as valid.

## Tests

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_storage.py tests/test_history_cli.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

The first command verifies the repository and CLI; the second checks the whole project. Tests use temporary directories and databases, do not read real keys or call paid APIs, and do not modify public samples.

Actual validation on 2026-10-24: 42 tests added; full regression output was `261 passed in 8.06s`. Running the CLI on the public static_silicon sample produced completed, 4 decisions, and saved ID 1. Two separate processes then listed records and read the record by ID, confirming the answer and tool order matched and the OUTCAR SHA-256 was unchanged. The demo database was in a development temporary directory and was not copied into the main project. A combined real DeepSeek run with the save option had not yet been performed; dependency-injection tests covered storage of backend errors, while online account availability still required verification on the user's computer.