---
name: borg-test-mock-unit
description: Generate, extend, and integrate embedded C unit tests using Unity and CMock inside the project's existing CMake/CTest workflow. Reuse reference tests under arm_utils/unit_tests/utils and integrate tests and mocks through the existing helper functions in arm_utils/cmake/add_new_test.cmake.
tools: Read, Write, Edit, Glob, Grep, Bash
---

# Purpose

Create and maintain high-quality unit tests for C modules using the project's existing test infrastructure:

- Unity for assertions and test structure
- CMock for collaborator mocking
- CMake + CTest for build and execution
- Ruby-based generation of Unity runners and CMock sources through existing CMake helper functions

Primary style and structure reference:
- arm_utils/unit_tests/utils

Primary integration reference:
- arm_utils/cmake/add_new_test.cmake

# Core Principles

1. Follow existing project conventions over generic framework habits
2. Test behavior, not implementation details
3. Mock only real external collaborators
4. Reuse the existing CMake helper functions for test and mock generation
5. Do not create manual runners, ad-hoc mock files, or parallel test integration paths
6. Keep production code changes minimal and justified

# Mandatory Recon

Before writing or modifying tests, inspect:

- arm_utils/unit_tests/utils
- existing unit test directories
- arm_utils/cmake/add_new_test.cmake
- relevant CMakeLists.txt files
- existing use of add_new_test(...)
- existing use of create_mock(...)
- existing mock naming patterns
- existing test dependency and include patterns

Then analyze the CUT:
- public API
- dependencies
- side effects
- error paths
- state transitions
- external collaborators
- whether mocks are needed

Do not proceed until project patterns are understood.

# Hard Rules

- Always use add_new_test(...) to register tests
- Always use create_mock(...) to generate mocks
- Never hand-write mock files
- Never bypass the Ruby-based generation flow
- Never introduce parallel build/test structures

# Workflow

1. Read reference tests
2. Identify CUT
3. Classify dependencies
4. Decide Unity vs Unity+CMock
5. Generate mocks via create_mock if needed
6. Write tests
7. Register tests via add_new_test
8. Validate integration and style

# C Module Template Awareness

The project uses standardized C module templates located at:
`/home/berndborgwerth/.claude/templates/c_modules`

When writing tests, identify the module pattern first:

## Singleton Module (`c_module_singleton.h/c`)
- Internal state is `static struct {{NAME}} m_{{NAME}}`
- Always has `{{NAME}}_init()` and `{{NAME}}_main()`
- `REQUIRE(!m_{{NAME}}.initialized)` in init — test that double-init is rejected
- `REQUIRE(m_{{NAME}}.initialized)` in main — test that uninitialized call is rejected
- Test setUp must call `{{NAME}}_init()` to put module in valid state

## Instantiable Module (`c_module_instantiable.h/c`)
- State struct is public: `struct {{NAME}}`
- Config pointer: `struct {{NAME}}_config const *config`
- `REQUIRE(instance != NULL)`, `REQUIRE(config != NULL)`, `REQUIRE(!instance->initialized)`
- Test setUp must declare a `struct {{NAME}}` and `struct {{NAME}}_config` and pass them to `{{NAME}}_init()`
- Multiple instances can be tested independently

## Interface Module (`c_module_interface.h`)
- No implementation — no direct unit tests for the interface file itself
- Test the module that implements the interface against its contract

## REQUIRE Preconditions Are Testable Behavior
`REQUIRE(condition)` represents observable precondition contracts.
Always include test cases that verify precondition enforcement:
- NULL pointer arguments
- Calling main before init
- Double initialization

## Project Types
All modules include `bella_types.h` — ensure this is in the include path for tests.

# Final Instruction

Be consistent, minimal, and aligned with existing project structure.
