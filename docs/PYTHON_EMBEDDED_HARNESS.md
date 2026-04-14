# Python And Embedded Harness

Borg Universe is optimized for pure Python tooling and embedded coding workflows.
Pure web development is intentionally low priority unless it is needed to operate the harness itself.

## Archon-Inspired Control Model

The harness uses the same practical control ideas as Archon-style coding workflows:

- YAML workflows define the ordered execution path.
- Agent nodes handle planning, task splitting, implementation, and review.
- Deterministic command gates run real build and test commands.
- Human review remains the boundary for hardware flashing, destructive actions, and ambiguous requirements.
- Docker remains the default runtime for web, MCP, worker, database, and command-gate execution.

## Default Workflows

Use separate workflows so Python helper tooling stays pure Python:

- `python_tooling_harness`: Python packages, CLIs, scripts, tests, packaging, and automation.
- `stm32_nordic_harness`: STM32 CubeMX/CubeIDE/CMake/Makefile projects and Nordic nRF52/nRF54 Zephyr/NCS projects.

PlatformIO remains optional fallback tooling, not the default embedded path.

## Deterministic Gates

Workflow task entries can declare `command` or `commands`.

Example:

```yaml
tasks:
  - id: python-tests
    title: Python test suite
    only_if_path_exists: tests
    commands:
      - id: python-pytest
        run: python -m pytest
        timeout_seconds: 1200
```

Supported command fields:

- `id`: stable command id used in events and artifact names
- `run`: shell command to execute
- `working_dir`: path relative to the project root, or an absolute path
- `timeout_seconds`: command timeout
- `allow_failure`: record failure without failing the parent task
- `only_if_path_exists`: skip command unless the path exists
- `env`: command-specific environment variables

Command output is recorded as task events and as `workflow_command_log` artifacts under `ARTIFACT_ROOT`.

## Container Tooling

The Docker image includes:

- Python runtime and project requirements
- Claude Code CLI
- Git
- build-essential
- CMake
- Ninja
- West for Nordic Zephyr/NCS workspace commands

This keeps Python tests, STM32 CMake/Makefile builds, and Nordic `west` builds executable from the worker container.

ARM GCC for bare-metal CMake and CubeMX Makefile projects is enabled by default in Docker Compose.
Set `INSTALL_ARM_GCC=false` to reduce image size.

PlatformIO is optional.
Build with `--build-arg INSTALL_PLATFORMIO=true` or set `INSTALL_PLATFORMIO=true` in `.env` when a target project actually uses `platformio.ini`.
