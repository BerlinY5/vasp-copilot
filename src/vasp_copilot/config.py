"""DeepSeek settings from process environment; no automatic .env loading."""

import math
import os
from dataclasses import dataclass, field
from typing import Mapping


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str = field(repr=False)
    model: str = "deepseek-flash"
    timeout: float = 30.0

    def __post_init__(self):
        if not self.api_key.strip() or any(c in self.api_key for c in "\r\n"):
            raise ConfigurationError("DEEPSEEK_API_KEY is missing or invalid")
        if not self.model.strip():
            raise ConfigurationError("DEEPSEEK_MODEL must not be empty")
        if not math.isfinite(self.timeout) or not 0 < self.timeout <= 120:
            raise ConfigurationError("DEEPSEEK_TIMEOUT must be greater than 0 and at most 120 seconds")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "DeepSeekConfig":
        values = os.environ if env is None else env
        try:
            timeout = float(values.get("DEEPSEEK_TIMEOUT", "30"))
        except ValueError:
            raise ConfigurationError("DEEPSEEK_TIMEOUT must be numeric") from None
        return cls(api_key=values.get("DEEPSEEK_API_KEY", "").strip(),
                   model=values.get("DEEPSEEK_MODEL", "deepseek-flash").strip(), timeout=timeout)
