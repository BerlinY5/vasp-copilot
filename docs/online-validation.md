# DeepSeek online validation and fixes

> This document preserves the development validation history chronologically. Earlier statements such as "awaiting revalidation" describe their respective dates; the latest core revalidation conclusion is in run 14.
> The original database, synthetic case directories, and complete model reports are not included in the public repository. The run IDs and absolute paths below refer to the development environment.
> New users should start with the public example in the [README](../README.md). Archived local report paths below are not downloadable resources.
> Questions and quoted prose are translated into English for this document; the original saved records remain unchanged.

## 2026-10-25: first complete record

Database: data/local/online-validation.sqlite3; run_id=1; saved at 2026-10-25 05:33:36 UTC (13:33:36 Beijing time). This was an actual invocation on the user's machine, not Mock or a simulated transport.

The question requested calculation-mode inspection, cross-file sampled step checks, three distinct calculation states, and reference retrieval. The result was completed, with two decisions and one tool call: scan_directory followed by the final answer. There was no search_knowledge call.

| Item | Review result |
| --- | --- |
| Parameters and locations | NSW=0 / 10918 and IBRION=-1 / 11031 matched the saved tool observations. |
| Sampled indices and locations | OUTCAR 1(13) / 42249, OSZICAR electronic row / 1156, and summary / 1236 all matched the observations. |
| Overall states | The answer retained unknown for normal_termination, electronic_convergence, and ionic_convergence. |
| Retrieval execution | Failed: it claimed a general explanation obtained through retrieval without calling search_knowledge. |
| Field names and counts | Failed: it used the nonexistent incar_context field and described three context_comparison.parameters entries, although there were only two: IBRION and NSW. |
| Sampling boundaries | Failed: saying there were no further iterations after ionic step 1 exceeded what the last sampled index establishes. Claiming no other explicit closing evidence also exceeded the tool's actual checks. |

The cited EDIFFG, ASE, and OSZICAR URLs occurred in scan_directory.sources. These are parser reference metadata, not evidence that passage text was retrieved or a webpage visited. Links in an answer alone do not establish that the RAG workflow ran.

Conclusion: the interface and tool execution completed, but answer-quality validation failed. Saved run 1 remains unchanged.

## Changes prompted by this record

Added the optional `--require-knowledge` flag, available only with `--agent --backend deepseek`. It declares search_knowledge as a tool that must return successfully before completion. It is disabled by default and does not infer requirements from question keywords.

If the backend returns a premature final, the loop records completion_feedback and requests retrieval on the next decision. It neither invents a tool call nor searches on the model's behalf. Each rejected final still consumes a max_steps decision. Repeated omission or failure eventually returns max_steps with no answer; history and feedback can be saved.

A successful search may return hits=[]: zero matches are valid, and the model need not keep searching until it finds something. A tool error does not satisfy the requirement. Query selection remains the model's responsibility; relevance and natural-language claims still require review.

AgentState gained required_tools and completion_feedback, defaulting to empty lists for older records. ToolEvent.step retains the original decision number, so feedback may leave gaps in tool-history step numbers. Reports now include tool requirements and correction history; rejected final text is not saved as the final answer.

Each DeepSeek request receives actual search counts, successful search counts, returned passage counts, and unmet requirements. The prompt distinguishes sources URLs from retrieved passages, requires real field names and counts, and forbids inferring an absence of later iterations from the last sampled index. These are prompt constraints, not automatic fact verification.

## User-run online revalidation

Reuse the previously successful network setup and local key. The following historical procedure loads run 1's saved question and directory, then repeats the real request with the same question to compare behavior:

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$db = 'D:\projects\vasp-copilot\data\local\online-validation.sqlite3'
$previous = & .\.venv\Scripts\python.exe -m vasp_copilot --show-run 1 --db $db | ConvertFrom-Json
$run = & .\.venv\Scripts\python.exe -m vasp_copilot $previous.run.state.directory --agent --backend deepseek --question $previous.run.state.question --require-knowledge --max-steps 8 --save-history --db $db | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.history_record | Format-List
$run.state.history | ForEach-Object { $_.call.tool_name }
$run.state.completion_feedback | Format-Table step, kind, missing_tools -Wrap
```

In a new PowerShell session, configure the key using the hidden-input procedure in deepseek.md. If configuration_error prevents a run result, report that error without sharing the key.

Validation criteria:

1. History includes a successful search_knowledge call. Inspect its actual query, hits, and citation relevance. Scanning and retrieval need not occur in a fixed order.
2. The answer attributes passages to local notes, does not claim to have browsed their source pages, and does not present project restrictions as official wording.
3. Field names and counts are accurate. Sampling cannot establish no subsequent iterations, a complete run's total step count, or the absence of unexamined markers.
4. The three overall states and run identity remain unknown as reported by the tools. Equal indices establish only equal sampled indices.
5. If a premature final was corrected, completion_feedback identifies its decision number. Empty feedback can also mean the model retrieved proactively; no fixed decision count is required.

At this stage, the revised real-model behavior awaited user revalidation. Simulated transports tested premature finals, feedback, budgets, persistence, and legacy records; they were not a real-model quality evaluation.

Targeted regression: 16 new tests in test_required_knowledge.py; model adapter, loop, storage, and report tests yielded `148 passed in 14.69s`, with another `58 passed in 4.41s` for report CLI, retrieval, and file-tool integration: 206 passes in total. Other tests were not repeated. The new code read original database run 1 without modifying its two decisions or scan_directory history.

## 2026-10-25, run 3: protocol parsing failure

Database: data/local/online-validation.sqlite3; run_id=3; saved at 2026-10-25 05:52:14 UTC (13:52:14 Beijing time). The complete record confirmed backend_error, decision_steps=1, and error.message=DeepSeekProtocolError. required_tools contained search_knowledge, but history and completion_feedback were empty.

No executable tool decision or valid final answer had been obtained, so the completion-time retrieval check had not triggered. Empty history does not imply that the user's command failed to run. The old version saved only a generic error class, without the failed response, so truncation, multiple calls, invalid structure, and invalid arguments could no longer be distinguished.

The fix subdivided response-body, finish-reason, tool-call, and argument-parsing failures into fixed error types, retaining error.message, persistence, and reporting. It changed neither request parameters nor retry behavior. See "Protocol error categories" in deepseek.md. A later success would not determine run 3's cause; the new answer needs its own review.

Required regression yielded `93 passed in 4.30s`, covering error preservation in the loop, database, and reports; suppression of sensitive content; and existing adapter and retrieval requirements. Simulated transport validated diagnostic behavior only. The actual failure still required online reproduction. No evaluation scenarios or scientific parsing rules were added.

## 2026-10-25, run 4: proactive retrieval completed

run_id=4; saved at 2026-10-25 08:17:25 UTC (16:17:25 Beijing time). Full history: scan_directory → search_knowledge → answer; completed, three decisions, and two successful tool calls. required_tools=[] and completion_feedback=[]: this command omitted --require-knowledge, so the model retrieved proactively. This was not online validation of the enforced-retrieval correction mechanism.

The query was `EDIFF reached aborting loop electronic convergence IBRION -1 NSW 0 static calculation OUTCAR`, with top_k=3. The two actual hits were electronic.md and outcar.md. The answer's EDIFF and OUTCAR links and explanations matched these saved passages and separated official summaries from project restrictions. input_context, the two IBRION/NSW parameters, indices, and evidence positions matched tool observations. Equal indices were not promoted to shared run identity or convergence.

The basic workflow passed, with three remaining wording issues:

- Step comparison came from scan_directory.output_comparison, not a separate compare_outputs call. The answer should identify the tool actually executed and its nested field.
- OUTCAR read coverage was [0,61474), snapshot_size=61474; OSZICAR was [0,1314), snapshot_size=1314. Both current files were fully read. A generic statement about information outside the sampling window incorrectly implied unread bytes remained. Incomplete semantic parsing or scientific verification is a separate limitation.
- Calling step indices "line numbers" was imprecise. Distinguish them from byte offsets and source line numbers.

The prompt was updated only for these issues. Original run 4 remained unchanged and was exported to reports/generated/deepseek-online-run-4.md. This success neither identifies run 3's ProtocolError cause nor establishes sustained service stability or correct interpretation across all modes.

## Next online case: case-02 without an OSZICAR summary

Directory: data/local/online-validation-cases/case-02. This was an explicitly constructed validation copy, not an actual failed run. OUTCAR retained the public static-silicon log's original bytes; OSZICAR retained only the first 1236 bytes, removing the final energy summary while keeping the complete RMM:13 electronic row. case.json recorded the source revision, transformation, and hashes; LICENSE.pymatgen retained the original license. Original public-examples/static_silicon files were unchanged.

Preparation confirmed that the tools still observed electronic index 13 in both files, but no ionic summary index in OSZICAR. Both output_comparison checks therefore remained unknown: without confirmed ionic-index equality, 13/13 electronic indices cannot establish reliable alignment or shared run identity.

This validation used --require-knowledge and a question without the expected conclusion. The model had to read actual tool results and explain the evidence gap:

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$db = 'D:\projects\vasp-copilot\data\local\online-validation.sqlite3'
$question = 'Check whether the last sampled step indices in these two outputs can be reliably aligned. Explain the evidence, missing information, and its implications. Retrieve references, distinguish file observations, reference explanations, and convergence judgments, and answer concisely with evidence locations.'
$run = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\online-validation-cases\case-02' --agent --backend deepseek --question $question --require-knowledge --max-steps 8 --save-history --db $db | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.history_record | Format-List
```

## 2026-10-26, run 6: multiple tool calls

run_id=6; saved at 2026-10-26 10:48:15 UTC (18:48:15 Beijing time); case-02 with --require-knowledge. Result: backend_error, decision_steps=1, DeepSeekMultipleToolCallsError, and empty tool history. This fixed error category confirmed that the response contained multiple calls rejected by the old single-tool protocol. The original failed response was not saved, so its exact names, count, and arguments cannot be reconstructed. It does not determine run 3's cause.

The fix added ToolBatch: at most eight calls per response, with complete structure, JSON argument, and ID validation before sequential execution. Each result retains its native ID. The next request replays one assistant message containing the batch followed by all tool results. The registry still validates business arguments and directory restrictions individually. Over-limit or malformed batches are rejected; individual tool errors return as observations. A batch counts as one decision, and older history defaults to single-call positions.

Required regression yielded `207 passed in 18.35s`, covering batch execution, native cross-turn associations, rejection of malformed later calls without partial execution, argument correction, retrieval requirements, budgets, and database/report compatibility. Substitute transports did not establish online success. The next step was to repeat the same case-02 command, report the new run ID, status, and errors, then inspect whether the answer correctly explained missing-summary alignment uncertainty.

## 2026-10-26, run 7: batch calls and case-02 passed

run_id=7; saved at 2026-10-26 11:12:26.942756 UTC (19:12:26 Beijing time); completed, two decisions and two tool calls. The entire database record was reviewed read-only and exported to reports/generated/deepseek-online-run-7.md.

| Decision | History | Result |
| --- | --- | --- |
| 1 | scan_directory, batch_index=1, batch_size=2 | success; OUTCAR/OSZICAR comparison unknown |
| 1 | search_knowledge, batch_index=2, batch_size=2 | success; one hit, outcar.md |
| 2 | Final answer | completed |

The calls had distinct native call_ids within one model decision and executed sequentially. Original assistant_content described "checking in parallel"; this model wording did not reflect actual execution and was retained without claiming parallel implementation. required_tools=[search_knowledge] and completion_feedback=[] show proactive compliance, not online recovery from a rejected final.

Checks passed:

- The online batch workflow completed, supporting the compatibility fix for run 6, without identifying earlier generic ProtocolError causes.
- The answer correctly cited scan_directory.output_comparison. OUTCAR ionic/electronic indices were 1/13; OSZICAR electronic index was 13 with no retained summary. Both alignment checks remained unknown.
- Byte offsets 42249, 1156, 54994, and 60827 matched saved evidence. OUTCAR coverage was [0,61474), OSZICAR [0,1236). The answer distinguished complete reading from complete semantic parsing.
- Missing summaries were not described as calculation failure or unfinished optimization. Equal electronic indices were not treated as shared run identity or convergence.
- The recorded query, translated, was "OUTCAR OSZICAR step indices alignment ionic steps iteration correspondence", top_k=4. Only outcar.md matched. The answer disclosed the lack of a dedicated correspondence reference and distinguished project comparison rules from official summaries.

Remaining improvements:

- The knowledge base then contained only OUTCAR, EDIFF, and EDIFFG notes, lacking an OSZICAR-specific entry. Add a sourced note and have the user validate retrieval and attribution online.
- The answer repeated uncertainty and was substantially longer than requested.
- byte_offset is zero-based; say "byte offset 42249" rather than an ambiguous ordinal byte number.
- Missing INCAR prevents checking input intent but does not remove the interpretive value of observed OUTCAR parameters. An absolute claim that calculation mode cannot be determined should be limited to the tool's current lack of a mode verdict. last_energy_summary=null means no usable summary was retained by the parser, not that the entire file necessarily lacked one.

Conclusion: batch calls and the core case-02 evidence interpretation passed. This was not general proof of scientific correctness or adequate retrieval coverage. Only actual validation evidence was archived; no evaluation scenarios or repeat API calls were added.

## After run 7: dedicated references and concise answers

On 2026-10-26, oszicar.md was added against the official VASP OSZICAR page. Its official summary explains electronic rows and summary fields; its project paragraph explains comparison policy and missing-summary limitations. Keywords cover OSZICAR, step indices, electronic rows, and energy summaries. Reusing run 7's query then returned oszicar.md and outcar.md, with traceable local passage lines. Retrieval algorithms, Mock strategy, and parsing rules were unchanged.

The DeepSeek prompt added these requirements: retrieve OSZICAR references when needed; aim for roughly 500 Chinese characters when brevity is requested, excluding URLs and allowing extra space for decisive evidence; do not truncate answers or reduce the response token limit; avoid repetition and unrelated file inventories; use zero-based byte offsets; do not infer whole-file absence from null fields; distinguish missing INCAR from observed OUTCAR settings; describe batch execution as sequential.

Required regression yielded `119 passed in 6.27s`, covering English/Chinese searches for the new entry, the original online query, exact passage lines and keyword boundaries, and existing DeepSeek, retrieval-requirement, and batch behavior. No evaluation scenarios were added. These tests did not establish whether model prose would obey the brevity request.

The planned user revalidation reused run 7's question and case-02 with --require-knowledge and eight decisions. Review whether actual retrieval hits oszicar.md, citations correctly attribute comparison policy, alignment remains unknown, and the answer becomes shorter while retaining decisive OUTCAR/OSZICAR offsets. No fixed order or decision count was required. At this point, the online result was pending.

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$db = 'D:\projects\vasp-copilot\data\local\online-validation.sqlite3'
$previous = & .\.venv\Scripts\python.exe -m vasp_copilot --show-run 7 --db $db | ConvertFrom-Json
$run = & .\.venv\Scripts\python.exe -m vasp_copilot $previous.run.state.directory --agent --backend deepseek --question $previous.run.state.question --require-knowledge --max-steps 8 --save-history --db $db | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.history_record | Format-List
```

Use a PowerShell session with the key already configured; in a new session, use deepseek.md's hidden-input command first. Return the new run ID, status, and errors. Full tool history can be reviewed in the local database.

## 2026-10-26, run 8: dedicated retrieval passed, parameter claims exceeded evidence

run_id=8; saved at 2026-10-26 11:21:38.640621 UTC (19:21:38 Beijing time); completed, two decisions. The first decision sequentially executed inspect_directory, compare_outputs, inspect_oszicar, diagnose_outcar, and search_knowledge. All five succeeded, batch_size=5; the second decision answered. required_tools included search_knowledge and completion_feedback was empty.

Actual hits were oszicar.md and outcar.md. The answer correctly attributed comparison policy to the project and retained unknown alignment. Dedicated retrieval passed online. The original answer contained 1199 characters, including 396 basic Han characters (U+4E00–U+9FFF), down from 852 previously. It met the earlier Han-character soft target, but lengthy English technical fields still made it hard to read.

Failed evidence boundary: missing INCAR and other files were used to claim IBRION/NSW mode settings were unavailable. scan_directory was not called, and none of the five results contained OUTCAR prefix settings. This established only that the run had not obtained them, not that they were absent or unobtainable. compare_outputs already read both logs; separate log calls repeated reads and were justified only for required details absent from comparison results. The original report remains at reports/generated/deepseek-online-run-8.md.

### Changes and revalidation for run 8

- Expanded tool descriptions to explain scan_directory fields and overlap, compare_outputs scope, and the fact that inventory and tail tools do not extract mode parameters. These descriptions accompany every request's tool definitions.
- Revised the prompt to avoid both recommending a combined scan and unconditionally requiring a separate OSZICAR call. Use comparison for alignment alone; prefer combined scanning for multiple observations or mode settings; reuse sufficient observations and make additional checks only when needed.
- Distinguished "not checked", "read failed", "not retained by the parser", and "file missing". Omit irrelevant mode limitations; obtain output_context before discussing necessary mode settings.
- Changed the soft brevity target to roughly 500 visible characters, counting English, digits, and punctuation but excluding URLs. Preserve critical evidence even if the target is exceeded; do not truncate.

Existing relevant tests yielded `109 passed in 4.84s`. No evaluation cases, scientific rules, fixed tool sequence, or duplicate-call interception were added. Tool descriptions and prompts cannot guarantee model compliance; real online validation was still needed.

Revalidation reused run 8's original question without disclosing expected tools or parameter values. Check alignment evidence, appropriate omission or prior acquisition of mode settings, reduced unjustified rereading, correct dedicated references, and concise prose. No fixed step count or tool order was required.

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$db = 'D:\projects\vasp-copilot\data\local\online-validation.sqlite3'
$previous = & .\.venv\Scripts\python.exe -m vasp_copilot --show-run 8 --db $db | ConvertFrom-Json
$run = & .\.venv\Scripts\python.exe -m vasp_copilot $previous.run.state.directory --agent --backend deepseek --question $previous.run.state.question --require-knowledge --max-steps 8 --save-history --db $db | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.history_record | Format-List
```

## 2026-10-28: online execution progress display

The database still ended at run 8, so the later tool-selection prompt changes awaited real revalidation. Added optional --progress to distinguish backend waiting, tool execution, and further decisions required by unmet tool requirements. Progress and final JSON use separate streams. No model calls, evaluation cases, or changes to original records were added.

Final required regression yielded `112 passed in 4.63s`, covering native batch replay, immediate flushing, tool errors and retrieval correction, backend/budget exits, callback isolation, CLI arguments, snapshots, and default-off behavior. A real PowerShell check used --agent --progress on a temporary empty directory: stdout passed ConvertFrom-Json as completed with decision_steps=2, while stderr displayed progress. Redirected Python output used GBK and the terminal UTF-8, causing Chinese progress text to appear garbled. Fixed ASCII English labels resolved this; the same tests and PowerShell check passed again. No online model was called, so this was not online answer-quality validation.

The user was asked to reuse the original question and case-02 with only --progress added. Loading run 8 does not call the model; the following Agent command does. The terminal should show the decision stage, then tool names and results, while $run remains parseable. After receiving the new run ID and result, review selection, parameter-evidence boundaries, and citations. No fixed order or count was required.

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$db = 'D:\projects\vasp-copilot\data\local\online-validation.sqlite3'
$previous = & .\.venv\Scripts\python.exe -m vasp_copilot --show-run 8 --db $db | ConvertFrom-Json
$run = & .\.venv\Scripts\python.exe -m vasp_copilot $previous.run.state.directory --agent --backend deepseek --question $previous.run.state.question --require-knowledge --progress --max-steps 8 --save-history --db $db | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.history_record | Format-List
```

See "Execution progress" in deepseek.md for stderr behavior. Do not merge stderr and stdout before ConvertFrom-Json.

## 2026-10-28, run 9: tool selection, parameter observations, and progress passed

run_id=9; saved at 2026-10-28 13:50:46.348041 UTC (21:50:46 Beijing time); completed, two decisions and two calls. scan_directory and search_knowledge succeeded in one batch, positions 1/2 and 2/2; the second decision answered. required_tools=[search_knowledge], completion_feedback=[]; no premature-final correction occurred. Full history was reviewed read-only and exported to reports/generated/deepseek-online-run-9.md.

| Validation item | Observation | Conclusion |
| --- | --- | --- |
| Execution progress | The user returned line-by-line backend, tool, and completion messages; execution finished at about 5.2 seconds and final JSON remained parseable. | Passed for this run; timing came from terminal output and was not persisted. |
| Tool selection | The combined scan supplied required observations without overlapping file calls; calls fell from five in run 8 to two. | Passed for this run, not proof of correct selection for every question. |
| Parameter evidence | output_context contained NSW=0 (10918) and IBRION=-1 (11031). The answer used both and limited missing INCAR to unavailable input-intent comparison. | Passed; did not repeat run 8's unavailable-mode-parameters claim. |
| Indices and uncertainty | OUTCAR 1(13) at 42249; OSZICAR electronic index 13 at 1156, no summary; both comparison checks stayed unknown. | Core conclusion matched saved evidence. |
| Dedicated retrieval | Hits were oszicar.md and outcar.md; equal indices were not treated as shared identity or convergence. | Coverage passed; citation wording passed only partially. |
| Brevity | Original answer: 1155 characters, including 461 basic Han characters; English fields, digits, and repeated explanations added substantial length. | Missed the roughly 500-visible-character soft target. |

Two remaining improvements:

1. Alignment policy was attributed to VASP-Copilot, but a paragraph-ending "same source" could imply the official site provided the algorithm. The conservative interpretation of OUTCAR timing also came from project-policy text. General-reference and project-policy citations should each point to their own source, retaining document names and local lines.
2. The answer listed files unrelated to the missing index and repeated why equal electronic indices do not establish alignment. Prioritize decisive evidence. Brevity remained prompt-based, without an enforced limit; truncating critical evidence to meet a count would be inappropriate.

Conclusion: one actual online run validated progress display, fewer overlapping calls, parameter-evidence boundaries, and core index interpretation. Wording passed only partially. The original record and answer were retained; review comments were not written back as model output. Only validation notes and the original report were archived; runtime code was unchanged and tests were not repeated. No immediate repeat of the same case-02 was needed. Future work should broaden real online tasks and address attribution and redundancy, rather than continually tuning one example.

## 2026-10-28: section-level attribution and case-03 parameter comparison

Run 9 showed that a paragraph-level warning separating project rules from official sources still allowed ambiguous "same source" citations. Knowledge hits gained sections: official_summary paragraphs carry the official URL; project_policy paragraphs carry only a project-note-and-line citation; unrecognized labels become unclassified. Existing excerpt/source fields remain. Reports prefer saved sections and do not reconstruct missing sections in old records from the current corpus.

Added incar.md, based on the official INCAR page's discussion of input settings and checking OUTCAR. Input intent versus sampled output, uncertain mismatch causes, and status boundaries belong to project policy, not the external source. File diagnostics, Mock strategy, and evaluation cases were unchanged.

Required regression yielded `183 passed in 8.27s`: exact section text and lines, external-link attribution, unclassified paragraphs, native replay, SQLite, reports, legacy records, retrieval, batches, and completion-time retrieval requirements. Tool observations for the following case were also prepared and checked read-only. These checks did not establish correct real-model attribution.

### case-03: compare current inputs and output records online

Directory: data/local/online-validation-cases/case-03. OUTCAR and OSZICAR copied the complete original static_silicon bytes, verified against fixed-revision manifest hashes, with LICENSE.pymatgen. The added INCAR was a manually written validation input that did not generate these outputs. case.json records synthetic provenance, sources, transformations, sizes, and hashes. This was a diagnostic validation copy, not an actual failed calculation. Original public examples and case-02 remained unchanged.

Manual validation criteria:

| Observation | Expected tool evidence | Interpretation boundary |
| --- | --- | --- |
| Current INCAR | IBRION=2, line 2; NSW=20, line 3; input_context.calculation_type=relaxation | Input intent, not proof this input produced the logs. |
| OUTCAR settings | IBRION=-1 at 11031; NSW=0 at 10918 | Sampled output values; do not require a verified mode claim. |
| context_comparison | Both mismatched | Different observed values; cause unknown. |
| output_comparison | Ionic 1/1 and electronic 13/13, both matched | Does not cancel setting differences or establish identity. |
| Three calculation states | unknown, with run_identity also unknown | One comparison cannot establish success, failure, or convergence. |

Saying only "insufficient evidence" while omitting explicit differences would fail. Recommendations may request provenance, job records, and input backups, but must not present possible causes as facts or modify inputs automatically. Cite official summaries with their external sources and project rules with sections.citation. Also check for irrelevant file inventories.

The question disclosed neither mismatched values nor the expected conclusion and imposed no fixed tool order. The user ran the real request and saved it:

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$db = 'D:\projects\vasp-copilot\data\local\online-validation.sqlite3'
$question = 'Check whether current input settings agree with output records, and inspect the last sampled step indices in both outputs. Separate confirmed facts, whether discrepancy causes can be determined, and implications for calculation-state judgments. Retrieve necessary references, cite evidence locations, distinguish references from project rules, and answer concisely.'
$run = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\online-validation-cases\case-03' --agent --backend deepseek --question $question --require-knowledge --progress --max-steps 8 --save-history --db $db | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.history_record | Format-List
```

Use a terminal with the key configured; otherwise use deepseek.md's secure-input procedure. Review the complete record after receiving the new run ID and result. At this stage, the real result was pending.

## 2026-10-28, run 10: case-03 core task and attribution passed

run_id=10; saved at 2026-10-28 14:03:37.312269 UTC (22:03:37 Beijing time); completed, two decisions and two successful calls. scan_directory and search_knowledge ran in one batch, then the second decision answered. required_tools=[search_knowledge], completion_feedback=[]. Complete history was reviewed read-only and exported to reports/generated/deepseek-online-run-10.md.

Core task passed:

- INCAR IBRION=2 (line 2), NSW=20 (line 3), and OUTCAR IBRION=-1 (11031), NSW=0 (10918) were accurately cited. Both context_comparison checks were mismatched. relaxation remained limited to input intent.
- Output-index checks were matched: ionic 1/1 and electronic 13/13, with OUTCAR evidence at 42249 and OSZICAR electronic/summary evidence at 1156/1236. Equal indices were not confused with matching settings, shared identity, or convergence.
- Causes remained possibilities requiring verification. Neither edited inputs, another run's outputs, nor parameter handling was asserted as fact. Termination, electronic convergence, ionic convergence, and run identity remained unknown.
- Retrieval hit incar.md, oszicar.md, and outcar.md, each with sections. The answer used official INCAR/OSZICAR summary URLs and attributed project comparison policy to VASP-Copilot with incar.md:8-8 and oszicar.md:8-8. It did not repeat the misleading official "same source" policy citation.

Two wording limitations remained:

1. The answer said missing POSCAR/KPOINTS/POTCAR/CONTCAR/vasprun.xml made geometric or energy cross-checks impossible. Saved output_comparison.explanation actually said the tool did not perform energy, geometry, timestamp, or trajectory comparison. An unimplemented check does not establish unavailable data; OSZICAR still contained reported electronic energy and F/E0. Prefer "energy or geometry cross-checks were not performed in this run".
2. Original answer: 1282 characters, including 426 basic Han characters, still above the roughly 500-visible-character target, with repeated uncertainty and peripheral file lists.

Conclusion: this actual online run validated case-03's core parameter interpretation, separation of the two comparisons, and section-level attribution. Answer quality remained a partial pass. The case was synthetic; a generated diagnosis did not mean VASP ran or establish general scientific correctness. The original answer was retained without incorporating review edits. Only the report and notes were archived; runtime code and tests were unchanged. No immediate repeat of this case was required.

## 2026-10-28: first local electronic-loop warning

The user chose to strengthen diagnostic capability. Added scf.last_loop_not_reached: a reliable last iteration header, one subsequent explicit EDIFF-not-reached message, and no parsing issues produce electronic_step_diagnosis.status=reported_not_reached, severity=warning, evidence, potential impact, and manual checks. This explains a program report, not independently recomputed nonconvergence, NELM exhaustion, a known cause, or whole-run failure. A reached message yields not_triggered; uncertain context yields unknown; old records and read failures do not acquire a diagnosis retroactively.

Initially, comparing the last electronic index with NELM was considered. Official EDIFF=0 fixed-step behavior and other modes showed why counts alone cannot establish nonconvergence, so no count-based inference or expanded setting parser was added at this stage. See rules.md for scope and nelm.md for official explanations and separate project restrictions. Mock strategy and evaluation cases were not expanded.

Required regression yielded `159 passed in 6.44s`: scoped explicit warnings and evidence; resets after later iterations/runs; conflict, orphan, truncation, and window guards; no trigger from counts alone; no false warning for two public reached-message logs; native message replay, retrieval, persistence, reports, and legacy snapshots without backfilling. Public fixtures contained no genuine not-reached case, so these tests did not establish adequate real-SCF-failure coverage.

### case-04: online interpretation of a synthetic not-reached message

Directory: data/local/online-validation-cases/case-04, containing only OUTCAR, LICENSE.pymatgen, and case.json. After verifying the pinned public static_silicon hash, its unique EDIFF-reached message was replaced with an explicit not-reached message. Parameters, energies, iteration headers, and other contents were not recalculated. case.json identifies synthetic provenance, original/derived hashes, old/new messages, replacement position, and count. This was not an actual unconverged VASP run; it validated the diagnostic rule and Agent explanation. Genuine failure logs remained future work.

Preliminary reading found ionic/electronic indices 1/13, header offset 42249, message-line offset 54994, and reported_not_reached. Subsequent offsets changed with replacement length; original timing offset 60827 could not be reused. Always use current tool evidence. Retaining original energy and timing content does not make the transformed log genuine calculation evidence. All three overall states stayed unknown.

Online validation priorities:

1. Actually read OUTCAR and explain the local program report, its loop, and evidence rather than ignoring it with "all unknown".
2. Distinguish reported_not_reached from overall convergence or termination; do not assert NELM exhaustion or a proven cause.
3. Retrieve EDIFF/NELM references and separately attribute official definitions and project rules. Check same-run mode, settings, and completeness before algorithm, mixing, or iteration-budget changes; do not prescribe blindly increasing NELM.
4. Do not modify files or submit jobs. Do not treat synthetic-case success as comprehensive validation on real failure logs.

The question supplied no expected warning, index, or tool order. The user ran it in a key-configured terminal:

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$db = 'D:\projects\vasp-copilot\data\local\online-validation.sqlite3'
$question = 'Check this calculation directory for an explicit electronic self-consistency warning. Explain its scope, file evidence, possible impact, and recommended investigation order. Distinguish program reports, reference explanations, and verified conclusions; keep unknown causes uncertain and answer concisely.'
$run = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\online-validation-cases\case-04' --agent --backend deepseek --question $question --require-knowledge --progress --max-steps 8 --save-history --db $db | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.history_record | Format-List
```

At this stage, the online explanation awaited a new user-provided record. Anonymized, traceable genuine not-reached logs could later extend failure coverage; this synthetic case could not replace them.

## 2026-10-28, run 11: local warning and explanation workflow passed

run_id=11; saved at 2026-10-28 14:36:04.663953 UTC (22:36:04 Beijing time); completed, two decisions and two successful calls. scan_directory and search_knowledge ran in the first batch, followed by the answer. required_tools=[search_knowledge], completion_feedback=[]. Full history was reviewed read-only; the original report is reports/generated/deepseek-online-run-11.md.

Core online validation of this synthetic message-transformation case passed:

- The tool returned scf.last_loop_not_reached, reported_not_reached/warning, scope=last_sampled_electronic_loop, ionic/electronic indices 1/13, header offset 42249, and explicit-message line offset 54994. The answer accurately explained this local program report instead of overlooking it because overall states remained unknown.
- It recommended carefully checking reported energy/forces after the loop, in the order of provenance/completeness, same-run settings/mode, iteration trajectory, and algorithm/mixing.
- It did not claim recomputed physical stopping criteria, NELM exhaustion, a known cause, or whole-run failure. It disclosed unextracted settings and unexcluded special modes; the three overall states and run identity stayed unknown.
- Actual search hits were electronic.md and nelm.md. Official summaries carried EDIFF/NELM links; project restrictions cited VASP-Copilot note line 8 rather than the official site.
- Transformed OUTCAR size was 61485 bytes, with timing offset 60838. The answer used current evidence rather than original offset 60827. User progress output showed completion at about 4.4 seconds; progress timing was not persisted.

Minor wording issues remained: undefined "instrument" should be replaced with the actual tool field. The original answer contained 926 characters, including 278 basic Han characters, above the soft brevity target but shorter than run 10's 1282. No core rule issue justified another immediate repeat solely for wording.

Validation boundary: this was a real DeepSeek call against an artificially replaced warning message, without rerunning VASP or a genuine failed-SCF positive case. It established usability of the local rule, selection, retrieval, explanation, and persistence in this case, not comprehensive real-failure diagnosis. Prioritize traceable genuine not-reached logs before broadening setting or cause analysis. Only the original report and validation notes were archived; no runtime edits, repeat tests, or online calls were made.

## 2026-10-30: reading self-consistency settings and conditional interpretation

The user chose actual extraction of EDIFF/NELM/ICHARG/ALGO/IALGO. diagnose_outcar and combined scans now return diagnostics.electronic_settings (a root field for the standalone tool), with full-line byte evidence, observed/missing/ambiguous statuses, occurrence counts, and prefix coverage. Existing IBRION/NSW input/output comparison was not expanded. Local diagnosis retains the program report and adds conditional considerations from sampled settings, without establishing same-run association, inferring algorithm names, or determining causes.

Final required regression yielded `248 passed in 19.65s`: bounded reading and unstable-file rejection; real semicolon-separated NELM lines; damaged numbers/encoding; duplicates; exact labels; special-mode contexts; numeric relationships without exhaustion claims; restart guards; native replay; persistence/reporting; and legacy records. New code read original run 11 without modifying its snapshot or backfilling settings. A read-only case-04 check produced the observations below without changing the case.

| Parameter | Current case-04 observation | Manual validation requirement |
| --- | --- | --- |
| EDIFF | 2e-6; original text 0.2E-05 | Cite actual byte evidence rather than claiming all settings were unextracted. |
| NELM | 100, on a line with NELMIN/NELMDL | Do not confuse companion labels with the target value. |
| ICHARG | 2 | Do not invent fixed-charge mode. |
| IALGO | 68 | Report only the observed value. |
| ALGO | missing | Do not fill a default or infer a name from IALGO. |

Last sampled electronic index 13 has relationship below to prefix NELM=100. This is a numeric comparison only; association remains unknown and does not establish exhaustion. reported_not_reached remains. case-04 is a synthetic message transformation, so this extends setting-reading and explanation validation, not genuine-failure coverage.

Real-model behavior awaited user revalidation in a key-configured terminal, reusing case-04 and asking for settings-based interpretation:

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$db = 'D:\projects\vasp-copilot\data\local\online-validation.sqlite3'
$question = 'Inspect electronic self-consistency warnings in this directory and interpret them using stopping conditions, iteration limits, and algorithm/charge settings actually recorded in the output. List observed values and evidence locations, missing information, whether causes can be determined, and a targeted investigation order. Distinguish program reports, parameter observations, and conditional interpretation; answer concisely.'
$run = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\online-validation-cases\case-04' --agent --backend deepseek --question $question --require-knowledge --progress --max-steps 8 --save-history --db $db | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.history_record | Format-List
```

Review actual history after receiving the new run ID and result, without requiring fixed order or count. EDIFF=0, ICHARG>=10, and postprocessing ALGO branches had code tests only, not separate online validation. One ordinary-settings case cannot establish applicability to all modes.

## 2026-10-30, run 13: parameter extraction passed, physical interpretation exceeded evidence

run_id=13; saved at 2026-10-30 03:08:00.084306 UTC (11:08:00 Beijing time); completed, two decisions and two successful calls. scan_directory and search_knowledge ran together, followed by the answer. The user's returned text matched this record. Original report: reports/generated/deepseek-online-run-13.md.

Parameter extraction passed: EDIFF=2e-6 (10422), NELM=100 (10357), ICHARG=2 (9809), IALGO=68 (12312), and ALGO missing were correctly cited, without defaults or inferred names. The answer retained the numeric-only nature of 13 < 100, the lack of exhaustion proof, and unverified prefix-to-loop association. Actual retrieval hits were electronic.md, algo.md, and icharg.md; nelm.md must not be counted as a hit in this run.

Interpretation did not fully pass:

- Saying "the not-reached message means the adjacent-step energy difference was not below the threshold" inferred an actual numeric result from message text. The tool had not recomputed free-energy or band-energy changes or verified mode/settings association. A "conditional interpretation" label did not make this a supported fact. Correct wording: "The file explicitly reports EDIFF not reached; the tool has not verified whether both energy changes satisfy the stopping criteria."
- Calling it "a real local fault" blurred a file report with an independently verified physical problem. The model had not received case.json's transformation provenance and could not be expected to identify it unaided. The application and reviewer must track the synthetic origin; general model wording should remain "a program-reported local warning".

The fix targeted diagnostic limitations, electronic.md's project policy, and the DeepSeek prompt, separating official definitions, observed messages, and numerical verification. It changed neither parameter parsing nor calculation files. Relevant regression yielded `160 passed in 3.32s`, confirming tool replay and compatibility, not real-model compliance. User revalidation was needed.

Revalidation reused run 13's original question and directory without embedding the expected answer, retaining --require-knowledge, --progress, an eight-decision budget, and persistence. Check accurate parameter evidence, no ALGO inference, and no claims of measured energy changes above/not below EDIFF or independently verified physical faults. At this point, the revised real-model result was pending. Original run 13 was not rewritten.

## 2026-10-30, run 14: core revalidation of settings and interpretation boundaries passed

run_id=14; saved at 2026-10-30 03:17:54.836503 UTC (11:17:54 Beijing time); completed, two decisions and two successful calls. scan_directory and search_knowledge ran together, followed by the answer. required_tools=[search_knowledge], completion_feedback=[]. The complete record was reviewed read-only; original report: reports/generated/deepseek-online-run-14.md.

Core checks passed:

- EDIFF=2e-6 (byte offset 10422), NELM=100 (10357), ICHARG=2 (9809), IALGO=68 (12312), and ALGO missing matched observations, with no defaults or inferred ALGO. Extra NELMIN=2 and NELMDL=0 in the answer genuinely occurred on the saved NELM evidence line. These were model quotations from evidence, not new structured parser fields; extraction still covers five parameters.
- The electronic-step-13 not-reached message remained a program-reported local warning, not a verified physical fault. Header 42249 and message 54994 were traceable.
- The answer explicitly said free-energy and band-energy changes had not been recomputed. It separated general stopping definitions from unverified numerical judgments and did not repeat run 13's inference.
- Prefix-to-loop association remained unknown; 13 < 100 remained numeric only, without exhaustion or cause claims. All three overall states stayed unknown.
- Actual hits were electronic.md and nelm.md, with citations separating official summaries from project restrictions. Recommendations prioritized provenance/completeness, trajectories, and algorithm/mixing checks. No settings were changed and no job submitted.

Wording could still improve: the original answer had 1044 characters, exceeding the soft brevity goal; "IPS" was undefined and should be "input/output setting comparison"; "therefore a static calculation" should be limited to the prefix parameters' fixed-ion meaning rather than suggesting verified mode or identity. These were recorded for later wording work, without another prompt change or immediate repeat.

Stage conclusion: setting extraction, integration with the local warning, missing-setting behavior, and message/numeric boundaries completed core online validation on this ordinary-settings synthetic case. This was not genuine SCF failure coverage, nor separate online validation of EDIFF=0, ICHARG>=10, or postprocessing ALGO. Future coverage should use new tasks or traceable genuine logs, rather than repeatedly tuning the same synthetic case. Only the original report and validation notes were archived; runtime code, original answer, and data stayed unchanged, and code tests were not repeated.
