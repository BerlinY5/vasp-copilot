# Stage 4: Local knowledge retrieval and the Agent

search_knowledge reads eight short English Markdown notes bundled with the package. It does not access the network, require an API key, use a vector database, or change existing scientific diagnostic rules.

## File evidence and knowledge references

File tools answer “what was actually observed in this directory”; the knowledge tool answers “what these terms generally mean.” An EDIFF message at a particular OUTCAR byte position is file evidence; the meaning of EDIFF comes from reference material. Retrieving convergence conditions does not prove that this run converged.

The notes are project summaries, not full official texts. Sources checked on 2026-10-23: [OUTCAR](https://vasp.at/wiki/index.php/OUTCAR), [EDIFF](https://vasp.at/wiki/index.php/EDIFF), and [EDIFFG](https://vasp.at/wiki/index.php/EDIFFG). [OSZICAR](https://vasp.at/wiki/index.php/OSZICAR) was added and checked on 2026-10-26. On 2026-10-28, [INCAR](https://vasp.at/wiki/index.php/INCAR) settings and output comparison were added, along with [NELM](https://vasp.at/wiki/index.php/NELM) guidance on investigating self-consistency anomalies. On 2026-10-30, setting context for [ICHARG](https://vasp.at/wiki/index.php/ICHARG) and [ALGO/IALGO](https://vasp.at/wiki/index.php/ALGO) was added, and the NELM note's project limits were updated to reflect new parsing capabilities. Each note distinguishes “Official-source summary” from “Project policy.” Eight notes still cannot answer every VASP question.

The OSZICAR note addresses the reference gap exposed by online run 7: it explains electronic-line and summary fields and explicitly attributes the cross-file step-comparison policy to this project. The original query, translated as “OUTCAR OSZICAR step numbers alignment ionic step iteration correspondence,” can now retrieve both OSZICAR and OUTCAR notes. This verifies retrieval coverage only; whether the model cites them correctly and concisely still requires the user's online revalidation, not a substitute offline test.

## Files and reading order

1. `src/vasp_copilot/rag/knowledge/electronic.md`: example knowledge entry. The first four lines are title, Source, Keywords, and Reviewed; line five is blank, and the body starts on line six. Keywords are separated by English commas.
2. `src/vasp_copilot/rag/retriever.py`: SearchKnowledgeArgs validates the question and top_k; KnowledgeRetriever.search() performs bounded document reads, keyword matching, ranking, and returns KnowledgeHit. Each note is one excerpt; line numbers refer to the local body, not the official website.
3. `src/vasp_copilot/tools/knowledge_search.py`: registers retrieval as a common tool. The only arguments are query and top_k; the model cannot specify arbitrary file paths.
4. `src/vasp_copilot/tools/file_inspection.py`: create_registry() registers search_knowledge alongside file tools.
5. `src/vasp_copilot/agent/mock.py`: after reading OUTCAR, chooses search terms from observations, then combines evidence explanations and source citations. AgentLoop need not know the retrieval implementation.
6. `tests/test_knowledge_search.py`: retrieval boundaries, source traceability, observation-driven topic selection, errors, and CLI acceptance.

pyproject.toml declares Markdown as package data; importlib.resources locates bundled documents independently of the current terminal directory. root is only a Python developer/test injection point, not a tool argument.

## Retrieval mechanism and boundaries

- Legacy Chinese query aliases use substring matching; note metadata is now in English. English words and parameter names are matched case-insensitively with word boundaries, so EDIFF does not spuriously match EDIFFG.
- score counts distinct matched keywords and is used only for ranking, not as confidence or a probability of scientific correctness. Ties are sorted by filename.
- query is limited to 500 characters and cannot be blank; top_k is an integer from 1–5, default 3. No match returns empty hits rather than invented citations.
- At most 32 documents; each read is limited to 16 KiB plus one probe byte, and the body to 4000 characters. Size-limit violations, encoding errors, or corrupt metadata become tool execution_error rather than silently skipping damaged entries.
- Returns document, title, source, reviewed_on, excerpt, line_start, line_end, score, and matched_keywords; evidence_type is always reference.
- New results also contain sections, each preserving text, line_start/line_end, kind, citation, and source_url. official_summary denotes an explicitly labeled official-source summary, paraphrased by the project, with source_url pointing to the official source declared by the note. project_policy denotes project limits, with only a VASP-Copilot note/local-line citation and source_url=null. Unrecognized labels produce unclassified sections, not official explanations.
- reference_sections() splits at blank lines and reads initial labels; line numbers correspond exactly to the original body. It recognizes labels in curated notes without automatically verifying that statements are supported by the official website. New entries still require manual review. Existing excerpt/source fields remain for compatibility; source does not imply support for the entire note's project rules.
- Reports display official-source summaries and project policies separately using saved sections. Old hits without sections default to an empty list, displaying the original excerpt and source while noting missing section attribution; current documents do not backfill history. New fields reach the model and SQLite through existing tool observations without database migration. Correct natural-language final citations still require online acceptance.
- This is keyword retrieval, not semantic understanding; unlisted synonyms may yield no hits. New topics require sources, scope, aliases, and tests.
- No automatic web scraping, document downloads, or execution of instructions in documents. Whether real models use citations correctly still requires manual acceptance; prompts are not fact-checkers.

## New Mock flow

```text
inspect_directory
  ├─ OUTCAR readable → diagnose_outcar
  │    ├─ Parse report error → explain error and finish
  │    └─ Observation obtained → search_knowledge → present file evidence and general explanations separately
  ├─ Only INCAR readable → inspect_incar → explain input intent
  └─ Neither readable → explain insufficient evidence
```

Search EDIFF when the electronic message status is not unknown; search EDIFFG when an ionic stopping marker is observed; query both when both appear; otherwise query OUTCAR. If retrieval fails or returns no hits, retain file observations and explain that references are unavailable.

Mock remains a fixed conditional test policy and does not understand natural language. The standard OUTCAR branch takes 4 decisions (inspect, parse, retrieve, final answer), the INCAR branch 3, and an empty directory 2; the default limit of 6 is sufficient. DeepSeek sees the same tool definitions but selects as needed, so its flow may differ.

## Offline acceptance in PowerShell

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$result = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --max-steps 6 | ConvertFrom-Json
$result | Format-List status, decision_steps, answer, error
$result.state.history | ForEach-Object { $_.call.tool_name }
```

The first two lines locate the project and set the source search path; the third runs default offline Mock and converts JSON to a PowerShell object. The fourth displays the readable answer (Chinese in this historical validation); the fifth shows tool order. Expect status=completed, decision_steps=4, and inspect_directory, diagnose_outcar, search_knowledge in order. completed means only that an answer was produced; overall scientific states remain unknown.

Replace static_silicon with relaxation to compare the samples. Do not modify original INCAR or OUTCAR files for the demo.

## Online acceptance

In the same terminal with DEEPSEEK_API_KEY configured, after running the first two lines above:

```powershell
$result = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --backend deepseek --question 'First inspect the directory and OUTCAR, then use search_knowledge for relevant explanations. List file evidence, reference sources, and remaining uncertainties separately.' --max-steps 6 | ConvertFrom-Json
$result | Format-List status, decision_steps, answer, error
$result.state.history | ForEach-Object { $_.call.tool_name }
```

This incurs real API usage. Check whether file tools and search_knowledge were used, whether specific file positions and knowledge sources are cited, and whether general references are mistaken for proof of this run's convergence. On 2026-10-24 the user returned a completed answer without the full tool history; manual review found answer-quality issues, detailed in evaluation.md. An EDIFF citation in the final answer alone cannot establish that search_knowledge was actually called.

Source attribution also requires acceptance: “Official-source summary” is the project's paraphrase, not an official verbatim quotation; “Project policy” is VASP-Copilot's implementation policy and must not be attributed to the official source. The knowledge-tool notice and model prompt make this explicit, but real answers still need checking.

## Tests

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_search.py tests/test_agent_loop.py tests/test_deepseek.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

Covers Chinese/English queries, parameter word boundaries, no hits, ranking and top_k, invalid arguments, bounded reading, source and body line numbers, evidence retention after retrieval failures, CLI offline runs, and retrieval-result return through native tool calls using fake DeepSeek transport. No real API requests are sent.

Development validation for this stage (2026-10-23): full test output was `219 passed in 2.91s`. Both public samples, static_silicon and relaxation, completed in 4 decisions, retrieving electronic explanations and electronic/ionic explanations respectively; sample SHA-256 hashes matched before and after runs. The project virtual environment lacked setuptools, so the initial offline build failed. Using existing system build tools then produced a wheel, and knowledge documents were retrieved directly from that wheel after isolating the source search path. No project dependencies were installed or upgraded.
