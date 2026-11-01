# Validation records: Parsers and online answers

> This document preserves validation records from each stage; test counts belong to their respective dates, not the current full suite.
> See the [homepage](../README.md) for current installation and public sample reproduction, and [record 14](online-validation.md) for the latest online acceptance.

Date: 2026-10-23.

## Data sources

Uses two OUTCAR files from the [public test directories at a pinned pymatgen commit](https://github.com/materialsproject/pymatgen/tree/682bfd855dd89264b0ff8d6bee4815f8834cc5ac/tests/files/io/vasp/fixtures), both headed VASP 5.2.12. Exact sources and hashes are in tests/fixtures/pymatgen/manifest.json; the MIT license is retained with the samples.

## Manually checked expected observations

| Sample | IBRION | NSW | Last ionic step number | Last electronic step number | EDIFF message | Timing header | Structural optimization stopping message |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| static_silicon | -1 | 0 | 1 | 13 | Reached message | Present | Absent |
| relaxation | 2 | 99 | 3 | 4 | Reached message | Present | Present |

Absence of a structural optimization stopping message in the static sample does not imply failure. Both samples retain overall convergence conclusions of unknown; this validates parsing and evidence association, not an independent scientific recalculation.

## Validation coverage

- For each complete public log, verify SHA-256 and size once, and parameters, iteration messages, markers, and evidence byte positions once: 4 tests.
- Truncate the relaxation log at the first electronic-step header of ionic step 3, verifying that the message from ionic step 2 is not reused: 1 test.
- Append an authentic header from another run and verify that the preceding run association is cleared: 1 test.
- Concatenate both complete logs, verifying that the last header comes from the latter sample and its offset is absolute within the concatenated file: 1 test.
- CLI integration using a real OUTCAR with an artificial minimal INCAR: 1 test.

Adds 8 tests to the existing 90, for 98 total. All run offline, using existing pytest, Pydantic, and Python standard library dependencies; pymatgen was not installed.

## Reproduction

Run from the project root:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_real_outcar.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

The first runs 8 public-sample regressions; the second runs all current tests (98 at the end of stage 2, 219 after knowledge retrieval integration). If samples are missing or integrity tests fail, check file completeness and the manifest rather than changing expected hashes to hide data changes.

## Not yet verified

VASP was not run locally, and the full upstream sample settings and scientific correctness were not independently confirmed. Both logs are VASP 5.2.12 and do not represent VASP 6, different output verbosity, molecular dynamics, response calculations, authentic non-convergence, or abnormal termination scenarios. Derived truncation tests cannot replace validation on real abnormal logs.

Stronger conclusions in a subsequent stage require additional versions and abnormal logs with clear sources and calculation-mode information.

## Online answer returned by the user on 2026-10-24

The subject was public-examples/static_silicon. The user provided status=completed, decision_steps=4, an empty error, and the final answer, but not the full state.history. This confirms an answer was generated; tool names and citations in the answer alone cannot confirm precise tool order or retrieval calls. Earlier network/protocol errors were not proven resolved, and one success cannot establish ongoing stability.

Positive manual findings: the answer distinguished program termination, electronic convergence, and ionic convergence, retained tool unknown states, and cited OUTCAR byte positions. The corresponding log positions matched the existing public sample.

Problems and required corrections:

| Problem | Correct boundary |
| --- | --- |
| “If this is an optimization, it is obviously unfinished” | An absent ionic stopping marker does not prove unfinished optimization or failure; conditional wording cannot bypass evidence requirements |
| Attributing conservative reached_marker handling to VASP Wiki | This is project policy; official parameter explanations and project limits require separate attribution, and summaries are not official verbatim quotations |
| Inferring calculation type/total steps from the directory name static and final Iteration 1 | Directory names are not scientific evidence; last_iteration supplies only the last recognized number, not full-file iteration statistics |
| Claiming IBRION/NSW cannot be obtained because INCAR is missing | Existing scan_directory output_context can extract OUTCAR prefix parameters; this sample explicitly contains IBRION=-1 and NSW=0 |
| Claiming sampling did not cover the entire file | This sample is 61474 bytes, below the tail-read limit; reading all bytes differs from complete semantic parsing, which remains unimplemented |
| Treating an EDIFF message as verification of physical conditions | Current tools verify only that a message was observed; they do not recompute energy changes or validate all modes |

Corresponding changes: tightened the DeepSeek system prompt to require checking sampled OUTCAR parameters before determining the mode; the knowledge-tool notice explicitly states source attribution. unknown states were not relaxed and scientific parsing rules did not change. Prompts guide answers but cannot replace automated fact-checking.

The next online acceptance must save both the final answer and tool order and check that these problems do not recur, especially whether scan_directory parameter observations are cited correctly. Online effects of the changes had not yet been verified.

After this round's changes, model-adapter and knowledge-retrieval regression returned `78 passed in 1.43s`; other tests were not rerun. Existing scan_directory also verified NSW=0 evidence at OUTCAR byte 10918, IBRION=-1 at 11031, and tail diagnostic read_start=0 with bytes_read=snapshot_size=61474. All operations were offline and samples were unchanged.

## Offline Agent scenario evaluation (2026-10-24)

Another complete DeepSeek online record was obtained on 2026-10-25: 2 decisions and 1 scan_directory call, without knowledge retrieval. The answer falsely claimed retrieval, contained field/count errors, and overinterpreted the sampling range. API execution completed but quality acceptance failed. See [Online validation](online-validation.md) for the record, corrections, and next user revalidation. The fixed Mock evaluation below cannot replace that acceptance.

The current suite, `mock-agent-v2`, joins key behaviors scattered across unit tests into fixed, independently runnable scenarios with savable results. It retains v1's 9 scenarios and adds 7 OSZICAR/two-log scenarios, totaling 16. It reuses real AgentLoop, the tool registry, file parsers, and local retrieval without pytest, an API key, or a network connection. It evaluates the current Mock policy; natural-language questions do not alter Mock decisions. Existing v1 reports remain historical and are not overwritten by this evaluation.

| Scenario | Data source | Expected behavior |
| --- | --- | --- |
| static_silicon | Pinned public OUTCAR | Inspect → parse → EDIFF retrieval → answer; retain overall unknown |
| relaxation | Pinned public OUTCAR | Retrieve both EDIFF and EDIFFG, retaining corresponding evidence |
| truncated_output | First 81109 bytes of relaxation, artificially truncated | Last recognized 3(1), no EDIFF message for that step; do not reuse the previous step |
| incar_only | Artificial IBRION=2, NSW=20 | Choose inspect_incar; output input intent relaxation |
| invalid_incar | Artificial invalid UTF-8 | Retain UnicodeDecodeError and unknown |
| empty_directory | Artificial empty directory | Finish after one file inspection without parsing nonexistent files |
| missing_directory | Artificial missing path | Retain execution_error / FileNotFoundError and finish |
| step_limit | Public static sample, one-decision budget | max_steps; retain one observation without a final answer |
| backend_failure | RuntimeError injected at decision 2 | backend_error; retain the first observation without a final answer |
| oszicar_only | Pinned public OSZICAR | Choose inspect_oszicar; check electronic line, energy summary, and original text |
| paired_outputs | Pinned public OUTCAR / OSZICAR pair | Choose scan_directory; ionic numbers 1/1, electronic numbers 13/13, matched |
| ionic_mismatch | Artificially replace OSZICAR summary number 1 with 2 | Ionic numbers mismatched; electronic comparison remains unknown even with 13/13 |
| electronic_mismatch | Artificially replace last electronic number 13 with 12 | Ionic numbers matched, electronic numbers mismatched |
| truncated_oszicar | Artificially remove the final OSZICAR newline byte | Clear old candidates, retain issues; both checks unknown |
| missing_oszicar_summary | Artificially truncate OSZICAR before byte 1236 | Retain electronic line without summary; do not infer ionic number; both checks unknown |
| unsupported_oszicar | Artificially append an MD-format record to complete OSZICAR | Current parser does not support it; clear old candidates and retain unknown |

Passing means meeting the scenario's expectations. For example, backend_failure status=passed means the expected backend_error was detected and history retained, not that the backend succeeded.

### What is checked

Common checks cover run status, decision count, tool order, tool errors, history step numbers, retention of question and directory, answer presence, and file fingerprints before/after. OUTCAR scenarios also check the last iteration, marker states, sampling coverage, evidence count, correspondence of byte positions to original text, and retention of all three overall unknown conclusions. INCAR scenarios check input type, parameters, and raw lines; retrieval checks expected documents, source URLs, reference labels, and source URLs in the answer.

OSZICAR scenarios check retained line numbers, numeric values, original-text positions, sampling range, errors/issues, and overall unknown conclusions. Two-log scenarios additionally check overall comparison, each item's numbers/status, evidence from both sides, and nonempty reasons; run_identity must remain unknown. Incorrect numbers or evidence fail even if a final answer was produced normally. Reasons are checked only for presence, not their natural-language meaning.

Reports include the pinned sample commit and SHA-256 hashes for both decompressed OUTCAR files and existing static_silicon.OSZICAR (1314 bytes). Evaluation first performs bounded reads of fixed filenames and verifies sizes/hashes; it refuses to start if any sample is missing or changed. Expected values and offsets follow the manually inspected public logs, and truncation positions were also checked directly against original bytes. Public data retains its license and manifest; no new dataset is downloaded.

Scoring uses only saved observations, fixed expectations, and original scenario bytes, without calling the parser under test again to generate a “correct answer.” Standalone OSZICAR-tool observations and equivalent scan_directory observations share scoring logic so a complete scan cannot bypass evidence checks. Each run also verifies that temporary input copies remain unchanged.

### Run in PowerShell

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$evaluation = & .\.venv\Scripts\python.exe -m vasp_copilot.evaluation | ConvertFrom-Json
$evaluation | Format-List suite, status, total, passed, failed
$evaluation.cases | Format-Table name, status
```

The first two lines set project/source paths; the third runs evaluation and converts JSON to a PowerShell object; the last two show the summary and scenario list. Expect mock-agent-v2 / passed / 16 / 16 / 0. Normal scenarios run in automatically cleaned temporary directories and do not write diagnostic history.

To save detailed results, choose a destination that does not yet exist:

```powershell
$evaluation = & .\.venv\Scripts\python.exe -m vasp_copilot.evaluation --output 'reports\generated\my-evaluation.json' | ConvertFrom-Json
$evaluation.cases | Where-Object status -ne 'passed' | ConvertTo-Json -Depth 20
```

The first line both saves UTF-8 JSON and returns results; the second expands failed scenarios, with no output when none fail. Each check's name identifies its subject, expected is the expected value, and actual is this run's value. Choose any filename; existing paths are never overwritten.

| Exit code / error | Meaning and action |
| --- | --- |
| 0 | All scenarios meet expectations |
| 1 | At least one scenario failed or raised an exception; inspect failed checks and case.error |
| 2, fixture_error | Samples missing or hashes differ; check --fixtures and original samples rather than altering hashes |
| 2, evaluation_output_error | Destination exists or cannot be written; choose a new .json file or writable directory |
| 2, evaluation_error | Basic file operation failed, such as temporary-directory creation; check local permissions and space |

The command needs tests/fixtures/pymatgen from the full source repository; test data is not included in the Python package. From another working directory add `--fixtures 'D:\projects\vasp-copilot\tests\fixtures\pymatgen'`. The entry point imports only Mock and evaluation functionality, without loading model configuration. Expected-exception logs are suppressed by default, while check results and errors remain in JSON.

### Source reading and validation

First read Scenario, build_scenarios(), and _output_scenarios() in evaluation/cases.py to understand how inputs, expectations, and sources describe a scenario. Then read run_scenario() and check_run() in runner.py to understand separation of execution and scoring. observations.py specifically checks saved OSZICAR and comparison observations; _evidence_valid() verifies evidence points to complete original-file lines. Finally read __main__.py's output and exit-code handling. __init__.py only describes package responsibilities.

The 22 tests added for v1 remain, including 9 fault categories deliberately tampering with evidence offsets, evidence text, evidence count, tool order, overall status, reference sources, answer citations, input files, and questions. They also verify corrupt/oversized samples, offline reproducibility, no model-configuration reads, continuing after a single-scenario exception, KeyboardInterrupt propagation, no output overwrite, and cleanup after failed writes.

The full suite at v1 was `312 passed in 10.08s`. v2 adds tests/test_evaluation_outputs.py: 20 categories of complete-scan-result tampering, 4 scenarios improperly promoting uncertain results to matched, 4 OSZICAR missing/corrupt sample cases, plus checks that scoring neither rereads files nor calls parsers and that scenario byte transformations are correct, totaling 30 new tests.

v2 validation completed on 2026-10-25: targeted tests `52 passed in 34.64s`, full suite `413 passed in 52.94s`, and fixed scenarios 16/16 passed. Repeated runs produced identical reports and original samples remained unchanged. All offline, without new dependencies, VASP execution, or DeepSeek calls.

### Interpretation limits

16/16 counts passes for these sixteen fixed scenarios; it is not a real-world calculation success rate or LLM accuracy. Artificial number changes, truncations, appended formats, decoding errors, and injected exceptions are not authentic VASP failure logs; multiple versions/modes and real abnormal samples remain missing. Matching numbers do not establish run identity or convergence; differences do not establish failure or cause. Including a source URL does not establish correct natural-language inference. Evaluation does not check citation meaning, answer overstatements, or all scientific conclusions. Problems found in earlier online answers still require real-model revalidation.

If Mock order or tool contracts deliberately change, first verify the rationale, then manually update expectations and the suite version; do not automatically refresh the baseline from current output.