#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.local_llm_client import LocalLlmClient, LocalLlmClientError
from app.services.orchestration_settings_store import LocalModelSettings, OrchestrationSettings


DEFAULT_PROMPT = "Antworte mir mit einem einfachen Hallo"
DEFAULT_LOG_FILE = REPO_ROOT / "tests" / "artifacts" / "test-logs" / "local_llm_smoke.log"
DEFAULT_CONFIG_FILE = REPO_ROOT / "BORG" / "config" / "orchestration.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send an OpenAI-compatible smoke test to a local LLM.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt sent to the local LLM.")
    parser.add_argument("--config-file", default=str(DEFAULT_CONFIG_FILE), help="Path to the stored orchestration settings.")
    parser.add_argument("--log-file", default=str(DEFAULT_LOG_FILE), help="Write a detailed run log to this file.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds for each LLM request.")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON.")
    return parser


def resolve_local_model(config_file: Path) -> LocalModelSettings:
    orchestration = OrchestrationSettings.model_validate_json(config_file.read_text(encoding="utf-8"))
    return orchestration.local_model


def run_smoke_test(local_model: LocalModelSettings, prompt: str, timeout_seconds: float) -> dict[str, Any]:
    client = LocalLlmClient(local_model, timeout_seconds=timeout_seconds)
    models = client.list_models()
    completion = client.send_prompt(prompt)
    return {
        "endpoint": f"http://{local_model.ip_address}:{local_model.port}",
        "models": models,
        "prompt": prompt,
        "reply": completion["content"],
        "request": completion["request"],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = _configure_logging(Path(args.log_file))
    config_file = Path(args.config_file)
    if not config_file.exists():
        logger.error("Stored local LLM config not found: %s", config_file)
        print(f"Stored local LLM config not found: {config_file}", file=sys.stderr)
        return 1

    local_model = resolve_local_model(config_file)

    logger.info("Local LLM smoke test started")
    logger.info("Loaded config file: %s", config_file)
    logger.info("Resolved endpoint: http://%s:%s", local_model.ip_address, local_model.port)
    logger.info("Resolved model: %s", local_model.model_name or "local-model")
    logger.info("Input prompt: %s", args.prompt)

    try:
        result = run_smoke_test(local_model, args.prompt, args.timeout)
    except LocalLlmClientError as exc:
        logger.exception("Local LLM request failed")
        print(f"Local LLM request failed: {exc}", file=sys.stderr)
        return 1

    logger.info("Models response: %s", json.dumps(result["models"], ensure_ascii=True))
    logger.info("Chat request: %s", json.dumps(result["request"], ensure_ascii=True))
    logger.info("Chat reply: %s", result["reply"])

    if args.json:
        rendered = json.dumps(result, indent=2, ensure_ascii=True)
        logger.info("JSON output: %s", rendered)
        print(rendered)
        return 0

    _emit(logger, f"Endpoint: {result['endpoint']}")
    _emit(logger, "Available models:")
    _emit(logger, json.dumps(result["models"], indent=2, ensure_ascii=True))
    _emit(logger, "Prompt:")
    _emit(logger, result["prompt"])
    _emit(logger, "Reply:")
    _emit(logger, result["reply"])
    _emit(logger, "Chat request:")
    _emit(logger, json.dumps(result["request"], indent=2, ensure_ascii=True))
    return 0


def _configure_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("local_llm_smoke")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.info("Writing smoke test log to %s", log_file)
    return logger


def _emit(logger: logging.Logger, message: str) -> None:
    logger.info("%s", message)


if __name__ == "__main__":
    raise SystemExit(main())
