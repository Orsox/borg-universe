# Feature Specification — `<FEATURE_NAME>`

## Metadata

| Field | Value                                      |
|-------|--------------------------------------------|
| Feature Name | `<FEATURE_NAME>`                           |
| Feature ID | `<ID>`                                     |
| Status | draft (planned / implemented / deprecated) |
| Owner | `<OWNER>`                                  |
| Created | `<DATE>`                                   |
| Last Updated | `<DATE>`                               |

---

# 1. Goal

<Brief, high-level description of what this module does and why it exists.>

---

# 2. Problem Statement

## The Problem

<Describe the problem space and the specific pain points this feature addresses.>

## Current Workarounds (If Any)

<What do users currently do to work around the lack of this feature?>

## Impact

<Who is affected and what is the business/technical impact?>

## Dependencies

< What submodules are used by this feature?>

---

# 3. Scope

## In Scope

- <List of functionality included in this feature>
- <Specific behaviors, components, or capabilities>

## Out of Scope

- <Deliberately excluded functionality with reasoning>
- <Future work that belongs to other features>

## Dependencies

- <External systems, libraries, or features required>
- <Breaking changes introduced>


---

# 4. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | <First functional requirement> |
| FR-2 | <Second functional requirement> |
| FR-3 | <Third functional requirement> |

### FR-<N>: `<Name>`
<Detailed description of the requirement. Include preconditions, expected behavior, and postconditions.>


---

# 5. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | <Performance requirements> |
| NFR-2 | <Availability/Reliability> |
| NFR-3 | <Scalability requirements> |
| NFR-4 | <Maintainability/Configurability> |

---

# 6. Constraints

- <Technical constraints (language version, platform)>
- <Integration constraints (API formats, protocols)>
- <Policy or compliance constraints>

---

# 7. Interfaces

## 7.1 Configuration Interface

<Describe configuration format - JSON schema, YAML, env vars, etc.>

### Configuration Schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `<field>` | `<type>` | Yes/No | `<value>` | <Description> |

## 7.3 External API

### Endpoint: `METHOD /path`

<Description of what this endpoint does>

**Request format:**
```json
{
  "<field>": "<value>"
}
```

**Response format:**
```json
{
  "<field>": "<value>"
}
```

## 7.2 Internal Interfaces

| Module | Purpose |
|--------|---------|
| `<module>.py` | <Purpose> |

---

# 8. Data Models

| Model/Type | Fields | Description |
|------------|--------|-------------|
| `<Model>` | - field: type<br>- field: type | <Description> |

---

# 9. Routing Logic (If applicable)

<Describe how requests/decisions are routed, including any matching algorithms or selection criteria>

## Matching Algorithm

1. <Step 1>
2. <Step 2>
3. <Step 3>

---

# 10. Error Handling

| Error Code | Condition | Response |
|------------|-----------|----------|
| `<CODE>` | <Condition> | <Response format> |

---

# 11. Testing Strategy

## Unit Tests
- <Test case 1>
- <Test case 2>

## Integration Tests
- <Scenario 1>
- <Scenario 2>

## Manual Testing
- <Steps to verify manually>

---

# 12. Migration Guide (If applicable)

<Steps for users to migrate from old version or approach>
