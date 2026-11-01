# 阶段 4：本地知识检索与 Agent

search_knowledge 工具读取随包分发的八篇 Markdown 短文，不联网，不需要 API Key，不使用向量数据库，也不改变现有科学诊断规则。

## 文件证据与知识依据

文件工具回答“这个目录里实际看到了什么”；知识工具回答“这些术语通常是什么意思”。OUTCAR 某一字节位置的 EDIFF 消息是文件证据；EDIFF 的含义来自参考资料。检索到收敛条件不等于证明本次运行收敛。

短文为本项目摘要而非官方全文，2026-10-23 核对来源：[OUTCAR](https://vasp.at/wiki/index.php/OUTCAR)、[EDIFF](https://vasp.at/wiki/index.php/EDIFF)、[EDIFFG](https://vasp.at/wiki/index.php/EDIFFG)；2026-10-26 增补并核对 [OSZICAR](https://vasp.at/wiki/index.php/OSZICAR)；2026-10-28 增补 [INCAR](https://vasp.at/wiki/index.php/INCAR) 设置与输出核对，并新增 [NELM](https://vasp.at/wiki/index.php/NELM) 自洽异常排查说明；2026-10-30 补充 [ICHARG](https://vasp.at/wiki/index.php/ICHARG)、[ALGO/IALGO](https://vasp.at/wiki/index.php/ALGO) 的设置语境，并更新 NELM 条目的项目限制以反映新解析能力。每篇区分“官方资料摘要”和“本项目使用限制”。八篇文档仍不能回答所有 VASP 问题。

OSZICAR 条目针对第 7 次在线运行暴露的参考缺口：解释电子行与摘要字段，并将跨文件编号比较策略明确归属本项目。原查询“OUTCAR OSZICAR 步编号 对齐 离子步 iteration 对应关系”现在可命中 OSZICAR 与 OUTCAR 两篇。该结果只验证检索覆盖；模型是否正确、简洁地引用仍由用户在线复验，不用离线测试代替。

## 文件与阅读顺序

1. `src/vasp_copilot/rag/knowledge/electronic.md`：知识条目示例。前四行依次为标题、Source、Keywords、Reviewed，第五行留空，第六行起是正文。关键词用英文逗号分隔。
2. `src/vasp_copilot/rag/retriever.py`：SearchKnowledgeArgs 校验问题和 top_k；KnowledgeRetriever.search() 有限读取文档、匹配关键词、排序并返回 KnowledgeHit。每篇短文作为一个片段；行号指向本地正文，并非官网行号。
3. `src/vasp_copilot/tools/knowledge_search.py`：把检索注册为统一工具。参数只有 query 和 top_k，模型不能指定任意文件路径。
4. `src/vasp_copilot/tools/file_inspection.py`：create_registry() 在文件工具之外注册 search_knowledge。
5. `src/vasp_copilot/agent/mock.py`：读到 OUTCAR 后根据观察选择检索词，再合并证据说明和来源引用。AgentLoop 无需了解检索实现。
6. `tests/test_knowledge_search.py`：检索边界、来源追溯、观察驱动的主题选择、错误和 CLI 验收。

pyproject.toml 将 Markdown 声明为包数据；importlib.resources 定位内置文档，因此不依赖当前终端目录。root 只作为 Python 开发者/测试注入点，不出现在工具参数中。

## 检索机制与边界

- 中文关键词按子串匹配，英文和参数名忽略大小写并检查词边界；EDIFF 不会误匹配 EDIFFG。
- score 是命中的不同关键词数量，只用于排序，不是置信度或科学正确性概率。相同分数按文件名排序。
- query 最长 500 字符，不能为空白；top_k 为 1–5 的整数，默认 3。无命中返回空 hits，不编造引用。
- 最多 32 篇文档，每篇最多读取 16 KiB 加一个探测字节，正文最多 4000 字符。超限、编码或元数据损坏会成为工具 execution_error，避免静默忽略损坏条目。
- 返回 document、title、source、reviewed_on、excerpt、line_start、line_end、score、matched_keywords；evidence_type 固定为 reference。
- 新结果另含 sections，每段保留 text、line_start/line_end、kind、citation 和 source_url。official_summary 表示有明确标签的官网摘要（项目转述），source_url 指向该笔记声明的官网；project_policy 表示项目限制，只带 VASP-Copilot 笔记与本地行号的 citation，source_url=null。未识别标签的段落记为 unclassified，不提升为官网解释。
- reference_sections() 按空行分段并读取段首标签，行号与原始正文逐字对应；它只识别策划笔记中的标签，不自动验证陈述是否得到官网支持。新条目仍需人工核对。原有 excerpt/source 保留以兼容已有消费者，source 字段不代表支持整篇笔记中的项目规则。
- 报告按保存时的 sections 分别展示官网摘要和项目限制；旧命中没有 sections 时默认空列表，显示原片段与原来源并说明缺少分段归属，不用当前文档补写历史。新版字段通过现有工具观察进入模型和 SQLite，无需数据库迁移；自然语言最终引用是否正确仍需在线验收。
- 这是关键词检索，不是语义理解；未收录的同义词可能没有命中。新增主题时需补充来源、适用范围、别名和测试。
- 没有自动抓取网页、下载资料或执行文档中的指令。真实模型是否正确使用引用仍需人工验收，提示词不是事实核验器。

## Mock 新流程

```text
inspect_directory
  ├─ OUTCAR 可读 → diagnose_outcar
  │    ├─ 解析报告错误 → 解释错误并结束
  │    └─ 获得观察 → search_knowledge → 分开呈现文件证据与通用解释
  ├─ 仅 INCAR 可读 → inspect_incar → 解释输入意图
  └─ 均不可读 → 解释证据不足
```

电子消息状态不是 unknown 时检索 EDIFF；观察到离子停止标记时检索 EDIFFG；两者同时出现则查询两个主题；都没有时查询 OUTCAR。知识检索失败或无命中时，保留文件观察并说明参考资料不可用。

Mock 仍是固定条件策略，不理解用户自然语言。标准 OUTCAR 分支需要 4 次决策（检查、解析、检索、最终回答），INCAR 分支 3 次，空目录 2 次；默认上限 6 足够。DeepSeek 能看到同一工具定义，但由模型按需选择，流程可能不同。

## PowerShell 离线验收

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$result = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --max-steps 6 | ConvertFrom-Json
$result | Format-List status, decision_steps, answer, error
$result.state.history | ForEach-Object { $_.call.tool_name }
```

前两行定位项目并设置源码搜索路径；第三行运行默认离线 Mock，并把 JSON 转成 PowerShell 对象。第四行显示可读中文回答，第五行查看工具顺序。预期 status=completed、decision_steps=4，顺序为 inspect_directory、diagnose_outcar、search_knowledge。completed 仅表示完成回答，总体科学状态保持 unknown。

可将 static_silicon 改成 relaxation 比较两个样例。不要为运行演示改动原始 INCAR 或 OUTCAR。

## 在线验收

在已经设置 DEEPSEEK_API_KEY 的同一个终端、完成上述前两行后执行：

```powershell
$result = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --backend deepseek --question '请先检查目录和 OUTCAR，再使用 search_knowledge 查询相关解释。回答中分别列出文件证据、参考来源和仍不确定的事项。' --max-steps 6 | ConvertFrom-Json
$result | Format-List status, decision_steps, answer, error
$result.state.history | ForEach-Object { $_.call.tool_name }
```

这会产生真实 API 用量。验收时检查：是否使用文件工具和 search_knowledge、是否引用具体文件位置及知识来源、是否把通用资料误当作本次收敛证明。2026-10-24 用户回传了一次 completed 回答，但未附完整工具历史；人工复核发现回答质量问题，详见 evaluation.md。不能仅由最终回答引用 EDIFF 就认定实际调用过 search_knowledge。

来源归属也需要验收：“官方资料摘要”是项目转述，不能当作官方逐字引语；“本项目使用限制”属于 VASP-Copilot 的实现策略，不能归因于官方来源。知识工具 notice 和模型提示已明确这一点，但仍需核对真实回答。

## 测试

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_knowledge_search.py tests/test_agent_loop.py tests/test_deepseek.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

覆盖中英文查询、参数词边界、无命中、排序和 top_k、非法参数、有限读取、来源与正文行号、检索失败保留证据、CLI 离线运行，以及通过假 DeepSeek 传输验证原生工具调用的检索结果回传。不发送真实 API 请求。

本阶段开发验证记录（2026-10-23）：完整测试实际输出 `219 passed in 2.91s`。static_silicon 与 relaxation 两份公开样例均在 4 次决策内 completed，分别检索到电子说明和电子/离子说明；运行前后样例文件 SHA-256 一致。项目虚拟环境缺少 setuptools，首次离线构建失败；改用系统已有的构建工具后成功生成 wheel，并在隔离源码搜索路径后从 wheel 内直接检索到知识文档。没有安装或升级项目依赖。
