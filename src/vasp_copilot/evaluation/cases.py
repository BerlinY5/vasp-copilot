"""Fixed scenarios and independently checked expectations for public logs."""

import gzip
import hashlib
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REVISION = "682bfd855dd89264b0ff8d6bee4815f8834cc5ac"
# Same originals as tests/fixtures/pymatgen/manifest.json; never derive expected
# observations from the parser under evaluation.
SAMPLES = {
    "static_silicon": (61474, "04b23098e34e2d32d35b24d2396f0366325c063bf09cb82927874154aede439c"),
    "relaxation": (106024, "6ae9368cd11c0fb68ce9f204c0d342ed2a1e04206f92f261cdbfa747c1485086"),
}
OSZICAR_SAMPLE = (1314, "1e3f219d8da90386d1f354cb7a8476084a7f4aea0d43514a21eda19d18c3664f")


class FixtureError(ValueError):
    """Required public fixture is missing, damaged or no longer pinned."""


@dataclass
class Scenario:
    name: str
    description: str
    origin: str
    files: dict[str, bytes] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    missing_directory: bool = False
    max_steps: int = 6
    fail_backend: bool = False


def load_samples(root: Path) -> dict[str, bytes]:
    samples = {}
    for name, (size, digest) in SAMPLES.items():
        try:
            with gzip.open(root / f"{name}.OUTCAR.gz", "rb") as stream:
                raw = stream.read(size + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise FixtureError(f"Cannot read pinned fixture: {name}") from exc
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise FixtureError(f"Fixture size or SHA-256 mismatch: {name}")
        samples[name] = raw
    size, digest = OSZICAR_SAMPLE
    try:
        with (root / "static_silicon.OSZICAR").open("rb") as stream:
            raw = stream.read(size + 1)
    except OSError as exc:
        raise FixtureError("Cannot read pinned fixture: static_silicon.OSZICAR") from exc
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise FixtureError("Fixture size or SHA-256 mismatch: static_silicon.OSZICAR")
    samples["static_silicon_oszicar"] = raw
    return samples


def _expected(tools: list[str], *, status: str = "completed", **observations: Any) -> dict[str, Any]:
    return {
        "status": status,
        "decision_steps": len(tools) if status == "max_steps" else len(tools) + 1,
        "tools": tools,
        "tool_statuses": ["success"] * len(tools),
        "tool_errors": [None] * len(tools),
        "tool_error_messages": [None] * len(tools),
        "run_error": None if status == "completed" else status,
        "answer_present": status == "completed",
        **observations,
    }


def build_scenarios(samples: dict[str, bytes]) -> list[Scenario]:
    tools = ["inspect_directory", "diagnose_outcar", "search_knowledge"]
    cases = []
    # Original byte offsets were manually checked in the pinned public files.
    for name, ionic, electronic, header, marker, ionic_status, documents in [
        ("static_silicon", 1, 13, 42249, 54994, "unknown", ["electronic.md"]),
        ("relaxation", 3, 4, 86842, 99982, "marker_found", ["electronic.md", "ionic.md"]),
    ]:
        cases.append(Scenario(
            name, "公开 OUTCAR：工具选择、迭代证据和参考来源", "pymatgen 原始公开日志",
            {"OUTCAR": samples[name]}, _expected(
                tools, iteration=[ionic, electronic, "reached_marker", header, [marker]],
                marker_states=["marker_found", ionic_status], reference_documents=documents,
            ),
        ))
    # Cut immediately after Iteration 3(1); do not inherit an earlier EDIFF message.
    cases.append(Scenario(
        "truncated_output", "输出截断：最后一步证据不足时保留 unknown", "relaxation 人工截断，非真实失败日志",
        {"OUTCAR": samples["relaxation"][:81109]}, _expected(
            tools, iteration=[3, 1, "unknown", 81005, []],
            marker_states=["unknown", "unknown"], reference_documents=["outcar.md"],
        ),
    ))
    input_tools = ["inspect_directory", "inspect_incar"]
    cases.extend([
        Scenario("incar_only", "只有 INCAR：选择输入检查工具", "人工构造输入",
                 {"INCAR": b"IBRION=2; NSW=20\n"}, _expected(
                     input_tools, input_type="relaxation", input_error=None,
                     input_parameters={"IBRION": 2, "NSW": 20})),
        Scenario("invalid_incar", "INCAR 解码失败：保留解析错误", "人工构造无效 UTF-8 字节",
                 {"INCAR": b"\xff\xfeinvalid\n"}, _expected(
                     input_tools, input_type="unknown", input_error="UnicodeDecodeError", input_parameters={})),
        Scenario("empty_directory", "无可读输入输出：说明证据不足", "人工构造空目录",
                 expected=_expected(["inspect_directory"])),
        Scenario("missing_directory", "目录不存在：将工具错误交给后端", "人工构造缺失目录",
                 expected=_expected(["inspect_directory"], tool_statuses=["error"],
                                    tool_errors=["execution_error"], tool_error_messages=["Tool raised FileNotFoundError"]),
                 missing_directory=True),
        Scenario("step_limit", "一步预算：保留已获得的观察", "人工设置决策上限",
                 {"OUTCAR": samples["static_silicon"]},
                 _expected(["inspect_directory"], status="max_steps"), max_steps=1),
        Scenario("backend_failure", "后端第二次决策异常：保留第一次观察", "人工注入后端异常",
                 expected=_expected(["inspect_directory"], status="backend_error", run_error_message="RuntimeError"),
                 fail_backend=True),
    ])
    return cases + _output_scenarios(samples)


def _output_scenarios(samples: dict[str, bytes]) -> list[Scenario]:
    """Explicit expected rows; mutations affect only temporary scenario bytes."""
    outcar, oszicar = samples["static_silicon"], samples["static_silicon_oszicar"]
    # Original OSZICAR rows and offsets were checked directly in the pinned bytes.
    electronic = ["RMM", 13, -10.6452777428, -1.9111e-6, -2.3579e-7, 274, 0.000912, None, 1156]
    summary = [1, -10.645278, -10.645278, 0.0, 1236]
    common = dict(oszicar_status="observed", oszicar_error=None, oszicar_has_issues=False,
                  oszicar_electronic=electronic, oszicar_summary=summary)
    cases = [Scenario(
        "oszicar_only", "只有 OSZICAR：保留电子行、能量摘要及原文", "pymatgen 原始公开日志",
        {"OSZICAR": oszicar}, _expected(["inspect_directory", "inspect_oszicar"], **common),
    )]
    paired = dict(common, iteration=[1, 13, "reached_marker", 42249, [54994]],
                  marker_states=["marker_found", "unknown"], reference_documents=["electronic.md"])
    # Tuples list the derived bytes and independent expected values, not parser output.
    variants = [
        ("paired_outputs", "双日志编号一致", "pymatgen 原始公开配对日志", oszicar,
         electronic, summary, False, "matched", "matched", "matched"),
        ("ionic_mismatch", "离子编号不同：不跨离子步比较电子编号", "人工将 OSZICAR 摘要编号 1 改为 2",
         oszicar[:1236] + oszicar[1236:].replace(b"   1 F=", b"   2 F=", 1),
         electronic, [2, *summary[1:]], False, "mismatched", "mismatched", "unknown"),
        ("electronic_mismatch", "离子编号一致但电子编号不同", "人工将 OSZICAR 最后电子编号 13 改为 12",
         oszicar[:1156] + oszicar[1156:].replace(b"RMM:  13", b"RMM:  12", 1),
         [electronic[0], 12, *electronic[2:]], summary, False, "mismatched", "matched", "mismatched"),
        ("truncated_oszicar", "末行截断：丢弃旧候选，核对保持 unknown", "人工删除 OSZICAR 最后一字节换行",
         oszicar[:-1], None, None, True, "unknown", "unknown", "unknown"),
        ("missing_oszicar_summary", "保留电子行但没有摘要：不推算离子编号", "人工在 OSZICAR 摘要前截断",
         oszicar[:1236], electronic, None, False, "unknown", "unknown", "unknown"),
        ("unsupported_oszicar", "后续不支持的记录：不沿用前面的摘要", "人工在 OSZICAR 末尾追加 MD 形式记录，非真实失败日志",
         oszicar + b"   2 T= 300 E= -10.0 F= -10.1 E0= -10.1 EK= 0.1 SP= 0.0 SK= 0.0\n",
         None, None, True, "unknown", "unknown", "unknown"),
    ]
    for name, description, origin, raw, electron, energy, issues, status, ionic_status, electronic_status in variants:
        expected = dict(paired, oszicar_status="observed" if electron or energy else "unknown",
                        oszicar_electronic=electron, oszicar_summary=energy, oszicar_has_issues=issues,
                        comparison_status=status, comparison_checks=[
                            ["ionic_step", ionic_status, 1, energy[0] if energy else None,
                             42249, energy[-1] if energy else None],
                            ["electronic_step", electronic_status, 13, electron[1] if electron else None,
                             42249, electron[-1] if electron else None],
                        ])
        cases.append(Scenario(name, description, origin, {"OUTCAR": outcar, "OSZICAR": raw},
                              _expected(["inspect_directory", "scan_directory", "search_knowledge"], **expected)))
    return cases
