"""Render saved evidence without re-running tools or promoting model claims."""

import html
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..rag.retriever import KnowledgeSearchResult
from ..schemas import InputContext, OszicarObservation, OutputDiagnosis, OutputStepComparison, ScanReport
from ..storage.repository import StoredRun
from ..tools.file_inspection import DirectoryInventory


class ReportPathError(RuntimeError):
    pass


def _cell(value: Any) -> str:
    text = "unknown" if value is None else str(value)
    text = html.escape(text, quote=False).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", text)
    return text.replace("\n", "<br>")


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _fenced(text: str, language: str = "text") -> str:
    # Untrusted text cannot close its fence and inject headings, links or raw HTML.
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _json(value: Any) -> str:
    return _fenced(json.dumps(value, ensure_ascii=False, indent=2), "json")


def _evidence(item: dict[str, Any]) -> str:
    return f"文件：{_cell(item['file'])}；零起始字节偏移：{item['byte_offset']}。\n\n{_fenced(item['text'])}"


def _inventory(data: dict[str, Any]) -> list[str]:
    return ["**文件清单**", _table(["文件", "检查状态", "存在", "可读取", "错误"], [
        [item["name"], item["status"], item["exists"], item["readable"], item["error"] or "—"]
        for item in data["files"]
    ])]


def _diagnosis(data: dict[str, Any]) -> list[str]:
    parts = ["**OUTCAR 采样与状态**", _table(["字段", "工具记录值"], [
        [key, data[key]] for key in ("read_start", "bytes_read", "snapshot_size", "normal_termination", "electronic_convergence", "ionic_convergence")
    ]), "字节读取范围不等于完整内容解析；标记和迭代编号不等于整体收敛结论。"]
    if data["error"]:
        parts.extend(["文件解析错误：", _json(data["error"])])
    parts.append(_table(["规则", "观察状态", "证据数量"], [
        [finding["rule_id"], finding["status"], len(finding["evidence"])] for finding in data["findings"]
    ]))
    for finding in data["findings"]:
        parts.append(f"规则说明：{_cell(finding['rule_id'])}")
        parts.append(_fenced(finding["explanation"]))
        parts.extend(_evidence(item) for item in finding["evidence"])
        if finding["sources"]:
            parts.extend(["规则参考来源（不是本次计算证据）：", _fenced("\n".join(finding["sources"]))])
    iteration = data["last_iteration"]
    parts.extend(["**最后可识别迭代**", _table(["离子步编号", "电子步编号", "消息状态"], [
        [iteration["ionic_step"], iteration["electronic_step"], iteration["status"]]
    ])])
    if iteration["header"]:
        parts.append(_evidence(iteration["header"]))
    parts.extend(_evidence(item) for item in iteration["markers"])
    if iteration["issues"]:
        parts.extend(["工具记录的不确定性：", _json(iteration["issues"])])
    parts.extend(["迭代观察范围：", _fenced(iteration["explanation"])])
    if iteration["sources"]:
        parts.extend(["迭代解析参考来源：", _fenced("\n".join(iteration["sources"]))])
    settings = data["electronic_settings"]
    if settings is None:
        parts.append("此记录未生成或未保存电子自洽设置观察，不从当前文件补写。")
    else:
        parts.extend(["**OUTCAR 前缀电子自洽设置**", _table(["前缀读取字节", "文件快照大小", "窗口受限", "循环关联"], [[
            settings["bytes_read"], settings["snapshot_size"], settings["window_limited"], settings["iteration_association"],
        ]]), _table(["参数", "采样状态", "值", "出现次数"], [
            [p["name"], p["status"], p["value"], p["occurrences"]] for p in settings["parameters"]
        ]), _fenced(settings["explanation"])])
        for parameter in settings["parameters"]:
            parts.append(f"参数 {_cell(parameter['name'])}：")
            parts.extend(_evidence(e) for e in parameter["evidence"])
            if parameter["issues"]:
                parts.append(_json(parameter["issues"]))
        if settings["issues"]:
            parts.extend(["设置上下文问题：", _json(settings["issues"])])
    local = data["electronic_step_diagnosis"]
    if local is None:
        parts.append("此记录未生成或未保存电子循环局部诊断，不使用当前规则追补历史。")
    else:
        parts.extend(["**最后采样电子循环的局部诊断**", _table(["规则", "局部状态", "级别", "范围"], [[
            local["rule_id"], local["status"], local["severity"], local["scope"],
        ]]), _fenced(local["summary"])])
        if local["impact"]:
            parts.extend(["影响与风险：", _fenced(local["impact"])])
        parts.extend(_evidence(item) for item in local["evidence"])
        if local["recommendations"]:
            parts.extend(["建议人工核查（不会自动修改参数）：", _fenced("\n".join(local["recommendations"]))])
        if local["settings_considerations"]:
            parts.append("结合前缀设置的条件性说明（不证明属于该循环）：")
            for consideration in local["settings_considerations"]:
                parts.append(_fenced(consideration["summary"]))
                parts.extend(_evidence(e) for e in consideration["evidence"])
        parts.extend(["局限：", _fenced("\n".join(local["limitations"])),
                      "规则依据（不替代本次文件证据）：", _fenced("\n".join(local["sources"]))])
    return parts


def _input_context(data: dict[str, Any]) -> list[str]:
    parts = [f"**INCAR 输入意图：{_cell(data['calculation_type'])}**", _table(["参数", "值", "一基行号", "原始行"], [
        [item["name"], item["value"], item["line_number"], item["text"]] for item in data["parameters"]
    ])]
    if data["issues"] or data["error"]:
        parts.extend(["输入解析问题：", _json({"issues": data["issues"], "error": data["error"]})])
    parts.extend([_fenced(data["explanation"]), "输入参数参考来源：", _fenced("\n".join(data["sources"]))])
    return parts


def _oszicar(data: dict[str, Any]) -> list[str]:
    parts = ["**OSZICAR 电子迭代与能量摘要**", _table(["字段", "工具记录值"], [
        [key, data[key]] for key in ("status", "read_start", "bytes_read", "snapshot_size",
                                    "electronic_convergence", "ionic_convergence", "normal_termination")
    ]), "observed 仅表示识别到支持的日志行。电子行 dE 与摘要 d E 分开呈现，不由数值大小判定收敛。"]
    electronic, summary = data["last_electronic_step"], data["last_energy_summary"]
    if electronic:
        parts.extend(["最后保留的电子迭代行：", _table(
            ["算法", "电子步编号", "E (eV)", "dE (eV)", "d eps (eV)", "ncg", "rms", "rms(c)"],
            [[electronic[key] for key in ("algorithm", "iteration", "energy_ev", "delta_energy_ev",
                                          "delta_band_energy_ev", "ncg", "rms", "rms_charge")]]),
            _evidence(electronic["evidence"])])
    if summary:
        parts.extend(["最后保留的能量摘要行：", _table(
            ["离子步编号", "F (eV)", "E0 (eV)", "摘要 d E (eV)"],
            [[summary[key] for key in ("ionic_step", "free_energy_ev", "energy_sigma0_ev", "reported_delta_energy_ev")]]),
            _evidence(summary["evidence"])])
    if not electronic and not summary:
        parts.append("当前记录没有保留可解释的完整电子行或能量摘要；不能据此判定计算失败。")
    if data["issues"] or data["error"]:
        parts.extend(["OSZICAR 读取或格式问题：", _json({"issues": data["issues"], "error": data["error"]})])
    parts.extend([_fenced(data["explanation"]), "格式参考（非本次计算证据）：", _fenced("\n".join(data["sources"]))])
    return parts


def _output_comparison(data: dict[str, Any]) -> list[str]:
    parts = [f"**输出日志采样编号核对：{_cell(data['status'])}**",
             f"同次运行归属：{_cell(data['run_identity'])}。编号相同不证明收敛或同次运行，编号不同不证明失败或具体原因。",
             _table(["检查项", "OUTCAR 编号", "OSZICAR 编号", "核对状态", "说明"], [
                 [item["name"], item["outcar_value"], item["oszicar_value"], item["status"], item["reason"]]
                 for item in data["checks"]
             ])]
    for item in data["checks"]:
        parts.append(f"{_cell(item['name'])} 的原文证据：")
        for key in ("outcar_evidence", "oszicar_evidence"):
            if item[key]:
                parts.append(_evidence(item[key]))
    parts.append(_fenced(data["explanation"]))
    return parts


def _observation(tool_name: str, data: dict[str, Any]) -> list[str]:
    models = {"inspect_directory": DirectoryInventory, "diagnose_outcar": OutputDiagnosis,
              "inspect_incar": InputContext, "inspect_oszicar": OszicarObservation,
              "compare_outputs": OutputStepComparison, "scan_directory": ScanReport,
              "search_knowledge": KnowledgeSearchResult}
    model = models.get(tool_name)
    if model is None:
        return ["该工具没有专用报告视图，保留其原始观察：", _json(data)]
    try:
        data = model.model_validate(data).model_dump()
    except ValidationError:
        return ["该工具记录不符合当前报告视图的数据格式，不据此生成摘要；原始观察如下：", _json(data)]
    if tool_name == "inspect_directory":
        return _inventory(data)
    if tool_name == "diagnose_outcar":
        return _diagnosis(data)
    if tool_name == "inspect_incar":
        return _input_context(data)
    if tool_name == "inspect_oszicar":
        return _oszicar(data)
    if tool_name == "compare_outputs":
        return _output_comparison(data)
    if tool_name == "scan_directory":
        parts = [f"**工具记录的计算状态：{_cell(data['calculation_status'])}**"]
        parts.extend(_inventory(data))
        parts.extend(_input_context(data["input_context"]))
        output = data["output_context"]
        parts.extend(["**OUTCAR 前缀参数观察**", _table(["参数", "采样值", "字节偏移", "原始行"], [
            [item["name"], item["value"], item["evidence"]["byte_offset"], item["evidence"]["text"]]
            for item in output["parameters"]
        ]), "参数读取范围及问题：", _json({key: output[key] for key in ("read_start", "bytes_read", "window_limited", "issues", "error")}),
            "**输入与输出采样值比较**", _json(data["context_comparison"])])
        parts.extend(_diagnosis(data["diagnostics"]))
        if data["oszicar"] is not None:
            parts.extend(_oszicar(data["oszicar"]))
        else:
            parts.append("此历史扫描记录未保存 OSZICAR 解析，不能据此推断当时文件缺失。")
        if data["output_comparison"] is not None:
            parts.extend(_output_comparison(data["output_comparison"]))
        else:
            parts.append("此历史扫描记录未保存输出日志编号核对，不使用当前文件或规则追补结论。")
        return parts
    parts = ["**知识库参考资料（非计算文件证据）**", _fenced(data["notice"])]
    if not data["hits"]:
        parts.append("本次检索没有命中参考条目；这不表示计算异常。")
    for hit in data["hits"]:
        parts.extend([
            f"条目：{_cell(hit['title'])}；本地文档：{_cell(hit['document'])}；一基行号：{hit['line_start']}–{hit['line_end']}。",
            f"资料核对日期：{_cell(hit['reviewed_on'])}；类型：reference。",
        ])
        if hit["sections"]:
            for section in hit["sections"]:
                label = {"official_summary": "官方资料摘要（项目转述）",
                         "project_policy": "本项目使用限制", "unclassified": "归属未分类"}[section["kind"]]
                parts.extend([f"**{label}**", "本地引用标识：", _fenced(section["citation"])])
                if section["source_url"] is not None:
                    parts.extend(["此段对应的官网来源：", _fenced(section["source_url"])])
                parts.append(_fenced(section["text"]))
        else:
            parts.extend(["此历史记录没有按段归属，不从当前知识库补写；保留原始片段与来源字段。",
                          "资料来源 URL（不代表支持整段项目限制）：", _fenced(hit["source"]),
                          "保存时的参考片段：", _fenced(hit["excerpt"])])
    return parts


def render_markdown(record: StoredRun) -> str:
    """Pure formatting: uses only the saved record, with no filesystem or API reads."""
    summary, run = record.summary, record.run
    parts = ["# VASP-Copilot 诊断报告", _table(["项目", "保存值"], [
        ["记录编号", summary.id], ["保存时间（UTC）", summary.saved_at], ["后端", summary.backend],
        ["Agent 运行状态", run.status], ["决策次数", run.decision_steps], ["工具调用次数", len(run.state.history)],
    ]), "completed 仅表示 Agent 已生成回答，不表示 VASP 计算成功或收敛。报告基于保存时的记录，不反映源文件之后的变化。",
        "## 用户问题", _fenced(run.state.question), "## 当时选择的目录", _fenced(run.state.directory),
        "## 工具证据与参考资料"]
    if not run.state.history:
        parts.append("本次运行未记录工具观察；没有可由工具核对的文件证据。")
    for event in run.state.history:
        position = f"（同轮调用 {event.batch_index}/{event.batch_size}）" if event.batch_size > 1 else ""
        parts.extend([f"### 步骤 {event.step}{position}：{_cell(event.call.tool_name)}",
                      f"工具执行状态：{_cell(event.observation.status)}。success 仅表示工具产生了合法报告。",
                      "调用参数：", _json(event.call.arguments)])
        if event.observation.status == "error":
            parts.extend(["工具错误：", _json(event.observation.error.model_dump())])
        else:
            parts.extend(_observation(event.call.tool_name, event.observation.data))
    if run.state.required_tools:
        parts.extend(["## 结束前的工具要求", _json(run.state.required_tools),
                      "这些工具必须成功返回后才接受最终回答。检索允许零命中；通过要求不证明检索相关性或回答正确。"])
    if run.state.completion_feedback:
        parts.extend(["## 提前结束的纠正记录",
                      "以下记录表示当时缺少必需工具调用；被拒绝的回答未作为最终答案保存。纠正计入决策步数。",
                      _json([item.model_dump() for item in run.state.completion_feedback])])
    parts.extend(["## 后端回答原文（未自动事实核验）",
                  _fenced(run.answer) if run.answer is not None else "本次运行未产生最终回答。"])
    if run.error:
        parts.extend(["## 运行错误或终止原因", _json(run.error.model_dump())])
    parts.extend(["## 判读边界",
                  "本报告没有新增科学判定。保留工具的 unknown、解析错误及适用范围；缺失文件或未找到标记不自动等于失败。后端回答原样保留，可能包含超出证据的推断，应与上面的工具观察分别核对。",
                  "## 完整保存快照", _json(record.model_dump())])
    return "\n\n".join(parts) + "\n"


def export_markdown(record: StoredRun, output: Path) -> Path:
    target = Path(output).expanduser().resolve()
    if target.suffix.lower() != ".md":
        raise ReportPathError("Report output must end in .md")
    content = render_markdown(record)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation refuses overwrites, including existing symlink targets.
    handle = target.open("x", encoding="utf-8", newline="\n")
    try:
        with handle:
            handle.write(content)
    except BaseException:
        # Remove only the new partial file created by this call, then preserve the failure.
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return target
