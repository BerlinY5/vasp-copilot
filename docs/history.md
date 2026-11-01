# 阶段 5：SQLite 诊断历史

本阶段增加基本保存与查询。数据库使用 Python 标准库 sqlite3，不需要安装服务器或新依赖。原有扫描及 Agent 命令保持兼容；只有显式添加 --save-history 才会写入历史。

## 保存什么

每条记录包含数据库内唯一的整数编号、UTC 保存时间、后端名称、用户问题、计算目录、运行状态、决策次数、工具调用数量，以及完整的 AgentRun JSON 快照。JSON 保存实际工具调用、参数、观察、检查过的文件、证据位置、参考来源、最终回答和错误。

数据库不会另行打开或复制完整计算文件，也不会保存后端配置、API Key 或整个环境变量。问题、目录路径、日志采样和回答本身会被保留；不要把密钥写进问题。历史是当次记录，不会随源文件后续变化更新，也不证明科学结论正确。

保存时间是完成运行后入库的时刻，不是 VASP 计算时间或 Agent 开始时间。当前记录后端类别 mock/deepseek，不包含模型版本、费用或每步耗时。

completed、max_steps、backend_error 都可以保存。密钥配置错误发生在 AgentRun 创建之前，因此不入库；进程强制退出或用户中断也不保证留下记录。本版本没有逐步检查点或断点续跑。

## 文件职责与阅读顺序

1. `storage/repository.py` 中的 RunSummary、StoredRun：分别表示列表摘要与完整记录；完整运行数据复用已有 AgentRun。
2. RunRepository.save()：序列化快照，通过带占位符的 SQL 插入记录；一个事务中完成初始化与写入，失败回滚，最后关闭连接。
3. RunRepository.list_runs() / get()：以 SQLite mode=ro 打开数据库。列表只查询摘要，按编号倒序返回；详情校验 JSON 和摘要是否一致。查询不创建数据库，不运行模型或工具。
4. `cli.py`：解析保存/查询选项，将 AgentLoop 的结果交给仓库；循环本身不依赖 SQLite。
5. `tests/test_storage.py` 与 `tests/test_history_cli.py`：覆盖记录往返、证据和引用保留、SQL 特殊字符、只读查询、失败回滚、损坏记录与 CLI 兼容性。

表名为 runs。application_id 标识本项目数据库，user_version=1 标识当前结构；不兼容的版本或其他应用的数据库会被拒绝，不自动迁移或覆盖。SQL 中的问题、路径、ID 和 limit 均通过参数传入，不拼接为命令。

## 离线运行并保存

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$result = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --save-history | ConvertFrom-Json
$result | Format-List status, decision_steps, history_record
```

前两行定位项目和源码；第三行使用离线 Mock 完成诊断并保存；第四行显示运行状态及保存编号。默认数据库为当前工作目录下的 data/local/diagnostics.sqlite3，在上述用法中位于项目目录中，已经被现有 Git 忽略规则覆盖。

预期顶层 status=completed、decision_steps=4，history_record.status=saved，并返回 run_id、saved_at、database。每次保存新增一条记录，不覆盖前次记录。

## 查询最近记录和完整过程

```powershell
$history = & .\.venv\Scripts\python.exe -m vasp_copilot --history --limit 5 | ConvertFrom-Json
$history.runs | Format-Table id, saved_at, backend, status, decision_steps, tool_calls

$record = & .\.venv\Scripts\python.exe -m vasp_copilot --show-run $result.history_record.run_id | ConvertFrom-Json
$record.run.answer
$record.run.state.history | ForEach-Object { $_.call.tool_name }
```

前两行列出最近五条摘要；后三行使用上次保存的编号读取完整记录、中文回答和工具顺序。关闭终端后数据库仍保留；重新打开窗口时需再次设置 PYTHONPATH，并把详情命令中的编号改为列表中实际存在的编号，例如 --show-run 1。查询无需密钥，也不会产生 API 用量。

--history 默认列出最近 10 条，--limit 支持 1–100；暂无分页、筛选、删除或导入命令。--show-run 只读取历史，不重新执行诊断。

## 指定其他数据库

```powershell
& .\.venv\Scripts\python.exe -m vasp_copilot --history --db 'D:\projects\vasp-copilot\data\local\diagnostics.sqlite3'
```

--db 可与 --save-history、--history 或 --show-run 配合；保存和查询必须指向同一个文件。只接受 .sqlite3、.sqlite、.db 后缀，避免把 OUTCAR 等文件误用为数据库。相对路径相对于当前终端目录；从其他目录查询时建议使用绝对路径。

## 在线运行

在已设置密钥、且当前电脑关闭 VPN 后可正常联通的终端，把此前成功的在线命令追加 --save-history 即可，例如：

```powershell
$result = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --backend deepseek --question '请检查文件证据，查询相关参考资料，并区分观察与推断。' --max-steps 6 --save-history | ConvertFrom-Json
$result | Format-List status, decision_steps, history_record, error
```

真实模型调用仍产生服务商用量。即使后端错误，也可通过保存的 run_id 查看错误前已完成的工具历史。关闭 VPN 是用户当前环境中观察到的可用条件，不是通用网络要求。

## 输出兼容性与错误

未指定 --save-history 时，原有 Agent JSON 不增加字段，也不创建数据库。指定后增加 CLI 层的 history_record；AgentRun 与 AgentLoop 的接口不变。

- 诊断 completed 且保存成功：退出码 0。
- 诊断 max_steps / backend_error，即使保存成功：退出码仍为 2。
- 保存失败：保留完整运行结果和回答，history_record.status=error，包含安全的错误类型，退出码 2。顶层 completed 只表示诊断完成，不能据此认为入库成功。
- 查询失败：错误 JSON 写到 stderr，退出码 2；run_not_found 表示编号不存在。
- 数据库不存在：FileNotFoundError，先保存一条记录或核对 --db 路径；查询不会自动创建空库。
- StoragePathError：使用允许的数据库后缀。
- StorageSchemaError：数据库不属于本项目或版本不兼容，换一个新路径；不要删除原库来掩盖问题。
- OperationalError：可能是数据库锁定或目录不可写；连接最长等待锁约 5 秒，诊断回答仍保留在终端结果中。
- StorageRecordError / DatabaseError：记录或数据库损坏，不返回伪装成有效的数据。

## 测试

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_storage.py tests/test_history_cli.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

第一条验证仓库和 CLI，第二条检查整个项目。测试使用临时目录和数据库，不读取真实密钥、不调用付费 API、不改动公开样例。

2026-10-24 实际验证：新增 42 项测试，完整回归输出 `261 passed in 8.06s`。使用公开 static_silicon 样例运行 CLI，得到 completed、4 次决策和保存编号 1；再用两个独立进程分别列出记录、按编号读取，确认回答与工具顺序一致，OUTCAR 的 SHA-256 未变。演示数据库位于开发临时目录，没有复制进主项目。真实 DeepSeek 加保存选项的联合运行尚未执行；保存层通过依赖注入测试覆盖后端错误记录，在线账号可用性仍以用户本机验证为准。
