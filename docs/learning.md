# Code learning path

At each step, aim to explain the concrete inputs, outputs, and call relationships.

1. **Run the project and find the entry point**: prepare the public sample using the [homepage](../README.md), read
   `main()` in [`cli.py`](../src/vasp_copilot/cli.py), and locate the normal scan and Agent branches.
2. **Read the data protocols before the tools**: read ToolCall, ToolResult, AgentState, and Finish in
   [`protocol.py`](../src/vasp_copilot/agent/protocol.py);
   then trace register, describe, and execute in [`tool_registry.py`](../src/vasp_copilot/agent/tool_registry.py),
   alongside the scan_directory registration in [`file_inspection.py`](../src/vasp_copilot/tools/file_inspection.py).
3. **Understand the decision loop**: read [`backend.py`](../src/vasp_copilot/agent/backend.py) and
   [`loop.py`](../src/vasp_copilot/agent/loop.py), and diagram “decision → validation → tool → observation → next round.”
   Use [`test_agent_loop.py`](../tests/test_agent_loop.py) to understand decision budgets, errors, and history.
   Mock is a fixed-policy test backend for tracing the execution mechanism; it does not understand natural-language questions.
4. **Understand the real model adapter**: start with DeepSeekBackend.decide in
   [`deepseek.py`](../src/vasp_copilot/agent/deepseek.py), then read _history_messages, _parse_decision, and request_completion.
   Understand native tool_calls, their corresponding tool_call_id values, and how tool results return to the model.
5. **Explore file evidence and reference material**: from [`inspection.py`](../src/vasp_copilot/inspection.py),
   trace input/output parameter comparison, OUTCAR iteration observations, SCF settings, local warnings, and OSZICAR step comparison.
   Read [`retriever.py`](../src/vasp_copilot/rag/retriever.py), distinguishing file facts, source summaries, and project policy.
6. **Review a run**: read [`repository.py`](../src/vasp_copilot/storage/repository.py) and
   [`generator.py`](../src/vasp_copilot/reports/generator.py), and explain what is saved at run time and what is only formatted during export.

Self-check: explain why equal electronic step numbers may still be impossible to align reliably; why a decision can contain multiple tool calls;
and why tool success, Agent completed, and scientific convergence describe different kinds of status.