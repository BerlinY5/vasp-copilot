"""Explicit registration and validated synchronous calls; no model decisions."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError

from ..schemas import ErrorInfo, Schema
from .protocol import ToolResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    argument_model: type[Schema]
    result_model: type[Schema]
    handler: Callable[[Any], Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self, name: str, description: str,
        argument_model: type[Schema], result_model: type[Schema],
    ) -> Callable:
        """Return a decorator; the handler receives one validated model instance."""
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or not description.strip():
            raise ValueError("Tool name must be lowercase snake_case and description nonempty")
        if not issubclass(argument_model, Schema) or not issubclass(result_model, Schema):
            raise TypeError("Tool models must inherit Schema")

        def decorator(handler: Callable[[Any], Any]) -> Callable[[Any], Any]:
            if name in self._tools:
                raise ValueError(f"Tool already registered: {name}")
            if not callable(handler):
                raise TypeError("Tool handler must be callable")
            self._tools[name] = ToolDefinition(name, description, argument_model, result_model, handler)
            return handler

        return decorator

    def describe(self) -> list[dict[str, Any]]:
        """Fresh JSON-compatible definitions; provider-specific adapters come later."""
        return [dict(name=tool.name, description=tool.description,
                     parameters=tool.argument_model.model_json_schema(),
                     returns=tool.result_model.model_json_schema())
                for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        def fail(kind: str, message: str) -> ToolResult:
            label = name if name in self._tools else "<unknown_tool>"
            logger.warning("Tool %s: %s", label, kind)
            return ToolResult(tool_name=name, status="error", error=ErrorInfo(kind=kind, message=message))

        tool = self._tools.get(name)
        if tool is None:
            return fail("unknown_tool", f"No registered tool named {name}")
        try:
            args = tool.argument_model.model_validate(arguments)
        except ValidationError as exc:
            details = exc.errors(include_url=False, include_input=False, include_context=False)
            return fail("invalid_arguments", json.dumps(details))
        logger.info("Executing tool %s", name)
        try:
            raw_result = tool.handler(args)
        except Exception as exc:
            # Do not return arbitrary exception contents to future model backends.
            return fail("execution_error", f"Tool raised {type(exc).__name__}")
        try:
            result = tool.result_model.model_validate(raw_result)
            data = result.model_dump(mode="json")
        except Exception as exc:
            return fail("invalid_result", f"Tool returned invalid or non-serializable data ({type(exc).__name__})")
        logger.info("Tool %s completed", name)
        return ToolResult(tool_name=name, status="success", data=data)
