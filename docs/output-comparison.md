# Compare sampled OUTCAR and OSZICAR step numbers

Date: 2026-10-24. Adds compare_outputs and the output_comparison field in default scans. The goal is to display numbers and original text already recognized by the two log parsers side by side, helping identify differences that need further verification. This is the project's conservative comparison policy, not a new VASP convergence criterion.

## What is compared

| Item | OUTCAR observation | OSZICAR observation | Comparison conditions |
| --- | --- | --- | --- |
| ionic_step | i from the last recognized Iteration i(j) | Number in the last retained F/E0 summary | Reliable records on both sides, without reading, context, or parsing issues |
| electronic_step | j from that header | Number in the last retained electronic line | The ionic step numbers above match, and the OSZICAR electronic line precedes the retained summary |

Each item includes status, outcar_value, oszicar_value, evidence from both sides, and reason. status is matched, mismatched, or unknown. Even when comparison is impossible, acquired values and original text are retained so users can see what is missing; do not inspect only the two numeric columns while ignoring unknown and reason.

Without an OSZICAR summary, do not infer an ionic step from the electronic-line count; if ionic steps differ, do not directly compare electronic numbers. A summary without an electronic line permits only ionic comparison. An unknown OUTCAR EDIFF message does not necessarily block number comparison: an intact header with no context issues still permits comparison of its explicit numbers.

Read errors, a truncated OUTCAR final line or conflicting messages, OSZICAR issues, and similar problems block comparison. The current policy also conservatively blocks comparison when OSZICAR has a limited-window warning; ignorable and non-ignorable warnings have not yet been distinguished.

Overall status: mismatched if any comparable item differs; matched only if both items match; otherwise unknown. run_identity always remains unknown. Files are read sequentially without an atomic cross-file snapshot; if they are being written, reads may capture different points in time. Equal numbers do not establish the same run or convergence; different numbers do not establish failure or a specific cause.

This round does not compare energy, structures, timestamps, or full trajectories. Electronic-line dE, summary d E, and different energy definitions are not treated as directly equivalent. See rules.md and oszicar.md for the parsing scope of basic fields.

## View comparison results directly

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$scan = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' | ConvertFrom-Json
$scan.output_comparison | Format-List status, run_identity
$scan.output_comparison.checks | Format-Table name, outcar_value, oszicar_value, status, reason -Wrap
```

The first two lines set the run location; the third runs an offline directory scan; the last two display the overall result and each item's reason. For the public silicon sample, expect ionic steps 1 versus 1, electronic steps 13 versus 13, status=matched, and run_identity=unknown. OUTCAR evidence is at byte 42249; the OSZICAR electronic line is at 1156 and its summary at 1236.

For unknown, inspect each reason, plus scan.diagnostics.error, scan.diagnostics.last_iteration.issues, and scan.oszicar.error/ issues. For mismatched, first check original text and file sources; do not directly modify calculation inputs based on this result.

## Agent, history, and reports

Mock first inspects the directory. When OUTCAR and OSZICAR are both readable, it chooses scan_directory, retrieves references based on OUTCAR observations, and includes the number comparison and original text from both sides in its final answer. The normal path still takes 4 decisions. With only one output file, existing fine-grained branches remain; Mock does not understand natural-language questions.

```powershell
$run = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --save-history | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.state.history | ForEach-Object { $_.call.tool_name }
```

Expected tool order: inspect_directory → scan_directory → search_knowledge, then the final answer. Successful storage returns run_id in history_record; use the existing `--export-run` command to export a report. Assess save failure separately from Agent completed; see history.md.

DeepSeek can choose compare_outputs for a dedicated comparison or use output_comparison from scan_directory. The prompt requires retaining unknown and avoiding inferences about causes or run identity. This round tested native tool calls only through simulated transport, without online calls.

Markdown reports add a side-by-side table, original text from both files, and byte positions. Export uses only the saved comparison, without rereading source files or adding conclusions to old records under new rules. Old snapshots without output_comparison remain queryable and exportable, with the explanation “output log step comparison not saved”; no database migration is required.

## Code reading order

1. schemas.py: OutputStepCheck defines one item and OutputStepComparison the overall result; the new ScanReport field is optional for compatibility with old records.
2. output_comparison.py: compare_output_steps() is a pure function accepting two observations, checking applicability, comparing integers, and copying evidence; inspect_output_comparison() is a thin wrapper reading both files.
3. inspection.py: reuse observations already read in this scan, without rereading tails for the new comparison. tools/file_inspection.py registers compare_outputs and reuses directory restrictions.
4. agent/mock.py: the two-output branch chooses a complete scan; summarize_comparison() assembles the explanation. agent/deepseek.py adds tool-use boundaries. The main loop needs no changes.
5. reports/generator.py: _output_comparison() formats saved results as a table without recomputing them.

## Validation record

Uses the existing public static_silicon OUTCAR/OSZICAR pair with pinned commit and SHA-256; no additional downloads. tests/test_output_comparison.py covers matching, different, missing, and truncated numbers; context conflicts; new cycles; missing summaries; reversed evidence order; bounded windows; read errors; and pure-function isolation.

tests/test_output_comparison_integration.py covers real tools, the full Mock flow, missing files, failed retrieval, files disappearing after inspection, history snapshots, reports, and simulated DeepSeek calls. compare_outputs was also added to existing directory-boundary tests, and old scan-format compatibility tests were updated. Exceptional scenarios such as mismatched numbers use explicitly constructed data, not purported authentic VASP failure samples.

This round added 29 tests. Targeted regression returned `125 passed in 8.27s`; the full suite returned `383 passed in 19.31s`. Offline Mock on the real public directory completed in 4 decisions and exported a report. The existing 9 mock-agent-v1 scenarios continued to pass; this round's integration tests cover the new two-output branch. No dependencies were added and VASP was not run.