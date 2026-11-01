# Stage 5: Export Markdown reports from history

This stage formats diagnostic records in SQLite as readable Markdown files. Export does not rerun the Agent, access the model service, reread the calculation directory or knowledge base, or add dependencies. Old evidence, answers, and references appear exactly as saved.

## Report structure

1. Record ID, UTC save time, backend, Agent status, and call counts.
2. User question and the directory selected at that time.
3. Each tool step's arguments, execution status, and observations: file inventory, OUTCAR sampling range, original marker text and byte positions, iteration numbers, raw INCAR lines, input/output parameter comparison, and so on.
4. Knowledge entries, source URLs, local document line numbers, and saved excerpts, explicitly labeled as general reference material.
5. The original backend answer, explicitly labeled “not automatically fact-checked,” without rewriting or correction.
6. Run errors, issues reported by tools, and interpretation boundaries.
7. The complete saved snapshot JSON, to check whether the formatted view omits information.

completed only means the Agent produced an answer and cannot be substituted for VASP success. unknown remains unknown; missing files or absent markers do not automatically imply failure. Reports provide no new scientific assurance for model answers.

Table text is escaped; raw logs, reference excerpts, and backend answers appear in text code blocks. Code fences automatically grow to accommodate backticks in their contents, preventing original text from accidentally changing report structure. Source URLs are preserved as text; pages are not loaded automatically. Before sharing a report, remember it contains the question, directory paths, and saved log excerpts.

## Added files and reading order

- `src/vasp_copilot/reports/generator.py`: render_markdown(record) is a pure formatting function accepting only StoredRun; _observation() selects a dedicated view by tool name and reuses existing Pydantic models; export_markdown() creates a new UTF-8 Markdown file.
- `src/vasp_copilot/reports/__init__.py`: report package entry point.
- `src/vasp_copilot/cli.py`: adds --export-run and --output; reuses the history repository's read-only get() without passing through AgentLoop.
- `tests/test_reports.py`: evidence, sources, unknown states, original snapshots, escaping, duplicate writes, and cleanup on failure.
- `tests/test_report_cli.py`: CLI export, mutually exclusive options, unchanged databases, unknown IDs, and output-path protection.

Observations from old records or custom tools may not fit current dedicated views. The report then explicitly explains that the summary cannot be generated and shows raw JSON rather than guessing missing fields. The repository still rejects corrupt databases or invalid AgentRun data.

## Export existing history

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')

$history = & .\.venv\Scripts\python.exe -m vasp_copilot --history --limit 5 | ConvertFrom-Json
$history.runs | Format-Table id, backend, status, saved_at

& .\.venv\Scripts\python.exe -m vasp_copilot --export-run 1
```

The first two lines locate the project and source; the middle two display exportable IDs; the last exports ID 1. Replace it with an ID actually present in the list.

The default destination is reports/generated/run-1.md relative to the current working directory. Here it is inside the project directory and covered by existing Git ignore rules. Success returns status=exported, run_id, and an absolute path, with exit code 0. exported means the report was written; records whose saved Agent status is backend_error or max_steps can also be exported normally.

## Complete offline demo with no existing history

```powershell
$saved = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --save-history | ConvertFrom-Json
$saved.history_record
& .\.venv\Scripts\python.exe -m vasp_copilot --export-run $saved.history_record.run_id
```

First run the preceding section's two project-location and PYTHONPATH lines. Then the first line above runs offline Mock and saves; the second confirms status=saved; the third exports the returned ID. No API key is required. If saving fails, do not continue with an empty run_id.

## Custom paths

```powershell
& .\.venv\Scripts\python.exe -m vasp_copilot --export-run 1 --db 'D:\projects\vasp-copilot\data\local\diagnostics.sqlite3' --output 'D:\projects\vasp-copilot\reports\generated\my-report.md'
```

--db selects an existing database; --output specifies a new .md file. Export creates necessary parent directories but does not overwrite an existing file; use a different filename for another export. There is no --force option, to avoid overwriting manually edited reports. Only the .md suffix is accepted, preventing OUTCAR or a database from being mistaken for an output file.

## Errors and limits

- run_not_found: the ID does not exist; check --history first.
- storage_error / FileNotFoundError: the database is missing or the path is wrong; neither queries nor exports create an empty database.
- report_error / FileExistsError: the destination already exists and remains unchanged; choose a new --output.
- report_error / ReportPathError: the output is not .md.
- report_error / PermissionError or another OSError: unwritable directory, disk error, etc. For handled write exceptions, remove the incomplete file created by this export and retain the exception. Unhandled exits such as power loss cannot guarantee cleanup.
- All failures use exit code 2 and write error JSON to stderr. The original database remains read-only.

Currently only Markdown is exported, not PDF, Word, or web pages. Export does not reason again, check the current state of source websites, or resume a failed Agent. Questions, paths, and answers in historical records are not automatically redacted.

## Validation

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_reports.py tests/test_report_cli.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

Actual results on 2026-10-24: 29 tests added; full regression was `290 passed in 10.31s`. A 16089-byte Markdown sample was also exported from the public static_silicon record saved in the previous stage, checking OUTCAR byte offsets, unknown states, reference sources, original backend text, and the complete snapshot. The SQLite SHA-256 was identical before and after export. No real model calls were made and no calculation files were changed.