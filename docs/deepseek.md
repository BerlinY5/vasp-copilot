# DeepSeek 后端：配置与验证

发布说明整理日期：2026-11-01。新用户请先按 [首页](../README.md) 安装并准备公开样例。

接口参考：[首次 API 调用](https://api-docs.deepseek.com/)、[Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。项目默认模型为 deepseek-flash，可通过 DEEPSEEK_MODEL 覆盖；可用模型以服务商账号和接口返回为准。

## 实现范围

- 使用固定官方地址 https://api.deepseek.com/chat/completions，避免误把密钥发送到其他主机；不支持自动重定向。
- 使用 Python 标准库 urllib，无 SDK、新依赖或自动重试。请求非流式响应，thinking=disabled，max_tokens=2048。
- describe() 转换为 DeepSeek tools；模型选择工具，Python 仍通过现有 ToolRegistry 校验和执行。保留原始 call_id 与 assistant_content，后续消息以对应 tool_call_id 回传工具结果。
- 支持一次响应提出 1–8 个函数调用，先校验整批结构、ID 和 JSON 参数，再通过注册表按顺序执行。后续以一条 assistant 消息保留整批原生调用，再逐一回传对应 tool 消息。格式错误拒绝整批；具体工具的参数、路径或执行错误作为各自结果回传，不阻止后续调用。
- 一批计为一次模型决策，最终回答也占一次决策；最多执行 max_steps × 8 次工具调用。同批调用不能依赖尚未返回的其他调用结果，文件读取也不是原子快照。
- 工具历史由应用重建，当前不能将缺少原生 call_id 的 Mock 历史切换给 DeepSeek；每次新运行重建状态。明确关闭思考模式，因此不处理 reasoning_content 的跨轮回传。
- 响应最多读取 2 MiB 加一个探测字节，超限拒绝。timeout 是 urllib 的阻塞网络操作超时，不是整个 Agent 的硬性总时限；最多决策次数仍由 --max-steps 控制。
- CLI Agent 创建的注册表绑定所选目录，所有文件工具都拒绝其他目录，已知 VASP 文件若解析到目录外也拒绝。路径检查不是对并发改动或任意 Python 后端的安全沙箱。

## 本地配置

项目只读取进程环境变量，不自动加载 .env。根目录 .env.example 是无密钥的字段参考，不需要复制或把真实密钥写入源码。

PowerShell：

```powershell
# 在已安装项目的仓库根目录执行
$env:DEEPSEEK_API_KEY = ([System.Net.NetworkCredential]::new('', (Read-Host 'DeepSeek API Key' -AsSecureString))).Password
$env:DEEPSEEK_MODEL = 'deepseek-flash'
$env:DEEPSEEK_TIMEOUT = '30'
```

Read-Host 用隐藏输入读取密钥，命令历史只记录表达式，不包含输入的密钥；密钥随后存在当前进程环境中。不要把密钥粘贴到聊天或提交到 Git。

配置完成后，下面命令会向 DeepSeek 发送真实请求，按服务商规则计费：

```powershell
& .\.venv\Scripts\python.exe -m vasp_copilot data/local/demo/static_silicon --agent --backend deepseek --question '请根据文件证据检查计算状态' --max-steps 8
```

请求内容包括问题、所选目录路径、工具说明和已经执行的工具结果（含文件名、参数、采样证据及错误信息），不主动上传完整计算文件或 POTCAR 内容。先选适合发给该服务的目录进行联调。

问题要求检索资料时，可追加 `--require-knowledge`。主循环要求 search_knowledge 成功返回后才接受最终回答；允许零命中，工具错误不算完成。提前回答会被退回并记录 state.completion_feedback，每次纠正计入 max_steps；建议本轮验收使用 8 次预算。该选项仅支持 DeepSeek Agent，默认不开启。它检查是否执行检索，不保证命中相关性或回答事实正确。

截至第 14 条在线记录，真实 DeepSeek 调用已验证同轮文件扫描与知识检索，以及普通设置人工消息案例中的参数读取和解释边界。早期检索遗漏、批次协议错误与修正过程保留在 [在线验收](online-validation.md)。这不代表所有版本、模式或真实故障已覆盖；原始本地数据库和人工案例目录不随仓库分发。开发测试使用替代传输，不读取用户终端中的密钥。

不使用 API 时保留默认离线模式：

```powershell
& .\.venv\Scripts\python.exe -m vasp_copilot data/local/demo/static_silicon --agent
```

## 运行进度

在线运行加 `--progress`，可在终端看到等待后端、每个工具开始/结果、必需工具未完成导致的最终回答退回，以及 Agent 结束。每条显示决策编号和累计耗时；同轮多调用显示 1/2、2/2 等序号。默认关闭，文件扫描和历史查询不能使用该参数。

阶段标签使用英文，避免 Windows 下 Python 重定向编码与终端编码不同导致乱码；模型最终答案仍按原设置输出中文。`Waiting for backend decision` 表示等待后端，`Starting tool` 表示工具开始，`Final deferred` 表示需要补做必需工具，`Agent finished` 表示执行结束。

```powershell
$run = & .\.venv\Scripts\python.exe -m vasp_copilot data/local/demo/static_silicon --agent --backend deepseek --progress --question '请简洁核对最后采样步编号，并检索相关解释，引用证据位置。' --require-knowledge --max-steps 8 | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
```

先按首页完成安装与样例准备，并在当前终端设置密钥。进度写到 stderr，stdout 只保留最终 JSON；不要用 `2>&1` 将两者合并后交给 ConvertFrom-Json。Windows PowerShell 可能把 stderr 显示为红色，运行是否成功以最终 status/error 和退出码为准。

耗时仅表示从本次 Agent 开始到当前通知的时间；不是单次请求计时、完成百分比或总时限。网络阻塞期间没有周期刷新，后端超时与决策预算沿用原设置。completed 表示完成回答，工具 success 表示返回合法工具结果，都不代表科学计算已收敛。配置阶段失败发生在 Agent 创建前，仍显示原来的 configuration_error。

`Agent finished` 出现在可选的 SQLite 保存之前，仅表示 Agent 已返回结果；历史是否保存成功仍看最终 JSON 的 history_record。

进度仅显示阶段、注册工具名称、编号与固定状态，不包含密钥、问题、工具参数、观察正文或模型回答。进度显示异常不会覆盖已产生的诊断；Ctrl+C 保持可中断。

2026-10-28 第 9 条真实运行中，用户终端显示等待后端、scan_directory 与 search_knowledge 的开始/成功、第二次决策和 completed 结束；最终 JSON 成功解析并保存为 run_id=9。用户回传的阶段总耗时约 5.2 秒，进度时间本身不在数据库快照中。完整验收与剩余问题见 [在线验收](online-validation.md)。

## 错误与排查

2026-10-26 第 7 条真实在线记录完成了多工具修复复验：第 1 次决策提出 scan_directory 与 search_knowledge，两项成功；第 2 次决策输出答案。开启 --require-knowledge，无需结束前纠正，case-02 的编号对齐结论符合工具证据。单次成功不证明所有协议分支或服务稳定性，详见 [第 7 条验收记录](online-validation.md)。

| 输出 | 排查方向 |
| --- | --- |
| configuration_error | 检查 DEEPSEEK_API_KEY、MODEL 和 TIMEOUT；没有密钥仍可用 Mock |
| backend_error / DeepSeekAuthenticationError | 鉴权失败，核对本地密钥是否有效 |
| backend_error / DeepSeekRateLimitError | 服务限流；稍后再试，程序不自动重试 |
| backend_error / DeepSeekTimeoutError | 连接或读取超时；检查网络，必要时调整 DEEPSEEK_TIMEOUT（最大 120 秒） |
| backend_error / DeepSeekDNSError | 域名解析失败；检查网络和代理的域名解析设置 |
| backend_error / DeepSeekCertificateError | HTTPS 证书验证失败；检查系统时间及受信任证书，不要关闭证书校验 |
| backend_error / DeepSeekTLSError | TLS 握手或加密连接中断；检查代理/VPN，网络稳定后重试 |
| backend_error / DeepSeekConnectionError | 连接被拒绝或重置；检查代理是否正在运行及其端口设置 |
| backend_error / DeepSeekNetworkError | 其他网络问题；核对当前连接与系统代理 |
| backend_error / DeepSeekHTTPError | 其他 HTTP 错误，如模型或参数不被接受、余额问题、服务异常；本版不回显原始服务响应 |
| backend_error / DeepSeekProtocolError | 旧记录中的通用协议错误，无法据此回溯具体原因；新代码按下表细分 |
| 工具 execution_error / PermissionError | 工具试图读取不同目录，或已知文件目标指向目录外 |

所有失败保留已经完成的工具历史。API Key 不进入请求正文、状态或工具历史；配置 repr 隐藏密钥，网络异常不回传原始错误体。最终自然语言回答是模型生成内容，可能有误，应以历史中的原始证据核对；系统提示不等于科学正确性保证。

### 协议错误细分（2026-10-25）

用户在线第 3 条记录在第 1 次决策发生通用 ProtocolError，当时尚无工具调用或 completion_feedback。旧记录没有原始响应，不能判断具体触发条件。本轮把错误细分为固定异常类型，由现有主循环将类型名写入 error.message；这些类型均继承 DeepSeekProtocolError，保持已有异常捕获兼容。

| error.message | 触发条件 |
| --- | --- |
| DeepSeekResponseTruncatedError | finish_reason=length，响应未完整结束 |
| DeepSeekResponseFilteredError | finish_reason=content_filter |
| DeepSeekResourceInterruptedError | finish_reason=insufficient_system_resource |
| DeepSeekResponseAbortedError | finish_reason=aborted |
| DeepSeekFinishReasonError | 缺少、未知或与工具调用结构矛盾的结束原因 |
| DeepSeekMultipleToolCallsError | 旧版本不支持多个调用时的错误；第 6 条在线记录据此定位，新版支持每轮最多 8 个调用 |
| DeepSeekToolCallLimitError | 单次响应超过 8 个工具调用，整批不执行 |
| DeepSeekToolCallFormatError | 工具调用数组、ID、函数字段等结构不符合约定 |
| DeepSeekToolArgumentsError | 工具 arguments 不是可解析为对象的 JSON 字符串；具体参数的业务校验仍由注册表完成 |
| DeepSeekDuplicateToolCallError | 原生调用 ID 在同批内重复或与已有历史重复 |
| DeepSeekHistoryReplayError | 历史缺少原生 ID，或批次不完整、顺序/元数据不一致，发送请求前停止 |
| DeepSeekEmptyAnswerError | 正常停止但没有非空文本答案 |
| DeepSeekResponseTooLargeError | 响应超过当前 2 MiB 上限 |
| DeepSeekResponseJSONError | HTTP 响应正文无法解析为 JSON |
| DeepSeekResponseShapeError | 响应对象、choices 或 assistant 消息结构不符合约定 |

结束原因按 [DeepSeek Chat Completions 官方响应格式](https://api-docs.deepseek.com/api/create-chat-completion/) 核对。显式截断或中断优先报告，不误当成后续 JSON 工具参数损坏。诊断只输出固定类别，不保存失败响应的正文、参数、思考内容或任意服务端错误文本；未知的 finish_reason 原文也不回显。

本轮没有修改模型、请求参数、max_tokens=2048、超时或重试行为。--max-steps 限制 Agent 决策次数，不会增加单次响应的 token 上限。需要用户再次在线运行，根据新类别选择后续修复；当前尚未确定第 3 条记录的根因。

Windows 下 urllib 也可能读取系统代理；没有设置 HTTP_PROXY / HTTPS_PROXY 并不代表没有走代理。遇到临时握手中断，先确认代理连接稳定，在原来设置密钥的 PowerShell 窗口重试一次。不要仅凭网络错误更换密钥，也不要关闭证书验证。

不带密钥的官方地址连通性探测若收到 HTTP 401，说明该次 HTTPS 请求已经到达服务器，但不能证明密钥、余额、模型调用或后续 Agent 流程正常。默认 TLS 与 TLS 1.2 均能连通时，无需固定 TLS 版本。

## 离线测试

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_deepseek.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

后端测试使用假传输函数与假 HTTP 响应，包含一次完整的“工具请求 → 本地执行 → 回传观察 → 模型回答”往返，以及连接阶段和读取阶段的网络错误分类与敏感信息过滤。测试不会调用付费接口或需要真实密钥。
