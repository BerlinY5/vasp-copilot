"""Interpret an explicit last-loop report without reconstructing VASP convergence."""

from .iterations import NOT_REACHED, REACHED
from .schemas import ElectronicSettings, ElectronicSettingConsideration, ElectronicStepDiagnosis, IterationObservation


def _diagnose_message(iteration: IterationObservation) -> ElectronicStepDiagnosis:
    """Pure rule: usable header plus one explicit, unambiguous loop-stop report."""
    result = ElectronicStepDiagnosis(
        ionic_step=iteration.ionic_step, electronic_step=iteration.electronic_step,
        summary="最后采样电子循环缺少可靠且唯一的停止消息，无法生成局部异常诊断。",
        limitations=[
            "仅解释采样窗口中最后可识别循环的程序报告；未重算总自由能变化或能带能量变化，不能由未达消息倒推其中任何量未低于 EDIFF，也不诊断所有离子步。",
            "未核实运行归属、EDIFF/NELM、ICHARG 或算法设置；特殊模式和人为拼接日志仍需检查。",
            "此局部诊断不改变整体电子收敛、离子收敛或正常终止的 unknown 状态。",
        ],
        sources=["https://gitlab.com/ase/ase/-/issues/1429",
                 "https://vasp.at/wiki/index.php/EDIFF", "https://vasp.at/wiki/index.php/NELM"],
    )
    if (iteration.header is None or iteration.issues or iteration.ionic_step is None
            or iteration.electronic_step is None or len(iteration.markers) != 1):
        return result
    marker = iteration.markers[0]
    if marker.byte_offset <= iteration.header.byte_offset:
        return result
    message = marker.text.strip().strip("- \t")
    if iteration.status == "not_reached_marker" and message == NOT_REACHED.decode("ascii"):
        result.status = "reported_not_reached"
        result.severity = "warning"
        result.summary = "最后采样电子循环由程序显式报告未达到 EDIFF；应核查这一步的自洽结果。"
        result.impact = "该循环后报告的能量、受力等结果需要审慎核对，不能据本规则判定整次计算失败或定位根因。"
        result.recommendations = [
            "先确认 OUTCAR 来源及完整性，核对该循环对应的作业记录，避免混用不同运行的输入和输出。",
            "核对同次运行的 EDIFF、NELM、ICHARG 与 ALGO/IALGO；本工具尚未提取这些设置，不能声称 NELM 已耗尽。",
            "结合电子迭代轨迹和计算模式排查；若确为自洽困难，参考官方资料检查算法和电荷混合，不应仅凭此消息盲目增大 NELM。",
            "EDIFF=0 的固定步数、非自洽或特殊响应模式需单独解释；以上为人工核查建议，不自动修改参数或提交计算。",
        ]
    elif iteration.status == "reached_marker" and message == REACHED.decode("ascii"):
        result.status = "not_triggered"
        result.summary = "最后采样循环报告达到 EDIFF，本条未达消息规则未触发；这不是整体收敛判定。"
    else:
        return result
    result.evidence = [iteration.header.model_copy(deep=True), marker.model_copy(deep=True)]
    return result


def diagnose_electronic_step(iteration: IterationObservation, settings: ElectronicSettings | None = None) -> ElectronicStepDiagnosis:
    """Keep the message verdict; add qualified context from separately scoped settings."""
    result = _diagnose_message(iteration)
    if settings is None:
        return result
    result.limitations[1] = "OUTCAR 前缀设置与最后采样循环的运行关联未验证；特殊模式、窗口间未读内容和拼接日志仍需核查。"
    if settings.issues:
        if result.status == "reported_not_reached":
            result.recommendations[1] = "参数样本存在运行边界问题，不能将前缀设置用于该循环；先取同次运行的完整输出核查。"
        return result
    observed = {p.name: p for p in settings.parameters if p.status == "observed"}
    if result.status == "reported_not_reached":
        values = "、".join(f"{p.name}={p.value}" for p in observed.values()) or "无可靠参数"
        missing = "、".join(p.name for p in settings.parameters if p.status != "observed")
        result.recommendations[1] = (f"前缀已观察到 {values}；仍需核对与该循环是否同一次运行。"
                                     + (f"未取得可靠的 {missing}，不补默认值或由 IALGO 反推 ALGO。" if missing else ""))
    def add(kind, summary, names, relation=None):
        result.settings_considerations.append(ElectronicSettingConsideration(
            kind=kind, summary=summary, relation=relation,
            evidence=[e.model_copy(deep=True) for name in names for e in observed[name].evidence],
        ))
    ediff, icharg, algo, nelm = (observed.get(name) for name in ("EDIFF", "ICHARG", "ALGO", "NELM"))
    if ediff and ediff.value == 0:
        add("ediff_zero", "前缀 EDIFF=0；若它属于该循环，应按固定电子步数语境解释，不能由步号判断未收敛；不撤销已观察到的消息。", ["EDIFF"])
    if icharg and icharg.value >= 10:
        add("fixed_charge", f"前缀 ICHARG={icharg.value}；若属于该循环，需先核对固定电荷/非自洽语境及设置适用性，不直接套普通自洽结论。", ["ICHARG"])
        result.sources.append("https://vasp.at/wiki/index.php/ICHARG")
    if algo and algo.value.casefold() in {"none", "nothing", "eigenval"}:
        add("postprocessing", f"前缀显式 ALGO={algo.value}；若属于该循环，需按后处理语境核对，不能将未达消息直接解释为一般自洽故障。", ["ALGO"])
        result.sources.append("https://vasp.at/wiki/index.php/ALGO")
    if nelm and iteration.header is not None and iteration.electronic_step is not None and not iteration.issues:
        number, limit = iteration.electronic_step, nelm.value
        relation = "below" if number < limit else "equal" if number == limit else "above"
        symbol = {"below": "<", "equal": "=", "above": ">"}[relation]
        consideration = ElectronicSettingConsideration(
            kind="sampled_step_vs_nelm", relation=relation,
            summary=f"最后采样电子编号 {number} {symbol} 前缀 NELM={limit}，仅为数值关系；运行关联未验证，不据此宣布上限耗尽或停止原因。",
            evidence=[iteration.header.model_copy(deep=True), *[e.model_copy(deep=True) for e in nelm.evidence]],
        )
        result.settings_considerations.append(consideration)
    return result
