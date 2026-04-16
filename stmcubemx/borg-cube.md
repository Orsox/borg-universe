# Module Specification - stmcubemx

## Metadata

| Field | Value |
|-------|--------------------------------------------|
| Feature Name | stmcubemx |
| Feature ID | stmcubemx |
| Status | draft |
| Owner | Borg Collective |
| Created | 2026-04-14 |
| Last Updated | 2026-04-14 |

---

# 1. Goal

This module is responsible for integrating and managing STM32CubeMX-generated code within Borg Universe. It ensures that hardware abstraction layers (HAL) and low-level drivers (LL) are integrated consistently and remain accessible to other Borg modules.

---

# 2. Problem Statement

## The Problem

The manual management of STM32CubeMX projects in an automated environment such as Borg Universe often leads to conflicts in paths, build configurations, and the separation between generated and manual code.

## Impact

Embedded developers must spend time on integration instead of focusing on application logic. Without a clear structure in `stmcubemx/`, maintainability is reduced.

## Dependencies

- STM32 HAL / LL libraries
- ARM GCC toolchain
- CMake / build system integration

---

# 3. Scope

## In Scope

- Structuring `stmcubemx/` to host `.ioc` files and generated code.
- Defining interfaces for access to hardware peripherals.
- Integration into the project's global build system.

## Out of Scope

- Automatic execution of STM32CubeMX (GUI-based).
- Replacement of the STM32 HAL.

---

# 4. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Provide a consistent directory structure for generated code. |
| FR-2 | Export include paths and symbols for other modules. |
| FR-3 | Support code regeneration without losing manual changes (user code sections). |

---

# 5. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Compatibility with standard STM32CubeMX versions. |
| NFR-2 | Minimal impact on build times through efficient file scanning. |

---

# 6. Constraints

- Must work in Linux-based build environments.
- Uses ARM GCC as the primary compiler.

---

# 7. Interfaces

## 7.2 Internal Interfaces

| Module | Purpose |
|--------|---------|
| `stmcubemx/Inc` | HAL/LL header files. |
| `stmcubemx/Src` | Initialization implementation. |

---

# 10. Error Handling

| Error Code | Condition | Response |
|------------|-----------|----------|
| ERR-CFG-01 | `.ioc` file is missing or corrupted. | Abort the build process and report the issue. |

---

# 11. Testing Strategy

## Manual Testing
- Verify the expected directory structure exists.
- Compile a test project with the `stmcubemx` module integrated.
