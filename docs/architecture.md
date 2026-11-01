# Agent 架构：工具注册、决策循环、知识检索、历史与报告

当前已有工具层、可替换决策接口、Mock 循环、DeepSeek 适配器和本地知识检索。原有 CLI 默认直接扫描目录；--agent 默认离线，额外指定 --backend deepseek 才访问模型服务。2026-10-24 用户回传一次 completed、4 次决策的在线回答；完整工具历史未提供，人工复核发现回答质量问题，详见 evaluation.md。

## 调用路径

```text
create_registry()
  → 注册 scan_directory、inspect_directory、diagnose_outcar、inspect_incar、inspect_oszicar、compare_outputs、search_knowledge

registry.execute("scan_directory", {"directory": "..."})
  → 从字典找到 ToolDefinition
  → ScanDirectoryArgs 校验参数
  → 调用 scan(args)
  → 复用 inspection.scan_directory()
  → ScanReport 校验输出并转为 JSON 数据
  → ToolResult 返回 success/data 或 error/error
```

## 文件职责

- agent/protocol.py：ToolResult 是 Observation。status=success 要有 data 且无 error；status=error 要有 error 且无 data。ToolCall / ToolBatch / Finish 是带 type 判别字段的决策；ToolBatch 包含 2–8 个 ToolCall。ToolEvent 保存一次调用和观察；AgentState 保存问题、目录和历史；AgentRun 保存终止状态与最终回答。
- agent/tool_registry.py：ToolDefinition 用 dataclass 保存名称、说明、两个模型类型和函数引用。ToolRegistry 用字典查找工具，通过装饰器注册。describe() 输出独立的 JSON Schema，尚未绑定某家模型 API 格式。
- tools/file_inspection.py：定义 ScanDirectoryArgs、DirectoryInventory，把已有读取函数适配为六个文件工具。inspect_directory 只探测文件，不提前解析整个报告；细粒度解析工具允许 Mock 按结果选择。create_registry() 每次返回独立实例。
- tests/test_tool_registry.py：使用一个测试专用 double 工具验证通用机制，再用真实扫描适配器验证集成。double 不会注册到生产实例。

## 为什么用装饰器

`@registry.register(...)` 会先产生一个装饰器，再将紧接着定义的函数传给它。装饰器把函数和参数模型存入字典，返回原函数。注册只是记录函数，不会立即扫描文件。

工具函数统一接收一个校验后的模型对象。execute() 不需要针对每个工具写 if/else；新增工具只需定义模型、写函数并注册。

## 返回语义

| error.kind | 含义 | 调用者应检查什么 |
| --- | --- | --- |
| unknown_tool | 名称未注册 | describe() 中的工具名称 |
| invalid_arguments | 参数未通过模型校验 | 缺失字段、类型、多余字段 |
| execution_error | 工具执行抛出普通异常 | 消息中的异常类型；如 FileNotFoundError 时核对目录 |
| invalid_result | 返回形状错误或无法转换为 JSON | 工具实现是否遵守结果模型 |

成功指工具执行并产出合法数据，不等于 VASP 计算成功。目录存在但 OUTCAR 缺失仍可能返回工具 success，缺失证据在 data 内说明。

参数模型继承 Schema，严格校验并禁止多余字段。校验错误不包含原始输入值；执行异常只报告类型，避免将任意内部异常内容直接送给后续模型。开发者可以用 logging 观察名称、开始、完成和错误类别；不记录参数值或完整报告。KeyboardInterrupt 等 BaseException 不会被吞掉。

## PowerShell 试运行

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& .\.venv\Scripts\python.exe -c "from vasp_copilot.tools.file_inspection import create_registry; r=create_registry(); print([t['name'] for t in r.describe()]); result=r.execute('scan_directory', {'directory': '.'}); print(result.status); print(result.data['calculation_status'])"
& .\.venv\Scripts\python.exe -m pytest tests/test_tool_registry.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

前三行分别切换目录、设置源码搜索路径、创建注册表并扫描项目根目录。预计输出七个工具的名称列表、`success`、`unknown`。项目根目录没有 VASP 数据也可完成扫描。最后两行分别运行工具层测试和完整测试。若找不到包，检查 PYTHONPATH；若返回 execution_error，检查目录存在性和权限。

## 当前边界与下一步

仅执行开发者明确注册的同步 Python 函数，不执行模型生成的代码或任意 Shell 命令。注册表不是安全沙箱；当前工具使用本地进程拥有的读取权限。尚无异步执行或强制超时控制；持久化历史由 CLI 显式启用，见下文。

## Mock 循环

```text
AgentLoop.run(question, directory)
  → 新建 AgentState
  → backend.decide(状态深拷贝, 工具说明)
  → Pydantic TypeAdapter 校验 ToolCall / ToolBatch / Finish
      ToolCall → registry.execute → 追加 ToolEvent → 再次决策
      ToolBatch → 按顺序执行各调用并追加 ToolEvent → 再次决策
      Finish → completed + answer
  → 决策次数耗尽：max_steps；后端抛异常或决策非法：backend_error
```

backend.py 的 Protocol 规定 decide() 方法签名，不要求后端继承具体类。循环只依赖这个接口和 ToolRegistry。MockBackend 通过 history[-1].observation 决策，循环本身不知道 VASP 文件名，也不知道应该调用哪个工具。

Mock 的实际分支：

- 无历史：inspect_directory。
- 文件检查完成：OUTCAR 与 OSZICAR 都可读则 scan_directory；否则 OUTCAR 可读则 diagnose_outcar；否则 OSZICAR 可读则 inspect_oszicar；否则 INCAR 可读则 inspect_incar；否则解释证据不足。
- OUTCAR 解析结果返回：根据电子消息和离子停止标记选择 EDIFF、EDIFFG 或 OUTCAR 主题，调用 search_knowledge 后再组织保守说明；实际原文、偏移和错误在历史中保留。INCAR 分支直接解释输入意图。
- 工具错误：说明后结束；解析器内部 error 也检查，避免把工具 success 等同于文件解析成功。

question 仅保存，不作自然语言理解；工具定义虽传给后端，Mock 的策略使用预先约定的工具名。它是离线验收后端，不伪装成 LLM。

决策步数包含 final，默认最多 6 次，上限 100。工具错误可作为 Observation 交给后端修正，测试后端会依据 invalid_arguments 修正一次参数；默认 Mock 不重试。后端异常、无效 type、错误字段会停止循环，且不会执行该非法决策。KeyboardInterrupt 保持可中断。深拷贝保护的是状态记录，不是对任意 Python 后端的沙箱隔离。

DeepSeek 在线验收可用 --require-knowledge 声明结束前的工具要求。CLI 把 search_knowledge 作为 AgentLoop.required_tools 传入；循环接受 final 前检查真实成功工具历史，未满足则追加 CompletionFeedback 并继续决策。拒绝 final 仍消耗预算，未生成伪工具事件，故 ToolEvent.step 可出现间隔。要求和纠正记录保存在 AgentState，旧快照默认为空列表。DeepSeek 请求携带这些要求、实际检索计数与当前纠正信息；检索零命中可以结束，但应如实说明。详见 online-validation.md。

tests/test_agent_loop.py 中的核心验收使用同一 Mock、同一问题和两个目录，分别得到 inspect_directory → diagnose_outcar → search_knowledge 与 inspect_directory → inspect_incar 两条调用历史。另验证空目录、读取期间文件消失、错误恢复、步数限制、历史隔离和 CLI 退出码。

## 运行阶段通知

agent/progress.py 定义冻结的 ProgressEvent 和进度回调类型，仅包含阶段、决策编号/上限、同轮工具序号、已注册工具名称和固定状态；不持有 AgentState、问题、参数或 Observation。StderrProgressReporter 接收 CLI 提供的 stderr 流，用 monotonic 计算累计耗时，每条通知立即刷新。

AgentLoop 的可选 on_progress 在决策开始、工具执行前后、最终回答被退回和正常返回运行结果前通知观察者。通知普通异常只记录固定警告，不改变诊断结果；KeyboardInterrupt 继续传播。进度不进入模型请求、数据库快照或报告，不影响决策预算，也不提供自动重试、周期心跳或强制超时。等待阶段直到后端返回才会出现下一条通知。

cli.py 的 --progress 仅为本次 Agent 运行创建显示对象，不安装全局 logging handler；默认关闭，历史查询拒绝该参数。原注册表日志对未知工具名也使用固定占位符，避免将模型生成的任意名称写入日志；未知名称仍按原机制作为工具错误保留在诊断历史中。

## DeepSeek 适配层

config.py 从进程环境读取密钥、模型名和超时，避免读入整个环境或自动加载私有文件。agent/deepseek.py 实现同一个 decide() 接口：将状态历史转换为 messages，将工具定义转换为 functions，通过可注入的 HTTP 传输函数获取响应，再转换为 ToolCall、ToolBatch 或 Finish。

ToolCall 新增可选 call_id、assistant_content，Mock 不依赖它们；DeepSeek 必须保留它们以回放真实工具调用及对应 Observation。循环本身不依赖 DeepSeek 的请求格式，测试可以替换传输函数而不访问网络。

一批工具占一次决策；同批 ToolEvent.step 相同，batch_index 从 1 开始，batch_size 为整批大小。旧记录缺少批次字段时默认 1/1，无需数据库迁移。DeepSeek 回放按 step 分组，一条 assistant 消息携带整批原生调用，后跟每项 tool 结果；批次缺失、乱序或 ID 重复时拒绝发送。报告显示同轮调用序号。

整批结构与 JSON 校验在执行前完成；注册表仍逐项处理业务参数和目录约束，某项工具错误不撤销已完成观察，也不阻止后续项执行。同批工具串行运行，没有原子快照保证。每轮最多 8 项，最后一个允许的决策也执行完整合法批次，之后没有预算生成最终回答时返回 max_steps。Mock 策略仍只返回单个工具调用。

CLI 创建绑定目录的 ToolRegistry。目录检查在执行函数之前生效，六个文件工具复用同一检查函数；不依赖模型遵守提示。模型提示要求引用证据并区分观察与推断，但模型自然语言结论尚无自动事实校验。

工具说明明确返回范围与重叠：compare_outputs 适合单独核对步编号；scan_directory 一次返回文件清单、输入设置、OUTCAR 参数摘要、两份日志观察和编号比较。diagnose_outcar 不提取前缀 IBRION/NSW，inspect_directory 只探测文件。需要讨论模式参数时应获取 scan_directory.output_context；仅回答编号问题时不必添加模式讨论。提示鼓励复用已有观察、按缺口追加工具，不强制固定调用顺序，也不在运行时拦截重复读取。工具选择与自然语言的证据边界仍须在线验收。

配置和上线验证步骤见 deepseek.md。测试不需要密钥；实际联调需用户在本地配置 DEEPSEEK_API_KEY。最新在线发现与针对性回归结果见 online-validation.md。

## 本地知识工具

tools/knowledge_search.py 注册知识检索工具，复用同一参数校验、Observation 和历史机制，AgentLoop 不作改动。rag/retriever.py 用关键词匹配包内 Markdown 短文，返回正文、本地行号、官方来源和 evidence_type=reference。知识检索不接收目录参数、不读取用户计算文件、不联网。

Mock 根据文件观察选择主题，检索失败时仍保留文件证据。DeepSeek 提示明确要求分别引用文件证据和参考资料，但自然语言结论尚无自动事实校验。资料格式、模块阅读顺序及验收命令见 [本地检索说明](rag.md)。

## SQLite 持久化

```text
CLI --agent [--save-history]
  → AgentLoop.run()
  → AgentRun（成功、达到上限或后端错误）
  → 若显式保存：RunRepository.save(run, backend)
  → 原运行结果 + history_record 保存状态

CLI --history / --show-run ID
  → RunRepository 以 mode=ro 查询 SQLite
  → 摘要列表 / 经过校验的 AgentRun 快照
```

storage/repository.py 定义 RunSummary、StoredRun 和 RunRepository。使用单张 runs 表，摘要列方便列表查询，run_json 保留完整工具历史与引用。参数化 SQL 防止问题文本被当作语句；事务保证保存整体提交或回滚；连接显式关闭，避免 Windows 文件锁残留。

数据库标识和版本不匹配时拒绝操作。列表不读取大 JSON，详情读取后用 AgentRun 验证并检查摘要一致性。查询不执行工具、不加载模型配置、不重新扫描文件，也不创建缺失数据库。

CLI 仅在 --save-history 时添加 history_record，不改变 AgentLoop 或 AgentRun。保存失败仍向用户返回已产生的回答，并单独标记存储错误。当前保存的是最终快照，尚无逐步提交、历史重放或恢复执行。详细用法见 [诊断历史](history.md)。

## 报告导出

```text
CLI --export-run ID [--db PATH] [--output FILE.md]
  → RunRepository.get(ID)，只读数据库并校验历史
  → render_markdown(StoredRun)，纯格式化
  → export_markdown()，以独占新建方式写入 UTF-8 文件
  → exported + run_id + path
```

reports/generator.py 从保存的 Observation 生成专用视图，复用既有数据模型，分别呈现文件证据、知识参考与后端原文。不增加科学判定，不执行工具，也不重新读取当前知识库。专用视图不支持或格式不匹配的观察明确回退到原始 JSON；完整保存快照放在报告末尾。

文本表格转义与自适应代码围栏使日志和后端原文作为文字展示。export_markdown 只写新 .md 文件，不覆盖旧报告；正常可捕获写入失败会尝试清理本次半成品。CLI 把输出错误与数据库错误分开报告，保留原记录。详情见 [报告导出](reports.md)。

## 离线场景评估

```text
python -m vasp_copilot.evaluation
  → cases.load_samples() 核验公开样例大小和 SHA-256
  → cases.build_scenarios() 构造 16 个场景及固定预期（mock-agent-v2）
  → runner.evaluate() 创建临时目录
      → run_scenario() 写入场景副本，创建受目录约束的注册表
      → AgentLoop + MockBackend（异常场景注入测试后端）
      → check_run() 对照预期，拆出完整扫描中保存的各类观察
      → observations.py 核对 OSZICAR 数值、编号比较及双方证据原文位置
      → 核验输入文件未改变
  → EvaluationReport：逐项 expected / actual / passed 与总计
  → 可选新建 JSON 文件；自动清理临时场景
```

evaluation/cases.py 将样例来源、人工变换及预期观察放在一起；预期值来自已人工核对的固定日志，不由当前解析器生成。runner.py 负责实际调用和评分，observations.py 核对保存的输出观察，不重新读取当前文件或调用解析器；__main__.py 负责参数、JSON 输出和退出码，与日常诊断 CLI 分开。v2 保留原有 9 个场景，并补充 OSZICAR 单文件、双文件一致、不一致、截断及证据不足等 7 个场景。

评估模块复用现有 Agent 与工具，不需要修改主循环、数据库或模型配置。它使用明确的 Mock 工具顺序检查回归，不适合直接给自由选择工具的真实模型评分。现阶段只检查回答存在性和参考 URL 的包含关系，没有语义判分。失败后查看具体检查项，不应直接把当前实际值改成预期值。详见 evaluation.md。

## OSZICAR 观察接入

oszicar.inspect_oszicar() 读取末尾有限字节并生成 OszicarObservation。schemas.py 分别定义电子行、能量摘要和 OSZICAR 证据，不扩大原 OUTCAR Evidence 的文件类型。ScanReport.oszicar 为可选字段，使旧快照仍能校验；新扫描主动填入观察或读取错误。

普通扫描和 inspect_oszicar 工具复用同一解析器。Mock 在没有可读 OUTCAR 时增加 OSZICAR 分支；DeepSeek 可根据问题选择新工具。报告的 _oszicar() 只处理保存的观察，分别展示电子行与摘要，不从当前文件补全旧记录。调用方式和字段说明见 oszicar.md。

## 电子循环局部诊断

electronic_diagnosis.py 的 diagnose_electronic_step() 是纯函数，接收 iterations.py 已解析的 IterationObservation，检查标题、唯一消息、issues 和偏移顺序，返回 ElectronicStepDiagnosis。它不读文件、不重算能量、不解析参数；诊断证据深拷贝自原观察。diagnostics.py 在一次既有尾部读取后调用该函数，diagnose_outcar 与组合扫描自动携带结果。

schemas.py 用 reported_not_reached、not_triggered、unknown 区分局部结果，severity 仅在警告时为 warning；整体三类状态继续为 unknown。reports/generator.py 展示该结果、影响和建议，字段缺失或读取失败时明确未生成/未保存，不重算旧快照。DeepSeek 的工具说明和提示要求解释局部警告，不把三类总体 unknown 当成没有任何可报告的问题。Mock 策略未扩展，测试替代传输只验证消息和保存流程，真实解释效果仍由用户在线验收。

## 输出日志编号比较实现

output_comparison.py 的 compare_output_steps() 是纯比较函数，复用 OutputDiagnosis 与 OszicarObservation，并复制原文证据。它先处理错误和上下文问题，再比较离子编号；只有离子编号相同且 OSZICAR 行顺序可靠时才比较电子编号。inspect_output_comparison() 为独立工具读取两份文件。

scan_directory 复用当前已经解析的观察生成 output_comparison，不再次读取尾部。Mock 在两份输出都可读时选择完整扫描，检索完成后同时解释 OUTCAR 与比较结果；检索失败仍保留文件证据。DeepSeek 可以独立调用 compare_outputs。新字段在 ScanReport 中可选，旧记录不追补新结论；报告支持专用比较表格。详见 output-comparison.md。

## 电子自洽设置驱动的核查建议

scf_settings.py 的 observe_electronic_settings() 只解析调用者提供的有限字节，精确分标签和分号段，分别记录五项值、状态和证据。run_start_offsets() 识别受限运行标题，帮助发现已知跨运行风险；它不能完整验证运行身份。

diagnostics.py 通过同一文件句柄读取前缀与尾部，检查读取长度、大小和时间戳后，把设置观察传给 electronic_diagnosis.py。diagnose_electronic_step() 保持原消息结果，再据可靠采样值生成 settings_considerations 和具体核查建议；发现运行边界问题时不应用这些设置。报告展示保存的参数表、证据与条件性说明，模型通过原有工具结果获得同样内容。既有 input_context/output_context/context_comparison 仍只处理 IBRION/NSW，不将新增设置混入旧比较。

schemas.py 的 ElectronicSetting/ElectronicSettings 定义观察，ElectronicSettingConsideration 定义带证据的条件说明。OutputDiagnosis 新字段默认 null，ElectronicStepDiagnosis 新列表默认空；读取旧记录不重新扫描、不改旧答案。此阶段没有新增依赖、工具名称或 Mock 策略。
