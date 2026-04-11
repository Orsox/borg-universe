from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import Settings


class SupabaseRestError(RuntimeError):
    def __init__(self, status_code: int | None, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class SupabaseRestClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url:
            raise SupabaseRestError(None, "SUPABASE_URL is not configured")

        api_key = settings.supabase_service_role_key or settings.supabase_anon_key
        if not api_key:
            raise SupabaseRestError(None, "SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY is required")

        self.base_url = settings.supabase_url.rstrip("/")
        self.api_key = api_key

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str | list[str]] | None = None,
        body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer

        request = Request(url, data=data, headers=headers, method=method.upper())

        try:
            with urlopen(request, timeout=10) as response:
                content = response.read()
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise SupabaseRestError(exc.code, details) from exc
        except URLError as exc:
            raise SupabaseRestError(None, str(exc.reason)) from exc

        if not content:
            return None
        return json.loads(content.decode("utf-8"))
