# OUTCAR 与 OSZICAR 采样编号核对

日期：2026-10-24。新增 compare_outputs 工具，默认扫描增加 output_comparison 字段。目标是将两份日志中已有解析器识别的编号与原文并列展示，帮助发现需要进一步核实的差异。这是本项目的保守比较策略，不是新增 VASP 收敛判据。

## 比较什么

| 项目 | OUTCAR 观察 | OSZICAR 观察 | 比较条件 |
| --- | --- | --- | --- |
| ionic_step | 最后识别的 Iteration i(j) 中的 i | 最后保留 F/E0 摘要中的编号 | 两边有可靠记录，没有读取、上下文或解析问题 |
| electronic_step | 上述标题中的 j | 最后保留电子行中的编号 | 上述离子步编号相同，且 OSZICAR 电子行位于保留摘要之前 |

每项包含 status、outcar_value、oszicar_value、两边的 evidence，以及 reason。status 为 matched、mismatched 或 unknown。即使不能比较，也保留已经取得的值和原文，让用户看到缺少什么；不能仅看两列数字而忽略 unknown 和 reason。

没有 OSZICAR 摘要时，不从电子行计数推算离子步；如果两边离子步不同，不直接比较电子编号。只有摘要而没有电子行时，只能比较离子步。OUTCAR 的 EDIFF 消息为 unknown 并不必然阻止编号核对：若标题完整且没有上下文问题，仍能比较其显式编号。

读取错误、OUTCAR 末行截断或冲突消息、OSZICAR issues 等会阻止比较。当前策略也保守地阻止带有 OSZICAR 窗口受限警告的比较，尚未细分可忽略与不可忽略的警告。

汇总 status：任一可比较项不同则 mismatched；两项都相同才 matched；其余 unknown。run_identity 始终 unknown。两份文件按顺序读取，没有跨文件原子快照；文件还在写入时，本次读取可能处于不同时间点。编号相同不证明同次运行或收敛，编号不同也不确定失败或具体原因。

本轮不比较能量、结构、时间戳或完整轨迹。电子行 dE、摘要 d E 和不同能量定义不会被拿来直接对等比较。基础字段的解析范围见 rules.md 和 oszicar.md。

## 直接查看核对结果

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$scan = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' | ConvertFrom-Json
$scan.output_comparison | Format-List status, run_identity
$scan.output_comparison.checks | Format-Table name, outcar_value, oszicar_value, status, reason -Wrap
```

前两行设置运行位置，第三行执行离线目录扫描，最后两行展示汇总及每一项的原因。公开硅样例预期离子步 1 对 1、电子步 13 对 13，status=matched、run_identity=unknown。OUTCAR 证据位于字节 42249；OSZICAR 电子行位于 1156，摘要位于 1236。

unknown 时查看各项 reason，以及 scan.diagnostics.error、scan.diagnostics.last_iteration.issues、scan.oszicar.error/ issues。mismatched 时先核对原文和文件来源，不据此直接修改计算输入。

## Agent、历史与报告

Mock 先检查目录：当 OUTCAR 和 OSZICAR 都可读时，选择 scan_directory，随后按 OUTCAR 观察检索参考资料，最终回答加入编号核对和双方原文。常规路径仍为 4 次决策。只有一个输出文件时保持已有细粒度分支；Mock 不理解自然语言问题。

```powershell
$run = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --save-history | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.state.history | ForEach-Object { $_.call.tool_name }
```

预期工具顺序为 inspect_directory → scan_directory → search_knowledge，最后给出回答。保存成功时 history_record 中有 run_id；可继续用已有 `--export-run` 导出报告。保存失败与 Agent 是否 completed 分开判断，详见 history.md。

DeepSeek 可以选择 compare_outputs 做专门核对，也可以使用 scan_directory 中的 output_comparison。提示要求保留 unknown、不推断原因或运行归属。本轮仅通过模拟传输验证原生工具调用，没有执行在线调用。

Markdown 报告新增并列表格、双方原文及字节位置。导出只使用保存的比较结果，不重新读取源文件，也不按新规则给旧记录补结论。旧快照没有 output_comparison 字段时仍可查询和导出，会说明“未保存输出日志编号核对”；无需迁移数据库。

## 代码阅读顺序

1. schemas.py：OutputStepCheck 定义单项结果，OutputStepComparison 定义汇总；ScanReport 的新字段可选，以兼容旧记录。
2. output_comparison.py：compare_output_steps() 是纯函数，接收两份观察、检查适用条件、比较整数并复制证据；inspect_output_comparison() 是读取两个文件的薄包装。
3. inspection.py：复用本次已读取的观察，不因新增比较再次读取尾部。tools/file_inspection.py 注册 compare_outputs，复用目录限制。
4. agent/mock.py：双输出文件分支选择完整扫描，summarize_comparison() 整理比较说明；agent/deepseek.py 增加工具使用边界。主循环无须修改。
5. reports/generator.py：_output_comparison() 将保存的结果排成表格，不重新计算。

## 验证记录

沿用已固定提交和 SHA-256 的公开 static_silicon OUTCAR/OSZICAR 配对，没有增加下载。tests/test_output_comparison.py 覆盖编号相同、不同、缺失、截断、上下文冲突、新周期、缺少摘要、倒序证据、有限窗口、读取错误与纯函数隔离。

tests/test_output_comparison_integration.py 覆盖真实工具、Mock 完整流程、缺失文件、检索失败、文件在检查后消失、历史快照、报告与模拟 DeepSeek 调用。另将 compare_outputs 加入现有目录边界测试，并更新旧扫描格式兼容测试。编号不一致等异常场景为明确构造的数据，未冒充真实 VASP 故障样例。

本轮新增 29 项测试。定向回归实际为 `125 passed in 8.27s`；完整测试为 `383 passed in 19.31s`。真实公开目录的离线 Mock 完成 4 次决策并导出报告；原有 mock-agent-v1 的 9 个场景继续通过，新双输出分支由本轮集成测试覆盖。没有增加依赖，也没有运行 VASP。
