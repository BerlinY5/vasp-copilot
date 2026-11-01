import io
import json
import socket
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from vasp_copilot.agent import deepseek
from vasp_copilot.agent.deepseek import DeepSeekBackend, DeepSeekProtocolError
from vasp_copilot.agent.loop import AgentLoop
from vasp_copilot.agent.protocol import AgentState
from vasp_copilot.cli import main
from vasp_copilot.config import ConfigurationError, DeepSeekConfig
from vasp_copilot.tools.file_inspection import create_registry


def reply(message, reason="stop"):
    return {"choices": [{"finish_reason": reason, "message": {"role": "assistant", **message}}]}


def tool_reply(directory, arguments=None):
    return reply({"content": "Inspect the directory first", "tool_calls": [{"id": "call_1", "type": "function", "function": {
        "name": "inspect_directory", "arguments": json.dumps({"directory": str(directory)}) if arguments is None else arguments,
    }}]}, "tool_calls")


def test_native_roundtrip_keeps_ids_and_observations(tmp_path):
    payloads = []
    def transport(payload, config):
        payloads.append(payload)
        return tool_reply(tmp_path) if len(payloads) == 1 else reply({"content": "Insufficient evidence; status unknown."})
    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-key"), transport), create_registry(tmp_path)).run("Inspect", str(tmp_path))
    assert run.status == "completed" and len(run.state.history) == 1
    messages = payloads[1]["messages"]
    assert messages[-2]["tool_calls"][0]["id"] == messages[-1]["tool_call_id"] == "call_1"
    assert messages[-2]["content"] == "Inspect the directory first"
    observation = json.loads(messages[-1]["content"])
    assert observation["status"] == "success" and len(observation["data"]["files"]) == 8
    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert payloads[0]["tools"][0]["function"]["name"] == "scan_directory"
    assert "test-key" not in json.dumps(payloads) + run.model_dump_json()


@pytest.mark.parametrize("bad", [
    {}, {"choices": []}, reply({"content": "partial"}, "length"), reply({"content": ""}),
    tool_reply(".", "not json"), tool_reply(".", "[]"),
    reply({"content": "blocked"}, "content_filter"),
    reply({"tool_calls": [{}, {}]}, "tool_calls"),
])
def test_invalid_or_truncated_response_fails_closed(bad):
    backend = DeepSeekBackend(DeepSeekConfig("test-key"), lambda payload, config: bad)
    with pytest.raises(DeepSeekProtocolError):
        backend.decide(AgentState(question="Inspect", directory="."), create_registry().describe())


def test_environment_configuration_and_secret_repr():
    config = DeepSeekConfig.from_env({"DEEPSEEK_API_KEY": " secret ", "DEEPSEEK_MODEL": "chosen-model", "DEEPSEEK_TIMEOUT": "12"})
    assert config.api_key == "secret" and config.model == "chosen-model" and config.timeout == 12
    assert "secret" not in repr(config)


@pytest.mark.parametrize("env", [
    {}, {"DEEPSEEK_API_KEY": ""}, {"DEEPSEEK_API_KEY": "key\ninjection"},
    {"DEEPSEEK_API_KEY": "key", "DEEPSEEK_MODEL": " "},
    *[{"DEEPSEEK_API_KEY": "key", "DEEPSEEK_TIMEOUT": value} for value in ("abc", "nan", "inf", "0", "121")],
])
def test_invalid_config(env):
    with pytest.raises(ConfigurationError):
        DeepSeekConfig.from_env(env)


def test_http_transport_headers_timeout_and_response(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == deepseek.ENDPOINT
            assert request.get_header("Authorization") == "Bearer test-key"
            assert timeout == 7
            assert json.loads(request.data) == {"model": "example"}
            return io.BytesIO(b'{"choices": []}')
    monkeypatch.setattr(deepseek, "build_opener", lambda *handlers: Opener())
    assert deepseek.request_completion({"model": "example"}, DeepSeekConfig("test-key", timeout=7)) == {"choices": []}


@pytest.mark.parametrize("error,expected", [
    (HTTPError(deepseek.ENDPOINT, 401, "private", {}, io.BytesIO(b"secret")), deepseek.DeepSeekAuthenticationError),
    (HTTPError(deepseek.ENDPOINT, 429, "private", {}, io.BytesIO(b"secret")), deepseek.DeepSeekRateLimitError),
    (HTTPError(deepseek.ENDPOINT, 500, "private", {}, io.BytesIO(b"secret")), deepseek.DeepSeekHTTPError),
    (URLError("private"), deepseek.DeepSeekNetworkError),
    (TimeoutError("private"), deepseek.DeepSeekNetworkError),
])
def test_transport_errors_are_sanitized_without_retry(monkeypatch, error, expected):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise error
    monkeypatch.setattr(deepseek, "build_opener", lambda *handlers: Opener())
    with pytest.raises(expected) as caught:
        deepseek.request_completion({}, DeepSeekConfig("test-key"))
    assert "private" not in str(caught.value) and "secret" not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize("data", [b"not json", b"[]", b"x" * (deepseek.MAX_RESPONSE_BYTES + 1)],
                         ids=["invalid-json", "non-object", "oversized"])
def test_transport_rejects_bad_or_oversized_body(monkeypatch, data):
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(data)
    monkeypatch.setattr(deepseek, "build_opener", lambda *handlers: Opener())
    with pytest.raises(DeepSeekProtocolError):
        deepseek.request_completion({}, DeepSeekConfig("test-key"))


def test_redirects_are_not_followed():
    assert deepseek.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example") is None


@pytest.mark.parametrize("error_type,expected", [
    (TimeoutError, "DeepSeekTimeoutError"),
    (socket.gaierror, "DeepSeekDNSError"),
    (ssl.SSLEOFError, "DeepSeekTLSError"),
    (ssl.SSLCertVerificationError, "DeepSeekCertificateError"),
    (ConnectionRefusedError, "DeepSeekConnectionError"),
    (ConnectionResetError, "DeepSeekConnectionError"),
    (OSError, "DeepSeekNetworkError"),
])
@pytest.mark.parametrize("phase", ["connect", "read"])
def test_network_failures_reach_agent_as_safe_specific_errors(monkeypatch, tmp_path, error_type, expected, phase):
    calls = []
    error = error_type("private test-key")

    class Response(io.BytesIO):
        def read(self, size):
            raise error

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            if phase == "connect":
                raise URLError(error)
            return Response()

    monkeypatch.setattr(deepseek, "build_opener", lambda *handlers: Opener())
    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-key")), create_registry(tmp_path)).run("Inspect", str(tmp_path))
    assert run.status == "backend_error"
    assert run.error.message == expected
    assert run.state.history == []
    assert "private" not in run.model_dump_json() and "test-key" not in run.model_dump_json()
    assert len(calls) == 1


@pytest.mark.parametrize("name", ["scan_directory", "inspect_directory", "diagnose_outcar", "inspect_incar", "inspect_oszicar", "compare_outputs"])
def test_all_tools_reject_outside_directory(tmp_path, name):
    selected, other = tmp_path / "selected", tmp_path / "other"
    selected.mkdir()
    other.mkdir()
    result = create_registry(selected).execute(name, {"directory": str(other)})
    assert result.error.kind == "execution_error" and "PermissionError" in result.error.message


def test_external_file_target_is_rejected(tmp_path, monkeypatch):
    selected, other = tmp_path / "selected", tmp_path / "other"
    selected.mkdir()
    other.mkdir()
    original = Path.resolve
    def resolved(path, *args, **kwargs):
        return other / "OUTCAR" if path == selected / "OUTCAR" else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolved)
    result = create_registry(selected).execute("diagnose_outcar", {"directory": str(selected)})
    assert "PermissionError" in result.error.message


def test_missing_key_cli_does_not_contact_service(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert main([str(tmp_path), "--agent", "--backend", "deepseek"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["kind"] == "configuration_error"


def test_mock_does_not_require_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert main([str(tmp_path), "--agent"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"


def test_native_tool_roundtrip_can_retrieve_references(tmp_path):
    payloads = []
    def transport(payload, config):
        payloads.append(payload)
        if len(payloads) == 1:
            assert "search_knowledge" in [tool["function"]["name"] for tool in payload["tools"]]
            return reply({"content": None, "tool_calls": [{"id": "reference_1", "type": "function", "function": {
                "name": "search_knowledge", "arguments": '{"query": "EDIFF", "top_k": 1}',
            }}]}, "tool_calls")
        observation = json.loads(payload["messages"][-1]["content"])
        assert observation["data"]["hits"][0]["evidence_type"] == "reference"
        assert observation["data"]["hits"][0]["source"] == "https://vasp.at/wiki/index.php/EDIFF"
        assert payload["messages"][-1]["tool_call_id"] == "reference_1"
        return reply({"content": "General explanation only; no file evidence for this calculation, status unknown."})
    run = AgentLoop(DeepSeekBackend(DeepSeekConfig("test-key"), transport), create_registry(tmp_path)).run("Explain EDIFF", str(tmp_path))
    assert run.status == "completed" and len(run.state.history) == 1
    assert "test-key" not in run.model_dump_json()
