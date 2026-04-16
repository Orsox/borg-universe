from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.orchestration_settings_store import LocalModelSettings


class LocalLlmClientError(RuntimeError):
    pass


class LocalLlmClient:
    def __init__(
        self,
        settings: LocalModelSettings,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else float(os.getenv("LLM_TIMEOUT_SECONDS", "1800"))

    def _url(self, path: str) -> str:
        if self.base_url:
            return urljoin(f"{self.base_url}/", path.lstrip("/"))
        return f"http://{self.settings.ip_address}:{self.settings.port}{path}"

    def list_models(self) -> dict[str, Any]:
        request = Request(self._url("/v1/models"), headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise LocalLlmClientError(details) from exc
        except URLError as exc:
            raise LocalLlmClientError(str(exc.reason)) from exc
        return raw

    def send_prompt(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.settings.model_name or "local-model",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        request = Request(self._url("/v1/chat/completions"), data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise LocalLlmClientError(details) from exc
        except URLError as exc:
            raise LocalLlmClientError(str(exc.reason)) from exc

        return {
            "request": payload,
            "response": raw,
            "content": _extract_content(raw),
        }


def _extract_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
            content = first.get("text")
            if isinstance(content, str):
                return content
    content = payload.get("content")
    if isinstance(content, str):
        return content
    return ""
