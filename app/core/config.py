from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WorkbenchStatus:
    path: Path
    configured: bool
    exists: bool
    is_directory: bool
    uses_placeholder: bool
    message: str | None

    @property
    def valid(self) -> bool:
        return self.configured and self.exists and self.is_directory and not self.uses_placeholder


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _load_dotenv() -> None:
    dotenv_path = PROJECT_ROOT / ".env"
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, _strip_wrapping_quotes(value.strip()))


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
    worker_temporary_failure_max_retries: int = 3

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and (self.supabase_anon_key or self.supabase_service_role_key))

    @property
    def workbench_status(self) -> WorkbenchStatus:
        path = self.workbench_root.expanduser()
        normalized = path.as_posix().lower()
        uses_placeholder = "workbench_placeholder" in normalized
        configured = bool(str(path).strip())
        exists = path.exists()
        is_directory = path.is_dir()

        if uses_placeholder:
            message = "WORKBENCH_ROOT still points to the placeholder path. Update `.env` with your real workbench directory."
        elif not exists:
            message = f"Configured workbench path does not exist: {path}"
        elif not is_directory:
            message = f"Configured workbench path is not a directory: {path}"
        else:
            message = None

        return WorkbenchStatus(
            path=path,
            configured=configured,
            exists=exists,
            is_directory=is_directory,
            uses_placeholder=uses_placeholder,
            message=message,
        )


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
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
        worker_temporary_failure_max_retries=int(os.getenv("WORKER_TEMPORARY_FAILURE_MAX_RETRIES", "3")),
    )
