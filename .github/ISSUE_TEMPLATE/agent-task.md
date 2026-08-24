---
name: Agent Task
about: Structured issue for autonomous agent execution
title: "Issue #NNN: <module> — <one-line description>"
labels: ""
assignees: ""
---

<!--
HARNESS ISSUE CONTRACT
This template is a binding contract between the human (intent) and the agent (execution).
Every section is required. Omissions cause agent drift, incomplete tests, or CI failure.
Do not add the agent-task label until ALL sections are complete.
-->

## Identity

| Field | Value |
|---|---|
| **Issue Number** | `#NNN` (canonical, independent of GitHub issue number) |
| **Depends On** | `#NNN — <title of predecessor>` |
| **Estimated LOE** | `Low \| Medium \| High \| X-High` |
| **LOE Factors** | One-line summary of signals that drove the score |
| **Files to Create** | (list below) |
| **Files to Modify** | (list below) |
| **Out of Scope** | (list below) |

### Files to Create
```
path/to/file.py
tests/test_file.py
```

### Files to Modify
```
# Read for context only:
AGENTS.md
docs/architecture.md

# Modify:
pyproject.toml  ← coverage omit delta (see below)
```

### Out of Scope
- Do NOT implement `<related module>` — that is Issue #NNN
- Do NOT add API calls to `<module>` — resolvers are pure logic only
- Do NOT modify `models.py` unless a schema change is explicitly listed here

---

## Interface Contract

### Public API (`__all__`)
```python
__all__ = ["ClassName", "function_name"]
```

### Signatures
```python
class ClassName:
    def method_name(
        self,
        param: ParamType,
        optional: SomeType | None = None,
    ) -> ReturnType:
        """One-line docstring."""
        ...


async def function_name(arg: ArgType) -> ReturnType | None:
    """One-line docstring."""
    ...
```

### Data Contracts
- Input: describe what the method receives and any nullability constraints
- Output: describe what it returns, including `None` conditions
- Side effects: file writes, API calls, state mutations — or "none"

---

## Domain Warnings

<!--
These are the landmines. Write them as explicit DO/DON'T pairs.
Reference AGENTS.md lessons if applicable.
-->

⚠️ **WARNING**: `field_name` is optional in the upstream response — always use `.get("field_name")`, never direct access. Failure mode: `KeyError` at runtime on real data.

⚠️ **WARNING**: <API name> uses <auth scheme>, NOT <common wrong scheme>. Failure mode: silent 401.

⚠️ **WARNING**: <operation> must be idempotent — check existence before create, not after failure.

---

## Acceptance Criteria

### Required Test Cases
Each test case must be implemented as a named test function. "Comprehensive tests" is not acceptable.

| Test Function | Scenario | Expected Outcome |
|---|---|---|
| `test_<method>_<scenario>` | Happy path with valid input | Returns `ExpectedType` with correct fields |
| `test_<method>_none_<field>` | `field` is `None` in upstream response | Returns result with `field=None`, no exception |
| `test_<method>_empty` | Empty collection input | Returns `[]`, no exception |
| `test_<method>_<error_case>` | Upstream returns error/429/timeout | Raises `ExpectedError` or retries N times |
| `test_<method>_below_threshold` | Score below confidence threshold | Returns `None` |

### Coverage Requirements
- `path/to/module.py`: **100%**
- `tests/test_module.py`: not measured

### Edge Cases That Must Be Covered
- [ ] `None` value for `<field>` — use `.get()` pattern
- [ ] Empty list response from upstream
- [ ] Pagination — at least 2 pages in test fixture
- [ ] Rate limit / retry behavior (if applicable)

---

## Coverage Omit Delta

Apply this change to `pyproject.toml` as part of this issue:

```toml
# Remove from omit list (this module is now implemented):
# "path/to/module.py",

# Keep in omit list (not yet implemented):
# "path/to/other.py",
```

---

## Definition of Done

- [ ] `ESTIMATED LOE` and `LOE FACTORS` fields are populated
- [ ] All files listed in "Files to Create" exist and are non-stub
- [ ] All signatures match the Interface Contract exactly
- [ ] All named test cases in Acceptance Criteria are implemented
- [ ] Coverage meets per-file requirements
- [ ] `pyproject.toml` omit list updated per Coverage Omit Delta
- [ ] `ruff check --fix . && ruff format . && ruff check .` — clean
- [ ] `mypy --strict .` — clean
- [ ] `python scripts/validate_harness.py` — clean
- [ ] PR opened, `Closes #<github-issue-number>` in PR body
