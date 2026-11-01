# 阶段 5：从历史记录导出 Markdown 报告

这一阶段把 SQLite 中的诊断记录整理成可阅读的 Markdown 文件。导出不重新运行 Agent、不访问模型服务、不重新读取计算目录或知识库，不新增依赖。记录中的旧证据、旧回答和旧参考资料均按保存时的内容展示。

## 报告结构

1. 记录编号、UTC 保存时间、后端、Agent 状态和调用次数。
2. 用户问题及当时选择的目录。
3. 每一步工具的调用参数、执行状态和观察：文件清单、OUTCAR 采样范围、标记原文与字节位置、迭代编号、INCAR 原始行、输入输出参数比较等。
4. 知识库条目、来源 URL、本地文档行号与保存时的片段，明确标为通用参考资料。
5. 后端回答原文，明确标为“未自动事实核验”，不重新改写或修正。
6. 运行错误、工具报告的问题及判读边界。
7. 完整保存快照 JSON，方便核对格式化展示是否遗漏信息。

completed 只表示 Agent 产生了回答，不能替换成 VASP 成功。unknown 保持 unknown；缺失文件或未找到标记不自动推断失败。报告不会对模型回答作新的科学保证。

表格中的文本会转义，原始日志、参考片段和后端回答放入文字代码块。代码块围栏会根据内容中的反引号自动加长，避免原文意外改变报告结构。来源 URL 保留为原文，不自动加载网页。分享报告前请留意它含有问题、目录路径和保存的日志片段。

## 新增文件与阅读顺序

- `src/vasp_copilot/reports/generator.py`：render_markdown(record) 是纯格式化函数，只接收 StoredRun；_observation() 按工具名称选择专用视图并复用现有 Pydantic 数据模型；export_markdown() 负责新建 UTF-8 Markdown 文件。
- `src/vasp_copilot/reports/__init__.py`：报告模块的包入口。
- `src/vasp_copilot/cli.py`：新增 --export-run 和 --output；复用历史仓库的只读 get()，不经过 AgentLoop。
- `tests/test_reports.py`：证据、来源、未知状态、原文快照、转义、重复写入与失败清理。
- `tests/test_report_cli.py`：CLI 导出、选项互斥、数据库不变、未知编号和输出路径保护。

旧记录或自定义工具的观察可能不符合当前专用视图。此时报告会明确说明不能生成该摘要，并展示原始 JSON，不猜测缺失字段。损坏的数据库或 AgentRun 本身仍由仓库拒绝读取。

## 从已有历史导出

```powershell
Set-Location D:\projects\vasp-copilot
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')

$history = & .\.venv\Scripts\python.exe -m vasp_copilot --history --limit 5 | ConvertFrom-Json
$history.runs | Format-Table id, backend, status, saved_at

& .\.venv\Scripts\python.exe -m vasp_copilot --export-run 1
```

前两行定位项目和源码；中间两行显示可导出的编号；最后一行导出编号 1，请替换为列表里实际存在的编号。

默认写入当前工作目录下的 reports/generated/run-1.md。在上述用法中它位于项目目录，并被已有 Git 忽略规则覆盖。成功返回 status=exported、run_id 和绝对 path，退出码 0。exported 表示报告已写入，即使保存的 Agent 状态是 backend_error 或 max_steps，也可以正常导出。

## 尚无历史记录时的离线完整演示

```powershell
$saved = & .\.venv\Scripts\python.exe -m vasp_copilot 'D:\projects\vasp-copilot\data\local\public-examples\static_silicon' --agent --save-history | ConvertFrom-Json
$saved.history_record
& .\.venv\Scripts\python.exe -m vasp_copilot --export-run $saved.history_record.run_id
```

先执行上一段的项目定位和 PYTHONPATH 两行。随后第一行运行离线 Mock 并保存，第二行确认 status=saved，第三行按返回编号导出。本流程不需要 API Key。若保存失败，不应继续使用空的 run_id。

## 自定义路径

```powershell
& .\.venv\Scripts\python.exe -m vasp_copilot --export-run 1 --db 'D:\projects\vasp-copilot\data\local\diagnostics.sqlite3' --output 'D:\projects\vasp-copilot\reports\generated\my-report.md'
```

--db 指定已有数据库，--output 指定新的 .md 文件。导出会创建需要的父目录，但不覆盖已有文件；重复导出请换一个文件名。不存在 --force 选项，避免误覆盖手工修改的报告。输出后缀仅接受 .md，不能把 OUTCAR 或数据库误作输出文件。

## 错误与限制

- run_not_found：编号不存在；先查看 --history。
- storage_error / FileNotFoundError：数据库不存在或路径不对；查询和导出都不会创建空数据库。
- report_error / FileExistsError：目标文件已存在，原文件保持不变；请改用新的 --output。
- report_error / ReportPathError：输出不是 .md。
- report_error / PermissionError 或其他 OSError：目录不可写、磁盘错误等；在可处理的写入异常中清理本次新建的半成品文件，并保留异常。断电等不可处理退出不能保证清理。
- 所有失败退出码为 2，错误 JSON 写到 stderr。原数据库保持只读。

当前只导出 Markdown，不生成 PDF、Word 或网页；不重新推理，不核验来源网站现状，不恢复执行失败的 Agent。历史记录中的问题、路径及回答不会自动脱敏。

## 验证

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_reports.py tests/test_report_cli.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

2026-10-24 实际结果：新增 29 项测试，完整回归 `290 passed in 10.31s`。另从上一阶段保存的公开 static_silicon 记录导出 16089 字节的 Markdown 样例，核对 OUTCAR 字节偏移、unknown 状态、参考来源、后端原文和完整快照；导出前后 SQLite 文件 SHA-256 一致。没有调用真实模型或更改计算文件。
