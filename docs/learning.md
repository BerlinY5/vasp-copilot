# 代码学习路线

每一步以能解释具体输入、输出及调用关系为目标。

1. **运行并找到入口**：按 [首页](../README.md) 准备公开样例，阅读
   [`cli.py`](../src/vasp_copilot/cli.py) 的 `main()`，找到普通扫描与 Agent 分支。
2. **先看数据协议，再看工具**：阅读
   [`protocol.py`](../src/vasp_copilot/agent/protocol.py) 中的 ToolCall、ToolResult、AgentState、Finish；
   然后追踪 [`tool_registry.py`](../src/vasp_copilot/agent/tool_registry.py) 的 register、describe、execute，
   对照 [`file_inspection.py`](../src/vasp_copilot/tools/file_inspection.py) 中的 scan_directory 注册。
3. **理解决策循环**：阅读 [`backend.py`](../src/vasp_copilot/agent/backend.py) 与
   [`loop.py`](../src/vasp_copilot/agent/loop.py)，画出“决策→校验→工具→观察→下一轮”。
   对照 [`test_agent_loop.py`](../tests/test_agent_loop.py) 理解决策预算、错误与历史。
   Mock 是用于跟踪执行机制的固定策略后端，不理解自然语言问题。
4. **理解真实模型适配**：从 [`deepseek.py`](../src/vasp_copilot/agent/deepseek.py)
   的 DeepSeekBackend.decide 入手，再读 _history_messages、_parse_decision 和 request_completion。
   理解原生 tool_calls、对应的 tool_call_id 和工具结果回灌。
5. **深入文件证据和参考资料**：从 [`inspection.py`](../src/vasp_copilot/inspection.py)
   追踪输入/输出参数比较、OUTCAR 迭代观察、SCF 设置、局部警告与 OSZICAR 编号比较。
   阅读 [`retriever.py`](../src/vasp_copilot/rag/retriever.py)，区分文件事实、资料摘要及项目规则。
6. **复盘一次运行**：阅读 [`repository.py`](../src/vasp_copilot/storage/repository.py) 和
   [`generator.py`](../src/vasp_copilot/reports/generator.py)，说明哪些内容在运行时保存，哪些仅在导出时格式化。

自测：解释为什么两个电子步编号相同仍可能无法可靠对齐；为什么一次决策可以包含多个工具调用；
为什么工具 success、Agent completed 和科学收敛是不同层面的状态。
