"""Deterministic, observation-driven demonstration; not an LLM emulator."""

from typing import Any

from .protocol import AgentState, Finish, ToolCall


def summarize_outcar(data: dict[str, Any]) -> str:
    iteration = data["last_iteration"]
    summary = (
        f"文件证据：OUTCAR 尾部采样，最后可识别离子步={iteration['ionic_step']}，"
        f"电子步={iteration['electronic_step']}，消息状态={iteration['status']}。"
    )
    for evidence in iteration["markers"]:
        summary += f" OUTCAR 字节偏移 {evidence['byte_offset']}：{evidence['text']}。"
    for finding in data["findings"]:
        for evidence in finding["evidence"]:
            summary += f" OUTCAR 字节偏移 {evidence['byte_offset']}：{evidence['text']}。"
    return summary + "这只是日志观察，整体收敛状态仍为 unknown；完整证据见工具历史。"


def summarize_comparison(data: dict[str, Any]) -> str:
    parts = [f"输出日志采样编号核对：{data['status']}；同次运行归属为 unknown。"]
    for check in data["checks"]:
        left = check["outcar_value"] if check["outcar_value"] is not None else "unknown"
        right = check["oszicar_value"] if check["oszicar_value"] is not None else "unknown"
        parts.append(f"{check['name']}：OUTCAR={left}，OSZICAR={right}；{check['status']}。{check['reason']}。")
        for evidence in (check["outcar_evidence"], check["oszicar_evidence"]):
            if evidence:
                parts.append(f"{evidence['file']} 字节偏移 {evidence['byte_offset']}：{evidence['text']}")
    parts.append("编号相同不证明同次运行或收敛；编号不同不证明失败，也不确定原因。")
    return "\n".join(parts)


class MockBackend:
    def decide(self, state: AgentState, tools: list[dict[str, Any]]) -> ToolCall | Finish:
        if not state.history:
            return ToolCall(tool_name="inspect_directory", arguments={"directory": state.directory})
        last = state.history[-1].observation
        if last.tool_name == "search_knowledge":
            previous = state.history[-2].observation
            if previous.tool_name == "scan_directory":
                summary = summarize_outcar(previous.data["diagnostics"]) + "\n\n" + summarize_comparison(previous.data["output_comparison"])
            else:
                summary = summarize_outcar(previous.data)
            if last.status == "error":
                return Finish(answer=summary + f"\n\n参考资料：检索失败（{last.error.kind}），未补充通用解释。")
            if not last.data["hits"]:
                return Finish(answer=summary + "\n\n参考资料：本地知识库没有匹配条目，不改变上述观察。")
            references = []
            for hit in last.data["hits"]:
                references.append(
                    f"参考资料（通用解释）：{hit['title']}\n{hit['excerpt']}\n"
                    f"来源：{hit['source']}；本地 {hit['document']} 第 {hit['line_start']}–{hit['line_end']} 行。"
                )
            return Finish(answer=summary + "\n\n" + "\n\n".join(references))
        if last.status == "error":
            return Finish(answer=f"工具 {last.tool_name} 未完成：{last.error.kind}（{last.error.message}）。证据不足，无法判断计算状态。")
        data = last.data
        if last.tool_name == "inspect_directory":
            readable = {file["name"] for file in data["files"] if file["readable"]}
            if {"OUTCAR", "OSZICAR"}.issubset(readable):
                return ToolCall(tool_name="scan_directory", arguments={"directory": state.directory})
            if "OUTCAR" in readable:
                return ToolCall(tool_name="diagnose_outcar", arguments={"directory": state.directory})
            if "OSZICAR" in readable:
                return ToolCall(tool_name="inspect_oszicar", arguments={"directory": state.directory})
            if "INCAR" in readable:
                return ToolCall(tool_name="inspect_incar", arguments={"directory": state.directory})
            return Finish(answer="文件检查未发现可读取的 OUTCAR、OSZICAR 或 INCAR。证据不足，计算状态为 unknown。")
        if data.get("error"):
            return Finish(answer=f"文件解析报告错误：{data['error']['kind']}。计算状态为 unknown；详情见工具历史。")
        if last.tool_name in {"diagnose_outcar", "scan_directory"}:
            output = data["diagnostics"] if last.tool_name == "scan_directory" else data
            if last.tool_name == "scan_directory" and output.get("error"):
                return Finish(answer=f"OUTCAR 读取失败：{output['error']['kind']}。整体状态为 unknown。\n" +
                              summarize_comparison(data["output_comparison"]))
            topics = []
            if output["last_iteration"]["status"] != "unknown":
                topics.append("EDIFF")
            if any(finding["rule_id"] == "outcar.ionic_stop_marker" and finding["status"] == "marker_found"
                   for finding in output["findings"]):
                topics.append("EDIFFG")
            return ToolCall(tool_name="search_knowledge", arguments={"query": " ".join(topics) or "OUTCAR", "top_k": 2})
        if last.tool_name == "inspect_incar":
            return Finish(answer=(f"未获得可读取的 OUTCAR；INCAR 表达的计算类型为 {data['calculation_type']}。"
                                  "输入意图不证明计算完成或收敛，计算状态为 unknown；参数原文和问题见工具历史。"))
        if last.tool_name == "inspect_oszicar":
            parts = [f"文件证据：OSZICAR 尾部解析状态为 {data['status']}。"]
            for key in ("last_electronic_step", "last_energy_summary"):
                if data[key] is not None:
                    evidence = data[key]["evidence"]
                    parts.append(f"OSZICAR 字节偏移 {evidence['byte_offset']}：{evidence['text']}")
            parts.extend(data["issues"])
            parts.append("这里只观察日志行，不把步号当总步数，也不由能量摘要判定收敛；整体状态仍为 unknown。")
            parts.append("格式参考（非本次计算证据）：" + "、".join(data["sources"]))
            return Finish(answer="\n".join(parts))
        return Finish(answer="Mock 不支持进一步解释此工具结果。计算状态为 unknown。")
