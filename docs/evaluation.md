# 验证记录：解析器与在线回答

> 本文保留各阶段验证记录，文中测试数量属于对应日期，并非当前全量数量。
> 当前安装与公开样例复现见 [首页](../README.md)，最新在线验收见 [第 14 条记录](online-validation.md)。

日期：2026-10-23。

## 数据来源

采用 [pymatgen 固定提交的公开测试目录](https://github.com/materialsproject/pymatgen/tree/682bfd855dd89264b0ff8d6bee4815f8834cc5ac/tests/files/io/vasp/fixtures) 中两份 OUTCAR，标题均为 VASP 5.2.12。精确来源及哈希见 tests/fixtures/pymatgen/manifest.json，MIT 许可随样例保留。

## 人工核对的预期观察

| 样例 | IBRION | NSW | 最后离子步编号 | 最后电子步编号 | EDIFF 消息 | 计时标题 | 结构优化停止消息 |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| static_silicon | -1 | 0 | 1 | 13 | 达到消息 | 有 | 无 |
| relaxation | 2 | 99 | 3 | 4 | 达到消息 | 有 | 有 |

静态样例没有结构优化停止消息不代表失败。两个样例仍保持总体收敛结论 unknown；本次验证的是解析和证据关联，不是独立复算科学结果。

## 验证覆盖

- 两份完整公开日志各验证一次 SHA-256 和大小，各验证一次参数、迭代消息、标记及证据字节位置：4 项。
- 从优化日志截断到第 3 个离子步的第 1 个电子步标题，确认不会沿用第 2 个离子步消息：1 项。
- 追加另一运行的真实标题，确认清空前一运行关联：1 项。
- 拼接两份完整日志，确认最后标题来自后一个样例且偏移为拼接文件绝对位置：1 项。
- 真实 OUTCAR 配人工最小 INCAR 的 CLI 集成：1 项。

新增 8 项，连同既有 90 项共 98 项。测试均离线运行，依赖仍为现有 pytest、Pydantic 和 Python 标准库，没有安装 pymatgen。

## 复现

在项目根目录执行：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_real_outcar.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

前者运行 8 项公开样例回归，后者运行当前全部测试（阶段 2 完成时为 98 项，知识检索接入后为 219 项）。缺少样例或完整性测试失败时，检查文件是否齐全及 manifest，勿修改预期哈希掩盖数据变化。

## 尚未验证

未在本地运行 VASP；未独立确认上游样例的全部计算设置和科学正确性。两个日志同属 VASP 5.2.12，不能代表 VASP 6、不同输出详细程度、分子动力学、响应计算、真实未收敛或异常终止场景。派生截断测试不能替代真实异常日志验证。

下一阶段若增加适用范围更强的结论，需补充具有明确来源和模式信息的其他版本及异常日志。

## 2026-10-24 用户回传的在线回答

测试对象为 public-examples/static_silicon。用户提供 status=completed、decision_steps=4、error 为空及最终回答，没有提供该次完整 state.history。可确认该次运行生成了回答；不能仅凭回答中的工具名称和引用确认精确工具顺序或检索调用。此前网络/协议错误未证明已根治，不能由一次成功推断持续稳定。

人工核对到的积极结果：回答区分程序结束、电子收敛和离子收敛，保留工具的 unknown，并引用了 OUTCAR 的字节位置。日志对应位置与既有公开样例一致。

发现的问题与修正要求：

| 问题 | 正确边界 |
| --- | --- |
| “若为优化则显然未完成” | 未发现离子停止标记不能证明优化未完成或失败；条件句也不能绕过证据要求 |
| 将 reached_marker 的保守处理归到 VASP Wiki | 这是本项目策略；官方参数说明与项目使用限制必须分别归属，摘要不是官方逐字引语 |
| 目录名 static 和最后 Iteration 1 被用于推断类型/总步数 | 目录名不能作为科学证据，last_iteration 只给最后识别编号，不提供全文件迭代统计 |
| 因 INCAR 缺失断言无法取得 IBRION/NSW | 现有 scan_directory 的 output_context 可以提取 OUTCAR 前缀采样参数；本样例中明确存在 IBRION=-1、NSW=0 |
| 声称采样没有覆盖全文件 | 该样例为 61474 字节，小于尾部读取上限；读入全文与完成全部语义解析不同，后者仍未实现 |
| 把 EDIFF 消息直接解释为物理条件已验证 | 现有工具只验证看到了消息，不重算能量变化，也未验证所有模式 |

对应修改：收紧 DeepSeek 系统提示，要求需要判定模式时先检查 OUTCAR 采样参数；知识工具 notice 明确来源归属。没有放宽 unknown 状态，也没有修改科学解析规则。提示词只能引导回答，不能替代自动事实校验。

下一次在线验收需保存最终回答及工具调用顺序，确认上述问题不再出现，尤其检查 scan_directory 的参数观察是否被正确引用。修改后的在线效果尚未验证。

本轮修改后执行模型适配和知识检索回归，实际输出 `78 passed in 1.43s`，未重复运行其余测试。另用现有 scan_directory 核对：NSW=0 的证据位于 OUTCAR 字节偏移 10918，IBRION=-1 位于 11031；尾部诊断 read_start=0、bytes_read=snapshot_size=61474。全部操作离线，没有改动样例。

## 离线 Agent 场景评估（2026-10-24）

2026-10-25 已取得另一轮完整的 DeepSeek 在线记录：2 次决策、1 次 scan_directory，没有知识检索；答案存在虚称检索、字段和数量错误、采样范围过度推断。接口运行完成但质量验收未通过。具体记录、修正与下一轮用户复验见 [在线验收](online-validation.md)。以下固定 Mock 评估不能替代该验收。

当前为 `mock-agent-v2` 评估集，把散布在单元测试中的关键行为串成可独立运行、可保存结果的固定场景。它保留 v1 的 9 个场景，新增 OSZICAR 和双日志的 7 个场景，共 16 个。它复用真实 AgentLoop、工具注册表、文件解析和本地检索，不依赖 pytest、API Key 或网络。评估对象是当前 Mock 策略；自然语言问题不会改变 Mock 的决策。既有 v1 报告仍是历史记录，不会被本次评估覆盖。

| 场景 | 数据来源 | 预期行为 |
| --- | --- | --- |
| static_silicon | 固定版本公开 OUTCAR | 检查→解析→EDIFF 检索→回答；保留整体 unknown |
| relaxation | 固定版本公开 OUTCAR | 同时检索 EDIFF 与 EDIFFG，保留对应证据 |
| truncated_output | relaxation 前 81109 字节，人工截断 | 最后识别 3(1)，无该步 EDIFF 消息，不沿用上一步 |
| incar_only | 人工构造 IBRION=2、NSW=20 | 选择 inspect_incar，输出输入意图 relaxation |
| invalid_incar | 人工构造无效 UTF-8 | 保留 UnicodeDecodeError 与 unknown |
| empty_directory | 人工构造空目录 | 一次文件检查后结束，不调用不存在的文件解析 |
| missing_directory | 人工构造缺失路径 | 保留 execution_error / FileNotFoundError 并结束 |
| step_limit | 公开静态样例，预算仅一步 | max_steps，保留一次观察，不生成最终回答 |
| backend_failure | 在第二次决策注入 RuntimeError | backend_error，保留第一次观察，不生成最终回答 |
| oszicar_only | 固定版本公开 OSZICAR | 选择 inspect_oszicar，核对电子行、能量摘要和原文 |
| paired_outputs | 固定版本公开 OUTCAR / OSZICAR 配对 | 选择 scan_directory；离子编号 1/1、电子编号 13/13，matched |
| ionic_mismatch | 人工将 OSZICAR 摘要编号 1 改为 2 | 离子编号 mismatched；即使电子编号 13/13 也保持 unknown |
| electronic_mismatch | 人工将最后电子编号 13 改为 12 | 离子编号 matched、电子编号 mismatched |
| truncated_oszicar | 人工删除 OSZICAR 最后一字节换行 | 清除旧候选并保留 issues；两个核对项均 unknown |
| missing_oszicar_summary | 人工在 OSZICAR 字节 1236 前截断 | 保留电子行，缺少摘要；不推算离子编号，两项 unknown |
| unsupported_oszicar | 人工在完整 OSZICAR 后追加 MD 形式记录 | 当前解析器不支持该格式，清除此前候选并保留 unknown |

通过意味着满足场景预期。例如 backend_failure 的场景 status=passed，表示检测到了预期的 backend_error 并保留历史，不表示后端实际成功。

### 实际检查内容

共同检查运行状态、决策次数、工具顺序、工具错误、历史步号、问题和目录是否保留、回答是否存在，以及运行前后的文件指纹。OUTCAR 场景另外检查最后迭代、标记状态、采样覆盖、证据数量、字节位置与原文是否对应、三个整体结论是否保持 unknown。INCAR 场景检查输入类型、参数和原始行；检索检查预期文档、来源 URL、reference 标签，以及回答是否包含来源 URL。

OSZICAR 场景检查保留行的编号、各数值、原文位置、采样范围、错误与 issues 是否存在，以及整体结论仍为 unknown。双日志场景还检查比较汇总、每项编号与状态、双方证据和非空原因；run_identity 必须为 unknown。即使最终回答正常产生，数值或证据有误仍判为失败。原因文字仅检查存在性，不自动评判其自然语言含义。

报告带有固定样例提交号与 SHA-256：两个 OUTCAR 解压后内容，以及已有的 static_silicon.OSZICAR（1314 字节）。评估首先按固定文件名有限读取并核验大小和哈希；任一样例缺失或改变时拒绝开始。预期值与偏移沿用已人工核对的公开日志，截断位置也直接核对原始字节。公开数据仍保留原有许可和 manifest，不下载新增数据集。

评分只使用保存的观察、固定预期和场景原始字节，不重新调用被测解析器来生成“正确答案”。独立 OSZICAR 工具与 scan_directory 内的同类观察共用评分逻辑，保证完整扫描不会绕开证据检查。每次运行仍核验临时输入副本未被修改。

### PowerShell 运行

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$evaluation = & .\.venv\Scripts\python.exe -m vasp_copilot.evaluation | ConvertFrom-Json
$evaluation | Format-List suite, status, total, passed, failed
$evaluation.cases | Format-Table name, status
```

前两行确定项目和源码路径，第三行运行评估并把 JSON 转为 PowerShell 对象，最后两行显示汇总与场景列表。预期汇总为 mock-agent-v2 / passed / 16 / 16 / 0。正常场景在临时目录中完成并自动清理，不会写入诊断历史库。

需要保存详细结果时，选择尚不存在的输出文件：

```powershell
$evaluation = & .\.venv\Scripts\python.exe -m vasp_copilot.evaluation --output 'reports\generated\my-evaluation.json' | ConvertFrom-Json
$evaluation.cases | Where-Object status -ne 'passed' | ConvertTo-Json -Depth 20
```

第一行同时保存 UTF-8 JSON 与返回结果；第二行展开失败场景，没有失败则不输出。每个检查项的 name 表示检查内容，expected 是预期值，actual 是本次实际值。文件名可以自行修改，重复使用已有路径会拒绝覆盖。

| 退出码 / 错误 | 含义与处理 |
| --- | --- |
| 0 | 全部场景符合预期 |
| 1 | 至少一个场景未通过或运行中异常；查看失败检查项与 case.error |
| 2、fixture_error | 样例缺失或哈希不同；核对 --fixtures 路径和原始样例，不要改哈希掩盖问题 |
| 2、evaluation_output_error | 输出已存在或无法写入；选择新 .json 文件或可写目录 |
| 2、evaluation_error | 临时目录等基础文件操作失败；检查本地权限与空间 |

命令需要完整源码仓库中的 tests/fixtures/pymatgen；测试数据没有打入 Python 安装包。从其他工作目录运行时添加 `--fixtures 'D:\projects\vasp-copilot\tests\fixtures\pymatgen'`。主入口只导入 Mock 与评估功能，不加载模型配置；默认抑制预期异常场景的日志，检查结果和错误仍在 JSON 中。

### 源码阅读与验证

先读 evaluation/cases.py 的 Scenario、build_scenarios() 和 _output_scenarios()，理解“输入、预期、来源”如何描述一个场景；再读 runner.py 的 run_scenario() 和 check_run()，理解“执行与评分分离”；observations.py 专门核对保存的 OSZICAR 与比较观察，_evidence_valid() 检查证据是否指向原始文件中的完整行；最后读 __main__.py 的输出和退出码处理。__init__.py 仅说明包职责。

v1 新增的 22 项测试保留，包括故意篡改证据偏移、证据文字、证据数量、工具顺序、整体状态、引用来源、回答引用、输入文件和问题的 9 类故障。另验证样例损坏/超限、离线可重复性、不读取模型配置、单场景异常后继续、KeyboardInterrupt 传播、输出文件不覆盖及失败写入清理。

v1 阶段完整测试为 `312 passed in 10.08s`。v2 增加 tests/test_evaluation_outputs.py：20 类完整扫描结果篡改、4 个将不确定结果擅自改为 matched 的场景、4 类 OSZICAR 样例缺失或损坏，以及评分不重读文件、不调用解析器和场景字节变换检查，共新增 30 项测试。

2026-10-25 完成 v2 验证：定向测试 `52 passed in 34.64s`，完整测试 `413 passed in 52.94s`，固定场景 16/16 通过。重复运行得到相同报告，原始样例保持不变。全部离线，无新依赖，没有运行 VASP 或调用 DeepSeek。

### 解释限制

16/16 是这十六个固定场景的通过数，不是现实计算成功率或 LLM 准确率。人工改编号、截断、追加格式、解码错误和注入异常不是真实 VASP 失败日志；仍缺少多版本、多模式和真实异常样本。编号相同不证明运行归属或收敛；不同也不确定失败或原因。包含来源 URL 不代表自然语言推断正确，评估不检查引文含义、回答是否过度断言或所有科学结论。先前在线回答发现的问题仍需真实模型复验。

Mock 顺序或工具契约有意改变时，应先核实新行为的理由，再人工更新预期并修改 suite 版本，不能用当前输出自动刷新基准。
