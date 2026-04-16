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
        model_name = self._select_model_name(prompt)
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if _env_bool("LLM_FORCE_TOOL_CHOICE_NONE", True):
            payload["tool_choice"] = "none"
            payload["parallel_tool_calls"] = False
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        raw = self._chat_completion_with_fallback(payload, headers)

        tool_call_error = _unsupported_tool_call_error(raw)
        if tool_call_error:
            raise LocalLlmClientError(tool_call_error)

        return {
            "request": payload,
            "response": raw,
            "content": _extract_content(raw),
        }

    def _chat_completion_with_fallback(self, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        request = Request(self._url("/v1/chat/completions"), data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if "tool_choice" in payload and _is_tool_choice_schema_error(details):
                fallback_payload = dict(payload)
                fallback_payload.pop("tool_choice", None)
                fallback_payload.pop("parallel_tool_calls", None)
                fallback_request = Request(
                    self._url("/v1/chat/completions"),
                    data=json.dumps(fallback_payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                try:
                    with urlopen(fallback_request, timeout=self.timeout_seconds) as response:
                        return json.loads(response.read().decode("utf-8"))
                except HTTPError as fallback_exc:
                    fallback_details = fallback_exc.read().decode("utf-8", errors="replace")
                    raise LocalLlmClientError(fallback_details) from fallback_exc
                except URLError as fallback_exc:
                    raise LocalLlmClientError(str(fallback_exc.reason)) from fallback_exc
            raise LocalLlmClientError(details) from exc
        except URLError as exc:
            raise LocalLlmClientError(str(exc.reason)) from exc

    def _select_model_name(self, prompt: str) -> str:
        if "<deep>" not in prompt.lower():
            return self.settings.model_name or "local-model"
        return (
            os.getenv("LLM_DEEP_MODEL_NAME")
            or os.getenv("DEEP_MODEL_NAME")
            or "gpt-5.4-mini"
        )


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


def _unsupported_tool_call_error(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return None
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason.strip().lower() == "tool_calls":
            return "Unsupported tool call loop: model returned finish_reason='tool_calls'."
        for container_name in ("message", "delta"):
            container = choice.get(container_name)
            if not isinstance(container, dict):
                continue
            tool_calls = container.get("tool_calls")
            if not isinstance(tool_calls, list) or not tool_calls:
                continue
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if not isinstance(function, dict):
                    continue
                arguments = function.get("arguments")
                name = function.get("name")
                if not isinstance(arguments, str) or not arguments.strip():
                    return f"Unsupported tool call loop: function '{name or 'unknown'}' was emitted with empty arguments."
            return "Unsupported tool calls in local LLM response; this execution path does not support tool invocation."
    return None


def _is_tool_choice_schema_error(details: str) -> bool:
    text = details.lower()
    indicators = (
        "tool_choice",
        "parallel_tool_calls",
        "additional properties",
        "unknown field",
        "unrecognized field",
        "validation error",
    )
    return any(indicator in text for indicator in indicators)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
