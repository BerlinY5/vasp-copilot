import json

import pytest
from pydantic import ValidationError

from vasp_copilot.agent.protocol import ToolResult
from vasp_copilot.agent.tool_registry import ToolRegistry
from vasp_copilot.schemas import ErrorInfo, Schema
from vasp_copilot.tools.file_inspection import create_registry


class NumberArgs(Schema):
    number: int


class NumberResult(Schema):
    doubled: int


def number_tool():
    registry = ToolRegistry()
    calls = []
    @registry.register("double", "Double a number", NumberArgs, NumberResult)
    def double(args):
        calls.append(args)
        return {"doubled": args.number * 2}
    return registry, calls


def test_dispatch_validates_and_serializes():
    registry, calls = number_tool()
    result = registry.execute("double", {"number": 3})
    assert result.status == "success" and result.data == {"doubled": 6}
    assert isinstance(calls[0], NumberArgs)
    assert json.loads(result.model_dump_json())["error"] is None


@pytest.mark.parametrize("arguments", [{}, {"number": "3"}, {"number": True}, {"number": 3, "extra": 1}, []])
def test_bad_arguments_do_not_call_handler(arguments):
    registry, calls = number_tool()
    result = registry.execute("double", arguments)
    assert result.error.kind == "invalid_arguments"
    assert calls == []


def test_unknown_name_does_not_execute_other_tools():
    registry, calls = number_tool()
    result = registry.execute("missing", {})
    assert result.status == "error" and result.error.kind == "unknown_tool"
    assert calls == []


def test_duplicate_does_not_replace_original():
    registry, _ = number_tool()
    with pytest.raises(ValueError, match="already registered"):
        registry.register("double", "Replacement", NumberArgs, NumberResult)(lambda args: {"doubled": 999})
    assert registry.execute("double", {"number": 2}).data == {"doubled": 4}


def test_tool_exception_is_structured_and_registry_remains_usable():
    registry, _ = number_tool()
    @registry.register("broken", "Raises an exception", NumberArgs, NumberResult)
    def broken(args):
        raise RuntimeError("private exception detail")
    result = registry.execute("broken", {"number": 1})
    assert result.error.kind == "execution_error"
    assert "private exception detail" not in result.model_dump_json()
    assert registry.execute("double", {"number": 2}).status == "success"


def test_invalid_result_rejected():
    registry = ToolRegistry()
    registry.register("bad", "Wrong return shape", NumberArgs, NumberResult)(lambda args: {"doubled": "six"})
    assert registry.execute("bad", {"number": 3}).error.kind == "invalid_result"


def test_keyboard_interrupt_not_swallowed():
    registry = ToolRegistry()
    def interrupt(args):
        raise KeyboardInterrupt()
    registry.register("interrupt", "User interrupt", NumberArgs, NumberResult)(interrupt)
    with pytest.raises(KeyboardInterrupt):
        registry.execute("interrupt", {"number": 3})


def test_descriptions_are_json_compatible_and_detached():
    registry, _ = number_tool()
    specs = registry.describe()
    assert specs[0]["parameters"]["additionalProperties"] is False
    assert specs[0]["parameters"]["required"] == ["number"]
    json.dumps(specs)
    specs[0]["name"] = "changed"
    assert registry.describe()[0]["name"] == "double"


@pytest.mark.parametrize("kwargs", [
    {"status": "success"},
    {"status": "error"},
    {"status": "success", "data": {}, "error": ErrorInfo(kind="x", message="x")},
    {"status": "error", "data": {}, "error": ErrorInfo(kind="x", message="x")},
])
def test_result_contract_rejects_contradictions(kwargs):
    with pytest.raises(ValidationError):
        ToolResult(tool_name="test", **kwargs)


def test_scanner_adapter_preserves_report_and_original_files(tmp_path):
    path = tmp_path / "INCAR"
    path.write_bytes(b"IBRION=2;NSW=20\n")
    result = create_registry().execute("scan_directory", {"directory": str(tmp_path)})
    assert result.status == "success"
    assert len(result.data["files"]) == 8
    assert result.data["input_context"]["calculation_type"] == "relaxation"
    assert result.data["calculation_status"] == "unknown"
    assert path.read_bytes() == b"IBRION=2;NSW=20\n"


def test_missing_directory_is_execution_error(tmp_path):
    result = create_registry().execute("scan_directory", {"directory": str(tmp_path / "missing")})
    assert result.error.kind == "execution_error"
    assert "FileNotFoundError" in result.error.message


def test_empty_directory_argument_rejected():
    assert create_registry().execute("scan_directory", {"directory": ""}).error.kind == "invalid_arguments"


def test_registries_are_independent():
    first, _ = number_tool()
    second = create_registry()
    assert first.execute("scan_directory", {}).error.kind == "unknown_tool"
    assert second.execute("double", {}).error.kind == "unknown_tool"
