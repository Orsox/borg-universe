from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    environment: str
    debug: bool
    log_level: str
    borg_root: Path
    agents_root: Path
    skills_root: Path
    workflows_root: Path
    artifact_root: Path
    workbench_root: Path
    supabase_url: str | None
    supabase_anon_key: str | None
    supabase_service_role_key: str | None
    mcp_server_url: str | None
    worker_poll_interval_seconds: float
    worker_batch_size: int
    worker_running_task_timeout_seconds: float = 900.0

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and (self.supabase_anon_key or self.supabase_service_role_key))


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Borg Universe"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        environment=os.getenv("APP_ENV", "local"),
        debug=_get_bool("APP_DEBUG", False),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        borg_root=_get_path("BORG_ROOT", "./BORG"),
        agents_root=_get_path("AGENTS_ROOT", "./agents"),
        skills_root=_get_path("SKILLS_ROOT", "./skills"),
        workflows_root=_get_path("WORKFLOWS_ROOT", "./BORG/workflows"),
        artifact_root=_get_path("ARTIFACT_ROOT", "./artifacts"),
        workbench_root=_get_path("WORKBENCH_ROOT", "./workbench_placeholder"),
        supabase_url=os.getenv("SUPABASE_URL") or None,
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY") or None,
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None,
        mcp_server_url=os.getenv("MCP_SERVER_URL") or None,
        worker_poll_interval_seconds=float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5")),
        worker_batch_size=int(os.getenv("WORKER_BATCH_SIZE", "4")),
        worker_running_task_timeout_seconds=float(os.getenv("WORKER_RUNNING_TASK_TIMEOUT_SECONDS", "900")),
    )
