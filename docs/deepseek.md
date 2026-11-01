# DeepSeek backend: Configuration and validation

Release notes compiled: 2026-11-01. New users should first follow the [homepage](../README.md) to install and prepare the public sample.

API references: [Your First API Call](https://api-docs.deepseek.com/), [Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/), and [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/). The project defaults to deepseek-flash, overridable with DEEPSEEK_MODEL; available models depend on the provider account and API responses.

## Implementation scope

- Uses the fixed official endpoint https://api.deepseek.com/chat/completions to avoid sending keys to another host; automatic redirects are unsupported.
- Uses Python's standard library urllib, with no SDK, new dependencies, or automatic retries. Requests non-streaming responses with thinking=disabled and max_tokens=2048.
- Converts describe() into DeepSeek tools. The model chooses tools; Python still validates and executes through ToolRegistry. Original call_id and assistant_content are preserved, and tool results return in subsequent messages with corresponding tool_call_id values.
- Supports 1–8 function calls in one response. Validates the entire batch's structure, IDs, and JSON arguments first, then executes sequentially through the registry. A subsequent assistant message preserves the complete native-call batch, followed by the corresponding tool messages. Malformed batches are rejected as a whole; individual tool argument, path, or execution errors return as their own results without blocking subsequent calls.
- A batch counts as one model decision, and the final answer also costs one decision; at most max_steps × 8 tool calls can execute. Calls in the same batch cannot depend on other results that have not yet returned, and file reads are not atomic snapshots.
- The application reconstructs tool history. Mock history lacking native call_id values cannot currently be switched to DeepSeek; each new run rebuilds state. Thinking is explicitly disabled, so cross-round reasoning_content replay is not handled.
- Reads at most 2 MiB plus one probe byte from a response and rejects oversized responses. timeout is urllib's blocking network-operation timeout, not a hard total Agent time limit; --max-steps still controls the decision limit.
- The CLI Agent's registry is bound to the selected directory. All file tools reject other directories, including known VASP files resolving outside it. Path checks are not a security sandbox against concurrent changes or arbitrary Python backends.

## Local configuration

The project reads process environment variables only and does not load .env automatically. The root .env.example is a key-free field reference; it need not be copied, and real keys need not be written into source.

PowerShell:

```powershell
# Run from the repository root after installing the project
$env:DEEPSEEK_API_KEY = ([System.Net.NetworkCredential]::new('', (Read-Host 'DeepSeek API Key' -AsSecureString))).Password
$env:DEEPSEEK_MODEL = 'deepseek-flash'
$env:DEEPSEEK_TIMEOUT = '30'
```

Read-Host reads the key through hidden input; command history records the expression, not the entered key. The key then exists in the current process environment. Do not paste it into chat or commit it to Git.

After configuration, the following command sends real requests to DeepSeek, billed according to the provider's rules:

```powershell
& .\.venv\Scripts\python.exe -m vasp_copilot data/local/demo/static_silicon --agent --backend deepseek --question 'Check the calculation status based on file evidence.' --max-steps 8
```

Requests include the question, selected directory path, tool descriptions, and completed tool results (including filenames, parameters, sampled evidence, and error information). They do not proactively upload complete calculation files or POTCAR contents. Choose a directory suitable for sending to this service before integration testing.

When a question requires references, append `--require-knowledge`. The main loop accepts a final answer only after search_knowledge returns successfully; zero hits are allowed, but tool errors do not count. Premature answers are deferred and recorded in state.completion_feedback; each correction counts toward max_steps. A budget of 8 is recommended for this acceptance round. The option supports only the DeepSeek Agent and is off by default. It checks that retrieval executed, not hit relevance or factual correctness.

By online record 14, real DeepSeek calls had verified file scanning and knowledge retrieval in one round, plus parameter reading and interpretation boundaries in an artificially constructed message case with ordinary settings. Early retrieval omissions, batch-protocol errors, and fixes are preserved in [Online validation](online-validation.md). This does not establish coverage of every version, mode, or real failure; the raw local database and artificial case directories are not distributed with the repository. Development tests use substitute transports and do not read keys from the user's terminal.

Without API use, retain the default offline mode:

```powershell
& .\.venv\Scripts\python.exe -m vasp_copilot data/local/demo/static_silicon --agent
```

## Run progress

Add `--progress` to an online run to see backend waiting, each tool's start/result, final-answer deferrals caused by unfinished required tools, and Agent completion. Each message shows the decision number and elapsed time; multiple calls in one round show indices such as 1/2 and 2/2. Off by default; unavailable for file scans or history queries.

Stage labels use English to avoid garbled Windows output when Python redirection encoding and terminal encoding differ. Final model answers now default to English unless the user explicitly requests another language; earlier validation used Chinese answers. Concise answers have a soft target of 150 English words, subject to preserving necessary evidence and boundaries. `Waiting for backend decision` indicates backend waiting, `Starting tool` indicates a tool is starting, `Final deferred` indicates a required tool remains to be completed, and `Agent finished` indicates execution has ended.

```powershell
$run = & .\.venv\Scripts\python.exe -m vasp_copilot data/local/demo/static_silicon --agent --backend deepseek --progress --question 'Briefly compare the last sampled step numbers, retrieve relevant explanations, and cite evidence positions.' --require-knowledge --max-steps 8 | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
```

First install and prepare the sample using the homepage, then configure the key in the current terminal. Progress goes to stderr; stdout contains only final JSON. Do not combine the streams with `2>&1` before ConvertFrom-Json. Windows PowerShell may display stderr in red; assess success using final status/error and the exit code.

Elapsed time runs from this Agent's start to the current notification; it is not a per-request duration, completion percentage, or total time limit. There is no periodic refresh during network blocking; backend timeouts and decision budgets retain their existing settings. completed means an answer was produced; tool success means a valid tool result was returned. Neither establishes scientific convergence. Configuration failures happen before Agent creation and retain the original configuration_error.

`Agent finished` appears before optional SQLite storage and means only that the Agent returned a result; check history_record in final JSON to determine whether history was saved.

Progress shows only stages, registered tool names, numbers, and fixed statuses, excluding keys, questions, tool arguments, observation bodies, and model answers. Progress-display exceptions do not overwrite an existing diagnosis; Ctrl+C remains interruptible.

In real run 9 on 2026-10-28, the user's terminal showed backend waiting, start/success for scan_directory and search_knowledge, a second decision, and completed termination. Final JSON parsed successfully and was saved as run_id=9. The user returned a total stage time of approximately 5.2 seconds; progress timings themselves are not in the database snapshot. See [Online validation](online-validation.md) for full acceptance details and remaining issues.

## Errors and troubleshooting

Real online record 7 on 2026-10-26 revalidated the multi-tool fix: decision 1 proposed scan_directory and search_knowledge, both successful; decision 2 produced the answer. --require-knowledge was enabled without needing a pre-completion correction; the case-02 step-alignment conclusion agreed with tool evidence. One success does not establish every protocol branch or service stability; see [Validation record 7](online-validation.md).

| Output | Troubleshooting direction |
| --- | --- |
| configuration_error | Check DEEPSEEK_API_KEY, MODEL, and TIMEOUT; Mock remains available without a key |
| backend_error / DeepSeekAuthenticationError | Authentication failed; check whether the local key is valid |
| backend_error / DeepSeekRateLimitError | Provider rate limit; retry later; the program does not retry automatically |
| backend_error / DeepSeekTimeoutError | Connection or read timeout; check the network and, if needed, adjust DEEPSEEK_TIMEOUT (maximum 120 seconds) |
| backend_error / DeepSeekDNSError | DNS resolution failed; check network and proxy DNS settings |
| backend_error / DeepSeekCertificateError | HTTPS certificate verification failed; check system time and trusted certificates; do not disable verification |
| backend_error / DeepSeekTLSError | TLS handshake or encrypted connection interrupted; check proxy/VPN and retry once the network is stable |
| backend_error / DeepSeekConnectionError | Connection refused or reset; check whether the proxy is running and its port settings |
| backend_error / DeepSeekNetworkError | Other network issue; check current connectivity and system proxy |
| backend_error / DeepSeekHTTPError | Other HTTP errors, such as rejected models/parameters, balance issues, or service faults; this version does not echo the raw service response |
| backend_error / DeepSeekProtocolError | Generic protocol error in older records; the specific cause cannot be reconstructed from it; new code uses the categories below |
| Tool execution_error / PermissionError | A tool tried to read a different directory, or a known file target points outside the directory |

All failures retain completed tool history. API keys do not enter request bodies, status, or tool history; configuration repr hides keys, and network exceptions do not return raw error bodies. Final natural-language answers are model-generated and may be wrong; check them against raw evidence in history. A system prompt is not a guarantee of scientific correctness.

### Protocol error categories (2026-10-25)

The user's online record 3 encountered a generic ProtocolError at decision 1, before any tool calls or completion_feedback. The old record has no raw response, so the precise trigger cannot be determined. This round introduced fixed exception categories whose type names are written to error.message by the existing main loop. All inherit DeepSeekProtocolError to preserve existing exception-handler compatibility.

| error.message | Trigger |
| --- | --- |
| DeepSeekResponseTruncatedError | finish_reason=length; response did not finish completely |
| DeepSeekResponseFilteredError | finish_reason=content_filter |
| DeepSeekResourceInterruptedError | finish_reason=insufficient_system_resource |
| DeepSeekResponseAbortedError | finish_reason=aborted |
| DeepSeekFinishReasonError | Missing or unknown finish reason, or one inconsistent with tool-call structure |
| DeepSeekMultipleToolCallsError | Older versions' error for unsupported multiple calls; identified the cause in online record 6; current versions support at most 8 calls per round |
| DeepSeekToolCallLimitError | More than 8 tool calls in a response; none in the batch execute |
| DeepSeekToolCallFormatError | Tool-call array, IDs, function fields, or related structure violates the contract |
| DeepSeekToolArgumentsError | Tool arguments is not a JSON string parseable as an object; the registry still performs business validation of individual parameters |
| DeepSeekDuplicateToolCallError | Native call IDs duplicate another in the batch or existing history |
| DeepSeekHistoryReplayError | History lacks native IDs, or batches are incomplete or inconsistent in order/metadata; stops before sending a request |
| DeepSeekEmptyAnswerError | Normal stop without a nonempty text answer |
| DeepSeekResponseTooLargeError | Response exceeds the current 2 MiB limit |
| DeepSeekResponseJSONError | HTTP response body cannot be parsed as JSON |
| DeepSeekResponseShapeError | Response object, choices, or assistant-message structure violates the contract |

Finish reasons were checked against the [official DeepSeek Chat Completions response format](https://api-docs.deepseek.com/api/create-chat-completion/). Explicit truncation or interruption takes precedence and is not misclassified as subsequent JSON tool-argument corruption. Diagnostics emit fixed categories only, without saving failed response bodies, arguments, thinking content, or arbitrary server error text; unknown finish_reason values are not echoed either.

This round did not change the model, request parameters, max_tokens=2048, timeout, or retry behavior. --max-steps limits Agent decisions and does not increase a single response's token limit. Another user-run online test is needed to select the next fix based on the new category; the root cause of record 3 had not yet been identified at this point.

On Windows, urllib may also read the system proxy; unset HTTP_PROXY / HTTPS_PROXY variables do not establish that a proxy is unused. For temporary handshake interruption, first confirm stable proxy connectivity and retry once in the original PowerShell window with the key configured. Do not replace a key based only on a network error or disable certificate verification.

If a key-free connectivity probe to the official endpoint receives HTTP 401, that HTTPS request reached the server; it does not establish key validity, balance, model-call success, or the rest of the Agent flow. If both default TLS and TLS 1.2 connect, no fixed TLS version is needed.

## Offline tests

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_deepseek.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

Backend tests use fake transport functions and HTTP responses, including a full “tool request → local execution → observation return → model answer” round trip, plus classification and sensitive-information filtering for connection/read-stage network errors. Tests neither call paid APIs nor require real keys.
