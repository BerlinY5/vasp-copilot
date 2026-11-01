# OSZICAR 观察工具

日期：2026-10-24。新增 inspect_oszicar 工具，以及默认目录扫描中的 oszicar 字段。工具读取指定目录的 OSZICAR，输出有限范围内支持的电子行和能量摘要，保留原文和零起始字节偏移。它不改变既有总体收敛判断。

## 格式依据与支持范围

格式依据为 [VASP Wiki：OSZICAR](https://vasp.at/wiki/index.php/OSZICAR)，本次核对页面版本 oldid=29868。下述字段含义是转述，解析限制属于本项目。

电子行支持 DAV、RMM、CG 前缀，依次读取电子步编号、E、dE、d eps、ncg、rms 和可选 rms(c)。E 是当前自由能，dE 是电子步间自由能变化，d eps 是能带能量变化。能量单位为 eV。ncg 计数、残差和电荷差单独记录，不把它们当作收敛阈值。

能量摘要支持 `编号 F=数值 E0=数值 d E=数值`。F 是自由能，E0 对应 sigma 趋零的能量；摘要 d E 的含义依赖计算模式，因此输出字段命名为 reported_delta_energy_ev，与电子行 delta_energy_ev 分开。可接受一个或三个数值的 mag 尾缀，仅校验数值格式并保留原文，不解释磁矩。

支持 E/e 和 D/d 指数、前导小数点、正负号、LF/CRLF、文件起始 UTF-8 BOM。NaN、Inf、星号溢出、浮点溢出或非零值下溢、负残差、零步号、多余列等不会被当作有效观察。

分子动力学 T/E/F/E0 格式、其他算法标签、机器学习力场的专用语义和非标准格式尚不支持。不从文件名或数值猜测这些模式，也不自动核对 OSZICAR 与 OUTCAR 是否来自同一次运行。

## 读取与状态

- 最多读取末尾 64 KiB；记录 read_start、bytes_read、snapshot_size。受限窗口的第一行可能不完整，因此保守跳过。
- 只解释完整换行的记录。每次最多保存一条电子行和一条摘要，不返回完整轨迹或统计总步数。
- 新电子表头清空旧候选；摘要后的新电子行清除旧摘要。连续摘要不沿用旧电子行。
- 未支持、损坏、无效编码或末行截断都会清空之前的候选，并记录 issues。后续完整有效行可以成为新的候选，警告仍保留。
- status=observed 仅表示当前保留了支持的行；unknown 表示没有保留有效候选。三个总体状态 electronic_convergence、ionic_convergence、normal_termination 始终 unknown。
- 缺失或不可读文件记录在 error；工具外层 success 只表示成功生成报告，不能代替检查内部 error。

因此，最后保留的编号不能解释成整份文件的总步数，观察到 F/E0 摘要也不能升级为本项目已验证的收敛结论。文本按原样保存；数值使用有限 Python 浮点数，原始精度表示可在 evidence.text 核对。

## 离线查看现有硅样例

无需密钥，直接运行普通扫描：

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$scan = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' | ConvertFrom-Json
$scan.oszicar | Format-List status, read_start, bytes_read, snapshot_size, error
$scan.oszicar.last_electronic_step | Format-List algorithm, iteration, energy_ev, delta_energy_ev
$scan.oszicar.last_energy_summary | Format-List ionic_step, free_energy_ev, energy_sigma0_ev, reported_delta_energy_ev
```

前两行设置项目和源码位置，第三行检查现有公开目录，后面展示 OSZICAR 的解析摘要。该样例预期：完整读取 1314 字节，RMM 电子步编号 13，电子行位于字节 1156，摘要位于 1236；F=E0=-10.645278 eV。三个总体状态仍 unknown。查看 `.evidence` 可获取对应原文。

## Agent 和报告

Mock 在 OUTCAR 与 OSZICAR 均可读时选择完整扫描，随后检索资料并回答，共 4 次决策；只有 OUTCAR 可读时保留原有解析与检索流程。没有可读 OUTCAR 而有 OSZICAR 时，调用 inspect_oszicar 后给出带字节证据的说明，共 3 次决策。之后才考虑 INCAR。Mock 不会根据自然语言问题强制换工具。两份日志的编号比较见 [输出日志编号核对](output-comparison.md)。

已在当前 PowerShell 配置密钥时，可运行：

```powershell
$run = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --backend deepseek --question '请使用 inspect_oszicar 查看电子迭代行和能量摘要，引用文件字节位置，区分电子行 dE 与摘要 d E，不把日志观察当作收敛证明。' --max-steps 6 --save-history | ConvertFrom-Json
$run | Format-List status, decision_steps, answer, error
$run.state.history | ForEach-Object { $_.call.tool_name }
```

这条命令会实际调用模型服务；本轮没有执行在线验证。模型是否选择该工具应查看 state.history。对于你的环境，之前关闭 VPN 后曾成功在线运行；这不是所有网络环境的通用要求。

历史保存继续使用原有 SQLite 快照。Markdown 报告为 inspect_oszicar 和 scan_directory 新增专用展示，分别列出电子行与摘要，附原文和来源。旧扫描记录没有 oszicar 字段时会说明“未保存解析”，不会误称文件缺失，不需要迁移数据库。

## 源码阅读顺序

1. schemas.py：OszicarEvidence、OszicarElectronicStep、OszicarEnergySummary、OszicarObservation；字段约束避免不合法数值进入工具观察。
2. oszicar.py：inspect_oszicar() 有限读取后逐行识别；clear() 管理旧候选；_number() 排除不可表示的数值。
3. inspection.py 和 tools/file_inspection.py：将解析器分别接入普通扫描及工具注册表，共用目录限制。
4. agent/mock.py 和 agent/deepseek.py：前者增加 OSZICAR 分支，后者告知模型新工具与判读限制；AgentLoop 本身无须修改。
5. reports/generator.py：_oszicar() 从保存的数据格式化报告，不重新读取文件。

## 验证记录与边界

公开 OSZICAR 来自此前下载的 pymatgen 固定提交，与 tests/fixtures/pymatgen/manifest.json 的 oszicar_samples 条目对应。文件 1314 字节、SHA-256 为 1e3f219d8da90386d1f354cb7a8476084a7f4aea0d43514a21eda19d18c3664f。原样复制到回归目录，没有重新下载或改写换行，沿用随目录提供的上游 MIT 许可。

tests/test_oszicar.py 检查真实字节、能量值、截断、新周期、错误数字、有限读取、读取中变短等；tests/test_oszicar_integration.py 检查 CLI、Mock、原生工具调用的模拟传输、SQLite、报告和旧记录。test_deepseek.py 增加新工具的目录边界测试。

本轮新增 42 项测试。针对解析、集成、模型适配与报告运行 `107 passed in 5.03s`；完整测试实际为 `354 passed in 31.46s`。原有 mock-agent-v1 的 9 个场景继续通过，OSZICAR 新分支由本轮测试覆盖，尚未加入该固定评估集。

所有验证均离线，没有增加依赖，没有运行 VASP，也没有用真实模型评判回答。当前只有一个公开静态 OSZICAR 样例，其他格式边界以明确构造的数据测试；这不能代表多版本、多模式的全面验证。
