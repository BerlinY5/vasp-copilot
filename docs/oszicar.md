# OSZICAR observation tool

Date: 2026-10-24. Adds the inspect_oszicar tool and the oszicar field in the default directory scan. The tool reads OSZICAR in the selected directory and returns supported electronic lines and energy summaries within a bounded range, preserving original text and zero-based byte offsets. It does not change existing overall convergence judgments.

## Format basis and supported scope

The format basis is [VASP Wiki: OSZICAR](https://vasp.at/wiki/index.php/OSZICAR), reviewed at page revision oldid=29868. Field meanings below are paraphrased; parser limits belong to this project.

Electronic lines support DAV, RMM, and CG prefixes, reading the electronic step number, E, dE, d eps, ncg, rms, and optional rms(c), in order. E is the current free energy, dE is the change in free energy between electronic steps, and d eps is the change in band-structure energy. Energy units are eV. ncg counts, residuals, and charge differences are recorded separately, not treated as convergence thresholds.

Energy summaries support `number F=value E0=value d E=value`. F is free energy; E0 is the energy as sigma tends to zero. Summary d E depends on calculation mode, so its output field is named reported_delta_energy_ev, separate from electronic-line delta_energy_ev. A mag suffix with one or three numbers is accepted; only numeric syntax is validated and original text retained, without interpreting magnetic moments.

Supports E/e and D/d exponents, leading decimal points, signs, LF/CRLF, and an initial UTF-8 BOM. NaN, Inf, asterisk overflow, floating-point overflow or underflow of a nonzero value, negative residuals, zero step numbers, extra columns, and similar cases are not accepted as valid observations.

Molecular-dynamics T/E/F/E0 format, other algorithm labels, specialized machine-learning force-field semantics, and nonstandard formats are not yet supported. Modes are not guessed from filenames or values, and OSZICAR and OUTCAR are not automatically verified as belonging to the same run.

## Reading and status

- Read at most the final 64 KiB, recording read_start, bytes_read, and snapshot_size. The first line of a bounded window may be incomplete and is conservatively skipped.
- Interpret only records ending with a complete newline. Retain at most one electronic line and one summary per read; do not return the full trajectory or count total steps.
- A new electronic header clears old candidates; a new electronic line after a summary clears the old summary. Consecutive summaries do not reuse an old electronic line.
- Unsupported or corrupt records, invalid encoding, or a truncated final line clear previous candidates and record issues. Later complete valid lines can become new candidates; warnings remain.
- status=observed means only that supported lines are currently retained; unknown means no valid candidate is retained. The three overall states electronic_convergence, ionic_convergence, and normal_termination always remain unknown.
- Missing or unreadable files are recorded in error; outer tool success means only that a report was generated, so the inner error must still be checked.

The last retained number therefore cannot be interpreted as the total number of steps in the file, and an observed F/E0 summary does not become a convergence conclusion verified by this project. Text is retained unchanged; numbers use finite Python floating-point values, with their original precision representation available in evidence.text.

## Inspect the existing silicon sample offline

No key is needed; run a normal scan:

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$scan = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' | ConvertFrom-Json
$scan.oszicar | Format-List status, read_start, bytes_read, snapshot_size, error
$scan.oszicar.last_electronic_step | Format-List algorithm, iteration, energy_ev, delta_energy_ev
$scan.oszicar.last_energy_summary | Format-List ionic_step, free_energy_ev, energy_sigma0_ev, reported_delta_energy_ev
```

The first two lines set project and source locations; the third inspects the existing public directory; the rest display the OSZICAR parsing summary. Expected for this sample: all 1314 bytes read, RMM electronic step number 13, electronic line at byte 1156, summary at 1236, and F=E0=-10.645278 eV. All three overall states remain unknown. Inspect `.evidence` for the corresponding original text.

## Agent and reports

When OUTCAR and OSZICAR are both readable, Mock selects a complete scan, then retrieves references and answers, taking 4 decisions. With only OUTCAR readable, the previous parse-and-retrieve flow remains. With no readable OUTCAR but a readable OSZICAR, it calls inspect_oszicar and explains the result with byte evidence, taking 3 decisions. INCAR is considered after that. Mock does not switch tools in response to natural-language questions. For number comparison between the logs, see [Output step comparison](output-comparison.md).

With a key configured in the current PowerShell session, run:

```powershell
$run = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --backend deepseek --question 'Use inspect_oszicar to inspect electronic iteration lines and energy summaries. Cite file byte positions, distinguish electronic-line dE from summary d E, and do not treat log observations as proof of convergence.' --max-steps 6 --save-history | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.state.history | ForEach-Object { $_.call.tool_name }
```

This command makes real model-service calls; no online validation was performed in this round. Check state.history to see whether the model selected this tool. In the user's environment, earlier online runs succeeded with the VPN disabled; this is not a general requirement for all networks.

History storage continues using existing SQLite snapshots. Markdown reports add dedicated views for inspect_oszicar and scan_directory, listing electronic lines and summaries separately with original text and sources. An old scan record without the oszicar field says “parsing not saved,” rather than incorrectly claiming the file was missing. No database migration is required.

## Source reading order

1. schemas.py: OszicarEvidence, OszicarElectronicStep, OszicarEnergySummary, and OszicarObservation; field constraints keep invalid numbers out of tool observations.
2. oszicar.py: inspect_oszicar() recognizes lines after a bounded read; clear() manages old candidates; _number() rejects unrepresentable numbers.
3. inspection.py and tools/file_inspection.py: connect the parser to normal scans and the tool registry, sharing directory restrictions.
4. agent/mock.py and agent/deepseek.py: add the OSZICAR branch in the former and inform the model of the new tool and interpretation limits in the latter; AgentLoop itself needs no changes.
5. reports/generator.py: _oszicar() formats saved data without rereading files.

## Validation record and boundaries

The public OSZICAR comes from the previously downloaded pinned pymatgen commit and corresponds to oszicar_samples in tests/fixtures/pymatgen/manifest.json. It is 1314 bytes with SHA-256 1e3f219d8da90386d1f354cb7a8476084a7f4aea0d43514a21eda19d18c3664f. It was copied unchanged into the regression directory, without redownloading or rewriting newlines, under the upstream MIT license supplied in that directory.

tests/test_oszicar.py checks real bytes, energy values, truncation, new cycles, invalid numbers, bounded reading, shortening during a read, and more. tests/test_oszicar_integration.py checks the CLI, Mock, simulated native-tool-call transport, SQLite, reports, and old records. test_deepseek.py adds directory-boundary tests for the new tool.

This round added 42 tests. Targeted parser, integration, model-adapter, and report tests returned `107 passed in 5.03s`; the full suite returned `354 passed in 31.46s`. The existing 9 mock-agent-v1 scenarios continued to pass; the new OSZICAR branch was covered by this round's tests but had not yet been added to that fixed evaluation set.

All validation was offline, with no new dependencies, VASP execution, or real model grading of answers. There is currently only one public static OSZICAR sample; other format boundaries use explicitly constructed tests. This does not constitute comprehensive validation across versions and modes.