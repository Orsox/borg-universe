from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import fastapi.testclient
import fastapi.dependencies.utils
import fastapi.routing
import starlette.background
import starlette.concurrency
import starlette.routing


LOG_DIR = Path(os.getenv("PYTEST_LOG_DIR", "artifacts/test-logs"))


class CompatTestClient:
    __test__ = False

    def __init__(self, app: Any, base_url: str = "http://testserver", **_: Any) -> None:
        self.app = app
        self.base_url = base_url

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url=self.base_url) as client:
                return await client.request(method, url, **kwargs)

        return anyio.run(send)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def __enter__(self) -> "CompatTestClient":
        return self

    def __exit__(self, *_: Any) -> None:
        return None


fastapi.testclient.TestClient = CompatTestClient


async def _inline_run_in_threadpool(func: Any, *args: Any, **kwargs: Any) -> Any:
    return func(*args, **kwargs)


fastapi.dependencies.utils.run_in_threadpool = _inline_run_in_threadpool
fastapi.routing.run_in_threadpool = _inline_run_in_threadpool
starlette.concurrency.run_in_threadpool = _inline_run_in_threadpool
starlette.routing.run_in_threadpool = _inline_run_in_threadpool
starlette.background.run_in_threadpool = _inline_run_in_threadpool


@pytest.fixture(autouse=True)
def _write_test_logs(request: pytest.FixtureRequest) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{_slugify(request.node.nodeid)}.log"

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))

    root_logger = logging.getLogger()
    previous_level = root_logger.level
    if previous_level > logging.DEBUG:
        root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        yield
    finally:
        root_logger.removeHandler(handler)
        handler.close()
        root_logger.setLevel(previous_level)


def _slugify(value: str) -> str:
    value = value.replace("\\", "/")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value.strip("_") or "test"
