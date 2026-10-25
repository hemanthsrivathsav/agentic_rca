"""Model clients.

Agents call :meth:`LLMClient.complete` with a list of chat messages and a
``purpose`` tag. Two implementations:

- :class:`MockLLMClient`   offline and deterministic. Behaviour is supplied by
  a *script*: a function ``(purpose, messages, sample) -> str``. The KYC demo
  provides one, so the demo always runs without network access.
- :class:`AzureOpenAIClient` calls an Azure OpenAI chat deployment with the
  standard library only (``urllib``), so no SDK needs approval.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

from .util import rough_token_count


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int
    model: str


class LLMClient(Protocol):
    def complete(self, messages: list[dict], *, purpose: str, temperature: float = 0.0, sample: int = 0) -> LLMResponse: ...


Script = Callable[[str, list[dict], int], str]


class MockLLMClient:
    """Deterministic client driven by a script function."""

    model = "mock-1"

    def __init__(self, script: Script) -> None:
        self.script = script
        self.calls = 0

    def complete(self, messages: list[dict], *, purpose: str, temperature: float = 0.0, sample: int = 0) -> LLMResponse:
        self.calls += 1
        text = self.script(purpose, messages, sample if temperature > 0 else 0)
        prompt = " ".join(m.get("content", "") for m in messages)
        return LLMResponse(text=text, tokens_in=rough_token_count(prompt), tokens_out=rough_token_count(text), model=self.model)


class AzureOpenAIClient:
    """Azure OpenAI chat completions over plain HTTPS.

    Configure with environment variables:
    ``AZURE_OPENAI_ENDPOINT`` (https://<name>.openai.azure.com),
    ``AZURE_OPENAI_KEY``, ``AZURE_OPENAI_DEPLOYMENT``,
    ``AZURE_OPENAI_API_VERSION`` (defaults to 2024-06-01).
    """

    def __init__(self, endpoint: str | None = None, key: str | None = None, deployment: str | None = None, api_version: str | None = None, timeout: float = 60) -> None:
        self.endpoint = (endpoint or os.environ["AZURE_OPENAI_ENDPOINT"]).rstrip("/")
        self.key = key or os.environ["AZURE_OPENAI_KEY"]
        self.deployment = deployment or os.environ["AZURE_OPENAI_DEPLOYMENT"]
        self.api_version = api_version or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
        self.timeout = timeout
        self.model = self.deployment

    def complete(self, messages: list[dict], *, purpose: str, temperature: float = 0.0, sample: int = 0) -> LLMResponse:
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"
        body = json.dumps({"messages": messages, "temperature": temperature}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "api-key": self.key})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"].strip(),
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            model=data.get("model", self.deployment),
        )
