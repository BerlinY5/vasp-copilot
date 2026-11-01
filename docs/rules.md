# Stage 2: Evidence markers, not a complete convergence diagnosis

Reviewed: 2026-10-23. Applies to OUTCAR files retaining the complete English lines below; different versions, translated output, and manually modified logs have not been comprehensively validated. Alongside artificial tests, two public VASP 5.2.12 logs with pinned sources now serve as regressions; see evaluation.md. VASP was not run locally.

| Rule | Matched text | Basis | Limits |
| --- | --- | --- | --- |
| outcar.timing_marker | General timing and accounting informations for this job: | [sisl parser source](https://sisl.readthedocs.io/en/stable/_modules/sisl/io/vasp/outcar.html) uses the timing marker to identify termination information | This project only confirms the complete header line exists; it does not verify a complete timing block or process exit code |
| outcar.ionic_stop_marker | reached required accuracy - stopping structural energy minimisation | [ASE parser source](https://wiki.fysik.dtu.dk/ase/_modules/ase/calculators/vasp/vasp.html) uses the related message to identify the end of ionic optimization | Does not parse IBRION, NSW, or EDIFFG as part of this rule, or verify run boundaries, every electronic step, or actual forces |

The [VASP EDIFFG documentation](https://vasp.at/wiki/index.php/EDIFFG) defines ionic optimization stopping conditions: positive values compare energy changes, negative values compare forces; it does not apply to molecular dynamics. The [VASP EDIFF documentation](https://vasp.at/wiki/index.php/EDIFF) defines electronic self-consistency stopping conditions. These concepts are not interchangeable. Overall electronic convergence remains undecided; see the new local not-reached-message diagnosis at the end.

## Reading and evidence semantics

- Tail observation reads at most the final 65536 bytes rather than scanning large files from the start. read_start is a zero-based byte position, bytes_read is the tail byte count actually read, and snapshot_size is the file size before reading. Electronic settings separately sample a prefix of at most 128 KiB plus one probe byte, as described in the new rules below.
- Complete lines match exactly after stripping surrounding whitespace and must end in a newline. Discard the first window line when its completeness cannot be established, and discard an unterminated final line. This may miss markers; results remain unknown.
- evidence.byte_offset is the start byte of the matched line in the original file, including indentation, not a line number; text is the stripped marker. Each rule saves only its last match.
- Markers may belong to earlier runs, especially in concatenated, appended, or active logs. marker_found therefore means only that a marker exists in the sampled window. normal_termination, electronic_convergence, ionic_convergence, and calculation_status all remain unknown.
- Missing files, insufficient permissions, same-name directories, and similar errors are structured error values; neither missing matches nor read failures diagnose failure or non-convergence.
- Size-change checks detect only some concurrent writes; preferably diagnose output snapshots that are no longer being written.

## Data structures

schemas.py uses Pydantic v2 BaseModel to validate fields: Literal restricts status vocabulary, Field requires nonnegative byte positions, and extra='forbid' catches misspelled or extra fields. model_validate converts dictionaries into validated objects; model_dump converts objects into JSON-ready dictionaries. This validates types and status terms, not scientific conclusions.

File-inspection error values retain the stage 1 string format for compatibility; new diagnostic ErrorInfo provides kind and message. Public-format changes can be reconsidered when unifying the tool protocol.

## Input-context rules (2026-10-23)

Basis: [INCAR format](https://vasp.at/wiki/index.php/INCAR), [IBRION modes](https://vasp.at/wiki/index.php/IBRION), and [NSW steps](https://vasp.at/wiki/index.php/NSW). This is the project's classification of limited parameter combinations, not a complete VASP input validator.

Classify only when both parameters appear explicitly without parsing issues:

| Parameter combination | Classification |
| --- | --- |
| IBRION=-1, NSW>=0 | static: ions do not update; NSW>0 may repeat calculations on the same structure and is not a recommended-setting claim |
| IBRION=1/2/3, NSW=0 | static: this project classifies zero ionic update steps this way |
| IBRION=1/2/3, NSW>0 | relaxation |
| IBRION=0, NSW>0 | molecular_dynamics |
| IBRION=0, NSW=0 | unknown: zero-step MD is not inferred to be static |
| Other, missing, duplicated, or unparseable | unknown, with issues |

IBRION=3, although named a damped molecular-dynamics algorithm, is classified here as structural optimization; do not confuse it with IBRION=0 MD.

INCAR reads are limited to 65536+1 bytes, with the extra byte detecting oversize files. Partial parameters are not used when oversized. Supports UTF-8 (including BOM), ASCII, semicolons, and explicit comments; integers accept only an optional sign followed by 1–9 digits. Continuations, quotes, nested tags, and lines not matching assignment syntax conservatively return unknown, even though those syntaxes may be valid in VASP. Tool limits do not establish VASP input errors. Duplicate parameters do not receive guessed precedence even when values match.

parameters stores recognized parameters with one-based line numbers and raw lines; partial evidence may remain with nonempty issues, but classification is withheld. InputContext.error distinguishes filesystem and encoding errors. Other ordinary assignment tags are currently ignored.

INCAR may have changed after the calculation. VASP's official guidance recommends checking the actual interpreted parameters in OUTCAR; see sampled-value comparison below. input_context still does not change OUTCAR marker interpretation or any convergence conclusion. Last-iteration message observation follows later; all overall convergence states remain unknown.

## Input/output sampled-parameter comparison (2026-10-23)

Basis: the [VASP INCAR documentation](https://vasp.at/wiki/index.php/INCAR) explains that VASP writes its interpretation of input to OUTCAR and users should check it against their intent. This project provides limited parameter-value comparison on that basis, without treating arbitrary sampled lines as verified final effective parameters.

- Read 131072+1 bytes from the start; the extra byte only detects a limited window and is included in bytes_read. Parse the first 131072 bytes with read_start=0. window_limited does not mean reading failed.
- Accept only uppercase IBRION or NSW integer assignments, with optional leading spaces. Values may be followed by whitespace-separated explanatory text; multiple assignments per line, semicolons, NUL, and an unterminated final line are unsupported. Integer limits match INCAR parsing. Non-parameter lines are ignored.
- Duplicate parameters have no guessed precedence even when values match; they may reflect echoed input plus parameter blocks, or multiple logs. Nonempty issues or error makes both comparisons unknown.
- With issue-free parsing on both sides and a unique value for a parameter on each side, compare integers for matched / mismatched. A missing output parameter makes only that item unknown; defaults are not invented.
- Parameter evidence remains in input_context.parameters (raw lines and one-based line numbers) and output_context.parameters (OUTCAR text and zero-based line-start byte offsets). context_comparison retains both compared values.
- The formal parameter block has not been located and single-run identity is not guaranteed. Other parameters, later runs, or errors may lie outside the window. matched means visible sampled values agree; mismatched means they differ, perhaps because input changed, output belongs to another run, or VASP processed parameters. It identifies neither the cause nor failure.
- Input, output, and tail diagnostics are read separately, not atomically; preferably use a directory copy that is no longer being written. All scientific convergence conclusions remain unknown.

Tests use small artificial examples for comparison logic and read boundaries, plus parameter extraction from two public logs; this does not validate every VASP version.

## Messages associated with the last recognizable iteration (2026-10-23)

This iteration-observation field associates log messages only, without directly reporting converged or unconverged; see the later local-diagnosis rules below.

Basis and scope:

- An [original Kitchin research-group example](https://kitchingroup.cheme.cmu.edu/blog/category/vasp/2/) shows the `Iteration i( j)` format and extraction of outer/inner step numbers. This project borrows only the format and does not infer non-convergence from reaching NELM/NSW counts.
- [Original ASE issue #1429](https://gitlab.com/ase/ase/-/issues/1429) provides two explicit loop messages and illustrates risks in reconstructing VASP convergence judgments from energy differences alone. It is a bug report with specific samples, not a cross-version output specification.
- A [VASP official forum discussion of LEPSILON](https://vasp.at/forum/viewtopic.php?p=18660) notes that EDIFF messages in response calculations may disagree with actual stopping criteria. This step therefore reports messages rather than proof of electronic convergence in all calculation modes.

Implementation:

1. Reuse the final 64 KiB; skip the first line when the start offset is nonzero to avoid clipped headers.
2. Recognize complete `Iteration i( j)` lines with optional dash decorations, where i and j are positive 1–9-digit integers. Each match rebuilds the current observation and discards messages associated with the previous header.
3. Associate only complete subsequent message lines: `aborting loop because EDIFF is reached` or `aborting loop EDIFF was not reached (unconverged)`. Surrounding whitespace and dash decorations are allowed; substrings in quoted text do not match.
4. Retain at most the last evidence for each message category; both categories together produce conflicting_markers. No associated message means unknown, not failure.
5. A line starting with `vasp.<digits>.` is recognized as a new-run header and clears old state. Unsupported headers beginning with Iteration also clear state. A final line without a newline makes status unknown while retaining earlier evidence for inspection.

Fields: ionic_step and electronic_step are the last recognized numbers; header and markers contain original lines and zero-based original-file byte offsets; issues explain incomplete or unassociable observations. last_iteration is an observation within the read window, not a guarantee of the truly last physical step or a complete run.

Limits: not all log variants are supported. Unrecognized run boundaries, special response loops, and manually concatenated logs may remain ambiguous. Prefix parameter sampling has no same-run binding to tail observations. Missing headers, unsupported formats, and tail truncation may return unknown. Top-level electronic_convergence, ionic_convergence, normal_termination, and calculation_status remain unknown.

Artificial tests cover an earlier reached message followed by a new iteration, a final not-reached message, conflicting categories, repeated messages, new runs, damaged headers, truncated final lines, window boundaries, and CLI serialization. Two public VASP 5.2.12 logs and explicitly labeled truncated/concatenated derivatives are also tested. VASP has not been executed locally.

## Local anomaly diagnosis for the last electronic loop (2026-10-28)

Rule scf.last_loop_not_reached introduces an actionable local diagnosis. It reuses last_iteration without new file reads: only a complete iteration header, a unique explicit subsequent EDIFF not-reached message, no issues, and reliable original-text byte ordering produce electronic_step_diagnosis.status=reported_not_reached and severity=warning. Output retains ionic/electronic step numbers, header/message evidence, potential impact, manual investigation steps, and limits.

| Input observation | Local result | Meaning |
| --- | --- | --- |
| Unique not-reached message with reliable association | reported_not_reached / warning | The program reports that the last sampled loop did not reach EDIFF; check that step's results |
| Unique reached message with reliable association | not_triggered | This not-reached rule did not trigger; it does not mean the whole calculation converged |
| Missing, conflicting, orphaned messages, old-run resets, unsupported headers, truncated final lines, etc. | unknown | Sampling cannot support a reliable local anomaly judgment |
| OUTCAR unreadable or old record lacks the field | null | Rule result not generated/saved; history is not backfilled |

Basis: [Original ASE issue #1429](https://gitlab.com/ase/ase/-/issues/1429) demonstrates explicit stopping messages and risks of reconstructing judgments from energy differences alone; the [official EDIFF documentation](https://vasp.at/wiki/index.php/EDIFF) explains stopping conditions and fixed NELM iterations for EDIFF=0; the [official NELM documentation](https://vasp.at/wiki/index.php/NELM) defines the maximum electronic self-consistency count and recommends reviewing algorithms and mixing. Message formats come from specific output examples, not all VASP versions and modes.

Investigation suggestions proceed through provenance/completeness, same-run parameters and mode, and electronic iteration trajectories, considering algorithms, mixing, and iteration budgets as needed. The initial 2026-10-28 version did not extract EDIFF/NELM/ICHARG/ALGO; see the next section for new setting observations. The message rule itself invents no parameter values, declares neither NELM exhaustion nor a specific root cause, and does not edit inputs or restart. A local warning does not mean this tool independently verified energies or forces; program termination and ionic optimization must be checked separately. Unrecognized boundaries, special response modes, artificial concatenation, and sampling limits still restrict interpretation.

electronic_step_diagnosis is optional in OutputDiagnosis, defaulting to null for old data. New reports display only saved results, without applying current rules to old records. Both existing public logs contain reached messages and only verify absence of false positives; the first online positive case is an explicitly labeled artificial message transformation, with no authentic not-reached log coverage yet.

## Electronic self-consistency setting observations and conditional advice (2026-10-30)

electronic_settings is a new optional OUTCAR diagnostic field, defaulting to null for old records without backfilling. scf_settings.py parses EDIFF, NELM, ICHARG, ALGO, and IALGO, retaining status, value, occurrences, original lines, and line-start byte offsets for each; one line may support multiple parameters. observed means a unique sampled assignment with supported syntax; missing means the current prefix retained no assignment for that parameter; ambiguous means format, encoding, truncation, or duplication makes the value unreliable. The latter two use value=null, without guessed defaults or precedence. ALGO is never inferred from IALGO.

Supports parameter lines beginning with standard uppercase tags. NELM lines with semicolon-separated companion NELMIN/NELMDL assignments can be parsed; exact tag matching distinguishes EDIFFG, NELMIN, NELMDL, and other names. EDIFF supports finite decimals and E/e or D/d exponents, rejecting negatives, nonfinite values, overflow, underflow to zero, and incomplete numbers. Integers must be explicit 1–9-digit literals; NELM is positive, ICHARG nonnegative. ALGO accepts explicit words or Old Fast/Old VeryFast, without guesses from explanatory text or quotations. Whole lines starting with non-target/non-companion tags such as SYSTEM are ignored, even with later semicolon target assignments; this is not complete INCAR/OUTCAR syntax support. Display evidence for corrupt encodings may contain replacement characters; affected parameters are not observed.

diagnose_outcar reads a bounded prefix and tail through one file handle; small files/overlapping samples reuse bytes already read, with a maximum request of 131073 prefix bytes plus 65536 tail bytes. Changes in before/after size, mtime, or read length prevent generation of setting and loop results. Existing combined-scan IBRION/NSW output_context still reads independently, so no atomic snapshot is promised. Size/mtime checks cannot detect every concurrent change either.

iteration_association between the prefix and final loop always remains unknown. Multiple recognized VASP run headers, or a run header later than retained parameter evidence, preserve observations but disable parameter-based loop explanations. Unrecognized boundaries and unread contents between windows remain limitations.

| Reliable prefix observation | Conditional explanation | Inferences not made |
| --- | --- | --- |
| EDIFF=0 | If it belongs to this loop, check fixed-electronic-step-count context | Does not withdraw the not-reached message or declare convergence |
| ICHARG>=10 | If it belongs to this loop, first check fixed-charge/non-self-consistent context and setting validity | Does not declare this loop verified as non-self-consistent |
| Explicit ALGO=None/Nothing/Eigenval | If it belongs to this loop, check post-processing context | Does not fill in ALGO or declare a root cause |
| NELM and reliable last electronic number | Provide only below/equal/above numeric relation with evidence for both | Does not declare NELM exhaustion or total iteration count |

Basis: [EDIFF](https://vasp.at/wiki/index.php/EDIFF), [NELM](https://vasp.at/wiki/index.php/NELM), [ICHARG](https://vasp.at/wiki/index.php/ICHARG), [ALGO](https://vasp.at/wiki/index.php/ALGO), and [IALGO](https://vasp.at/wiki/index.php/IALGO). These explain definitions and applicability without establishing effective parameters, loop association, or anomaly root causes for this run. Local reported_not_reached message interpretation is unchanged; settings_considerations adds only checking context. All three overall states remain unknown.

Online record 13 further exposed an interpretation boundary: a not-reached message does not establish that this run's total-free-energy change or band-energy change was above, or not below, EDIFF, because the tool did not perform those numeric comparisons. Even a “conditional explanation” heading cannot turn this into fact. State the general stopping condition separately from unverified numeric criteria for this run, and call reported_not_reached a program-reported local warning rather than an independently verified physical failure. Artificially transformed cases can verify only the log-interpretation flow.