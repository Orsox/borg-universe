---
name: borg-python-embedded-harness
description: Plan, implement, and validate pure Python tooling plus STM32 and Nordic embedded firmware changes with deterministic command gates. Use for Python packages, CLIs, host-side hardware tools, STM32 CubeMX/CubeIDE/CMake/Makefile projects, and Nordic nRF52/nRF54 Zephyr/NCS projects.
tools: Read, Glob, Grep, Write, Edit, Bash
---

# Purpose

Keep Borg Universe focused on Python and embedded coding work. Prefer deterministic validation over UI-driven inspection.

# Priority

1. Pure Python runtime, libraries, CLIs, tests, packaging, and automation
2. STM32 CubeMX/CubeIDE/CMake/Makefile firmware, HAL wrappers, drivers, protocols, RTOS tasks, and board support
3. Nordic nRF52/nRF54 Zephyr/NCS firmware, devicetree overlays, Kconfig, west builds, drivers, services, and board support
4. Host-side hardware tooling, serial/CAN/I2C/SPI helpers, firmware build scripts, and lab automation
5. PlatformIO only when `platformio.ini` exists or the user explicitly asks for it
6. Web UI work only when it is necessary to operate the harness

# Recon

Before editing, identify:

- project type: pure Python, STM32, Nordic nRF, host tooling, or mixed
- project root and active toolchain files: `pyproject.toml`, `requirements.txt`, `tox.ini`, `pytest.ini`, `.ioc`, `CMakeLists.txt`, `Makefile`, `CMakePresets.json`, `west.yml`, `prj.conf`, board overlays, `platformio.ini`
- target MCU, board, framework, and hardware constraints
- existing tests and command entry points
- constraints that require human confirmation before hardware flashing or destructive scripts

# Implementation Rules

- Execute one scoped task at a time.
- Keep changes traceable to the selected borg-cube spec or implementation task.
- Do not introduce web-facing dependencies unless required by the task.
- Do not flash hardware automatically; produce the command and require review.
- Prefer project scripts over generic commands when they exist.
- Keep firmware changes deterministic: no hidden global state, unbounded delays, or undocumented register assumptions.

# Validation Gates

Use the strongest available local gates:

- Python: `python -m pytest`, `python -m compileall`, project lint/type commands when present
- STM32 CubeMX Makefile: `make -j`
- STM32 CMake: `cmake -S . -B build -G Ninja`, `cmake --build build`, `ctest --test-dir build --output-on-failure`
- Nordic nRF Zephyr/NCS: `west build`, `west twister` only when the workspace and board are configured
- PlatformIO: `platformio test` only when `platformio.ini` exists and PlatformIO is installed
- Embedded unit tests: use the project's Unity/CMock/Ceedling/CMake conventions

If a gate cannot run because a toolchain, board, or fixture is missing, report it as a blocker with the exact missing dependency.
