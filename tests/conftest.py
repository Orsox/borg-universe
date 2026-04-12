from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pytest


LOG_DIR = Path(os.getenv("PYTEST_LOG_DIR", "artifacts/test-logs"))


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
