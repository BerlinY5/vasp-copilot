# Agent architecture: Tool registration, decision loop, knowledge retrieval, history, and reports

The project has a tool layer, replaceable decision interface, Mock loop, DeepSeek adapter, and local knowledge retrieval. The original CLI scans directories directly by default; --agent defaults to offline operation, and only --backend deepseek accesses the model service. On 2026-10-24 the user returned an online answer with completed and 4 decisions; complete tool history was not provided, and manual review found answer-quality issues. See evaluation.md.

## Call path

```text
create_registry()
  → Register scan_directory, inspect_directory, diagnose_outcar, inspect_incar, inspect_oszicar, compare_outputs, search_knowledge

registry.execute("scan_directory", {"directory": "..."})
  → Find ToolDefinition in the dictionary
  → Validate arguments with ScanDirectoryArgs
  → Call scan(args)
  → Reuse inspection.scan_directory()
  → Validate output with ScanReport and convert to JSON data
  → ToolResult returns success/data or error/error
```

## File responsibilities

- agent/protocol.py: ToolResult is an Observation. status=success requires data without error; status=error requires error without data. ToolCall / ToolBatch / Finish are decisions discriminated by type; ToolBatch contains 2–8 ToolCall objects. ToolEvent stores a call and observation; AgentState stores the question, directory, and history; AgentRun stores termination status and final answer.
- agent/tool_registry.py: ToolDefinition uses a dataclass to store the name, description, two model types, and function reference. ToolRegistry looks up tools in a dictionary and registers them through decorators. describe() emits independent JSON Schema, not yet bound to a particular model API format.
- tools/file_inspection.py: defines ScanDirectoryArgs and DirectoryInventory, adapting existing reading functions into six file tools. inspect_directory probes files only, without parsing a complete report in advance; fine-grained parsers let Mock choose from results. create_registry() returns a separate instance each time.
- tests/test_tool_registry.py: uses a test-only double tool to verify the common mechanism, then a real scan adapter for integration. double is never registered in production instances.

## Why use decorators

`@registry.register(...)` first produces a decorator, then passes the following function to it. The decorator stores the function and argument model in a dictionary and returns the original function. Registration only records the function; it does not scan files immediately.

All tool functions receive one validated model object. execute() needs no tool-specific if/else branches; adding a tool only requires models, a function, and registration.

## Return semantics

| error.kind | Meaning | What the caller should check |
| --- | --- | --- |
| unknown_tool | Name not registered | Tool names in describe() |
| invalid_arguments | Arguments failed model validation | Missing fields, types, extra fields |
| execution_error | Tool raised an ordinary exception | Exception type in the message; for example, check the directory for FileNotFoundError |
| invalid_result | Wrong return shape or cannot convert to JSON | Whether the implementation follows the result model |

Success means the tool executed and produced valid data, not that VASP succeeded. An existing directory with no OUTCAR may still return tool success, with missing evidence explained inside data.

Argument models inherit Schema, validate strictly, and forbid extra fields. Validation errors omit raw input values; execution exceptions report only their types to avoid directly forwarding arbitrary internal exception text to subsequent models. Developers can use logging to see names, starts, completions, and error categories, without parameter values or complete reports. BaseException subclasses such as KeyboardInterrupt are not swallowed.

## PowerShell trial run

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& .\.venv\Scripts\python.exe -c "from vasp_copilot.tools.file_inspection import create_registry; r=create_registry(); print([t['name'] for t in r.describe()]); result=r.execute('scan_directory', {'directory': '.'}); print(result.status); print(result.data['calculation_status'])"
& .\.venv\Scripts\python.exe -m pytest tests/test_tool_registry.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

The first three lines change directory, set the source search path, and create a registry to scan the project root. Expected output is a list of seven tool names, `success`, and `unknown`. Scanning can complete even without VASP data in the project root. The last two lines run tool-layer and full tests. If the package cannot be found, check PYTHONPATH; for execution_error, check directory existence and permissions.

## Current boundaries and next steps

Only explicitly registered synchronous Python functions execute; model-generated code and arbitrary shell commands do not. The registry is not a security sandbox; current tools use the local process's read permissions. There is no asynchronous execution or enforced timeout control yet; the CLI explicitly enables persistent history, described below.

## Mock loop

```text
AgentLoop.run(question, directory)
  → Create AgentState
  → backend.decide(deep-copied state, tool descriptions)
  → Pydantic TypeAdapter validates ToolCall / ToolBatch / Finish
      ToolCall → registry.execute → append ToolEvent → decide again
      ToolBatch → execute each call sequentially and append ToolEvent → decide again
      Finish → completed + answer
  → Decision budget exhausted: max_steps; backend exception or invalid decision: backend_error
```

The Protocol in backend.py specifies the decide() signature without requiring inheritance from a concrete class. The loop depends only on this interface and ToolRegistry. MockBackend decides using history[-1].observation; the loop itself knows neither VASP filenames nor which tool should be called.

Actual Mock branches:

- No history: inspect_directory.
- File inspection completed: choose scan_directory if OUTCAR and OSZICAR are both readable; otherwise diagnose_outcar for readable OUTCAR, inspect_oszicar for readable OSZICAR, inspect_incar for readable INCAR, or explain insufficient evidence.
- OUTCAR parse result returned: choose EDIFF, EDIFFG, or OUTCAR topics based on electronic messages and the ionic stopping marker; call search_knowledge before assembling a conservative explanation. Actual text, offsets, and errors remain in history. The INCAR branch directly explains input intent.
- Tool error: explain and finish; parser-internal error is checked too, avoiding confusion between tool success and successful file parsing.

question is saved without natural-language interpretation. Tool definitions are passed to the backend, but Mock uses predefined tool names. It is an offline acceptance test backend and does not impersonate an LLM.

Decision steps include final; the default limit is 6 and maximum 100. Tool errors can become Observations for backend correction; a test backend fixes arguments once after invalid_arguments, while default Mock does not retry. Backend exceptions, invalid type, or incorrect fields stop the loop without executing the invalid decision. KeyboardInterrupt remains interruptible. Deep copying protects state records; it does not sandbox arbitrary Python backends.

DeepSeek online acceptance can declare pre-completion tool requirements with --require-knowledge. The CLI passes search_knowledge as AgentLoop.required_tools; before accepting final, the loop checks actual successful tool history, appending CompletionFeedback and continuing if unmet. A rejected final still consumes budget without generating a fake tool event, so ToolEvent.step may contain gaps. Requirements and correction records live in AgentState, defaulting to empty lists in old snapshots. DeepSeek requests carry these requirements, actual retrieval counts, and current correction feedback; zero-hit retrieval permits completion but must be described honestly. See online-validation.md.

Core acceptance in tests/test_agent_loop.py uses the same Mock and question with two directories, producing inspect_directory → diagnose_outcar → search_knowledge and inspect_directory → inspect_incar respectively. It also verifies empty directories, files disappearing during reading, error recovery, step limits, history isolation, and CLI exit codes.

## Run-stage notifications

agent/progress.py defines frozen ProgressEvent and a progress callback type containing only stage, decision number/limit, same-round tool index, registered tool name, and fixed status. It holds no AgentState, question, arguments, or Observation. StderrProgressReporter receives the stderr stream supplied by the CLI, computes elapsed time with monotonic, and flushes every notification immediately.

AgentLoop's optional on_progress notifies observers at decision start, before/after tool execution, when a final answer is deferred, and before normally returning a run result. Ordinary notification exceptions produce only a fixed warning without altering diagnosis; KeyboardInterrupt still propagates. Progress does not enter model requests, database snapshots, or reports, affect decision budgets, or provide retries, periodic heartbeats, or enforced timeouts. During backend waiting, the next notification appears only after return.

cli.py creates a display object only for this Agent run with --progress, without installing a global logging handler. Progress is off by default and rejected for history queries. Registry logs also use a fixed placeholder for unknown tool names, preventing arbitrary model-generated names from entering logs; unknown names remain tool errors in diagnostic history through the original mechanism.

## DeepSeek adapter

config.py reads the key, model name, and timeout from the process environment without loading the entire environment or automatically loading private files. agent/deepseek.py implements the same decide() interface: convert state history into messages, tool definitions into functions, get a response through an injectable HTTP transport, and convert it into ToolCall, ToolBatch, or Finish.

ToolCall adds optional call_id and assistant_content. Mock does not depend on them; DeepSeek must preserve them to replay real tool calls and corresponding Observations. The loop itself is independent of DeepSeek request format, and tests can replace transport without network access.

One tool batch occupies one decision; ToolEvent.step is shared within the batch, batch_index starts at 1, and batch_size is its full size. Old records missing batch fields default to 1/1 without database migration. DeepSeek groups replay by step: one assistant message carries all native calls, followed by each tool result. Missing, out-of-order, or duplicate-ID batches are rejected before sending. Reports show same-round call indices.

Batch structure and JSON validation complete before execution. The registry still handles business arguments and directory restrictions individually; one tool error neither rolls back completed observations nor blocks later items. Same-batch tools run serially without atomic snapshots. A round has at most 8 calls; even the last permitted decision executes its complete valid batch, returning max_steps if no budget remains for a final answer. Mock still returns only single tool calls.

The CLI creates a directory-bound ToolRegistry. Directory checks apply before function execution and are shared by all six file tools, independent of model obedience. Prompts require evidence citations and observation/inference separation, but model natural-language conclusions have no automatic fact-checking yet.

Tool descriptions state scope and overlap: compare_outputs is for standalone step comparison; scan_directory returns file inventory, input settings, an OUTCAR parameter summary, observations from both logs, and step comparison. diagnose_outcar does not extract prefix IBRION/NSW; inspect_directory probes files only. Discussing mode parameters requires scan_directory.output_context; a step-number-only question need not add mode discussion. Prompts encourage reusing observations and filling gaps with tools, without imposing a fixed order or blocking duplicate reads at run time. Tool choice and natural-language evidence boundaries still require online acceptance.

See deepseek.md for configuration and online validation steps. Tests need no key; real integration requires the user to configure DEEPSEEK_API_KEY locally. See online-validation.md for latest online findings and targeted regression results.

## Local knowledge tool

tools/knowledge_search.py registers retrieval using the same argument validation, Observation, and history mechanisms, without changes to AgentLoop. rag/retriever.py keyword-matches bundled Markdown notes and returns body text, local line numbers, official sources, and evidence_type=reference. Retrieval takes no directory argument, reads no user calculation files, and makes no network requests.

Mock selects topics from file observations and retains file evidence if retrieval fails. DeepSeek prompts explicitly require separate citations for file evidence and reference material, but natural-language conclusions still lack automatic fact-checking. See [Local retrieval](rag.md) for material format, module reading order, and acceptance commands.

## SQLite persistence

```text
CLI --agent [--save-history]
  → AgentLoop.run()
  → AgentRun (success, budget exhausted, or backend error)
  → If explicitly saved: RunRepository.save(run, backend)
  → Original run result + history_record storage status

CLI --history / --show-run ID
  → RunRepository queries SQLite with mode=ro
  → Summary list / validated AgentRun snapshot
```

storage/repository.py defines RunSummary, StoredRun, and RunRepository. A single runs table uses summary columns for list queries and run_json for complete tool history and citations. Parameterized SQL prevents question text from being interpreted as statements; transactions commit or roll back the entire save; connections close explicitly to avoid lingering Windows file locks.

Mismatched database identifiers or versions are rejected. Lists do not read large JSON values; details validate AgentRun and summary consistency after reading. Queries neither execute tools, load model configuration, rescan files, nor create missing databases.

The CLI adds history_record only with --save-history, without changing AgentLoop or AgentRun. A failed save still returns the produced answer to the user with a separate storage error. Currently only final snapshots are saved; no incremental commits, history replay, or execution resumption. See [Diagnostic history](history.md).

## Report export

```text
CLI --export-run ID [--db PATH] [--output FILE.md]
  → RunRepository.get(ID), read-only database access and history validation
  → render_markdown(StoredRun), pure formatting
  → export_markdown(), exclusive creation of a new UTF-8 file
  → exported + run_id + path
```

reports/generator.py builds dedicated views from saved Observations using existing data models, presenting file evidence, knowledge references, and original backend text separately. It adds no scientific judgments, executes no tools, and does not reread the current knowledge base. Unsupported or mismatched observations explicitly fall back to raw JSON; the full saved snapshot closes the report.

Table escaping and adaptive code fences present log/backend originals as text. export_markdown writes only new .md files without overwriting existing reports; normally catchable write failures attempt to remove this run's incomplete file. The CLI reports output and database errors separately, retaining the original record. See [Report export](reports.md).

## Offline scenario evaluation

```text
python -m vasp_copilot.evaluation
  → cases.load_samples() verifies public sample sizes and SHA-256
  → cases.build_scenarios() constructs 16 scenarios and fixed expectations (mock-agent-v2)
  → runner.evaluate() creates temporary directories
      → run_scenario() writes scenario copies and creates a directory-restricted registry
      → AgentLoop + MockBackend (injected test backend for exception scenarios)
      → check_run() compares expectations and extracts saved observations from complete scans
      → observations.py checks OSZICAR values, step comparison, and original evidence positions on both sides
      → Verify input files unchanged
  → EvaluationReport: per-check expected / actual / passed and totals
  → Optionally create new JSON file; automatically clean up temporary scenarios
```

evaluation/cases.py keeps sample sources, artificial transformations, and expected observations together. Expected values come from manually checked fixed logs, not the current parser. runner.py handles execution and scoring; observations.py checks saved output observations without rereading current files or calling parsers; __main__.py handles arguments, JSON, and exit codes separately from the diagnostic CLI. v2 retains the original 9 scenarios and adds 7 for OSZICAR alone, matched/mismatched paired files, truncation, and insufficient evidence.

Evaluation reuses existing Agent/tools without modifying the main loop, database, or model configuration. Its explicit Mock tool-order regressions are unsuitable for directly grading real models with free tool choice. It currently checks only answer presence and inclusion of reference URLs, without semantic scoring. Inspect individual failed checks rather than replacing expectations directly with actual values. See evaluation.md.

## OSZICAR integration

oszicar.inspect_oszicar() reads bounded tail bytes and produces OszicarObservation. schemas.py defines electronic lines, energy summaries, and OSZICAR evidence separately without broadening the existing OUTCAR Evidence file type. ScanReport.oszicar is optional for validation of old snapshots; new scans explicitly populate an observation or read error.

Normal scans and inspect_oszicar reuse one parser. Mock adds an OSZICAR branch when OUTCAR is unreadable; DeepSeek can choose the tool based on the question. Report _oszicar() handles saved observations only, displaying electronic lines and summaries separately without filling old records from current files. See oszicar.md for usage and fields.

## Local electronic-loop diagnosis

diagnose_electronic_step() in electronic_diagnosis.py is a pure function accepting IterationObservation already parsed by iterations.py. It checks headers, unique messages, issues, and offset order, returning ElectronicStepDiagnosis. It reads no files, recomputes no energies, and parses no parameters; diagnostic evidence is deep-copied from original observations. diagnostics.py calls it after an existing tail read, and diagnose_outcar and combined scans automatically carry the result.

schemas.py distinguishes reported_not_reached, not_triggered, and unknown local results; severity is warning only for warnings, while all three overall states remain unknown. reports/generator.py displays the result, impact, and suggestions, explicitly stating not generated/not saved for absent fields or read failures without recalculating old snapshots. DeepSeek tool descriptions and prompts require explaining local warnings rather than treating the three overall unknown states as absence of reportable problems. Mock policy was not extended; substitute-transport tests verify messages/storage only, while real interpretation remains subject to user online acceptance.

## Output log step-comparison implementation

compare_output_steps() in output_comparison.py is a pure comparison function reusing OutputDiagnosis and OszicarObservation and copying original evidence. It handles errors/context issues first, then compares ionic numbers; electronic numbers are compared only if ionic numbers match and OSZICAR line ordering is reliable. inspect_output_comparison() reads both files for the standalone tool.

scan_directory reuses already parsed observations to produce output_comparison without rereading tails. When both outputs are readable, Mock selects a complete scan and explains OUTCAR and comparison results after retrieval; failed retrieval still retains file evidence. DeepSeek can call compare_outputs independently. The new ScanReport field is optional; old records receive no new conclusions, while reports support a dedicated comparison table. See output-comparison.md.

## Setting-driven electronic self-consistency checks

observe_electronic_settings() in scf_settings.py parses only bounded bytes supplied by the caller, distinguishing exact tags and semicolon segments, and separately recording five values, statuses, and evidence. run_start_offsets() recognizes limited run headers to help identify known cross-run risks; it cannot fully verify run identity.

diagnostics.py reads prefix/tail through one file handle, checks read lengths, sizes, and timestamps, then passes settings to electronic_diagnosis.py. diagnose_electronic_step() retains the original message result, adding settings_considerations and specific checks from reliable sampled values; settings are not applied when run-boundary issues are found. Reports show saved parameter tables, evidence, and conditional explanations; models receive the same content through existing tool results. Existing input_context/output_context/context_comparison still handle IBRION/NSW only, keeping new settings out of that comparison.

ElectronicSetting/ElectronicSettings in schemas.py define observations; ElectronicSettingConsideration defines evidence-based conditional explanations. The new OutputDiagnosis field defaults to null, and new ElectronicStepDiagnosis lists default to empty. Reading old records does not rescan files or change old answers. This stage added no dependencies, tool names, or Mock policies.