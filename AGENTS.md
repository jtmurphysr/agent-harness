# AGENTS.md — Agent Operating Constitution
# <PROJECT-NAME>

This file is the primary context document for all agents operating in this repository.
Read it in full before taking **any** action. It is the single source of truth for
conventions, module boundaries, and the definition of "done."

---

## Repository Identity

- **Purpose**: <one-line description of what this project does>
- **Stack**: <language, runtime, framework — e.g., "Python 3.11+, CLI-first, no web framework">
- **Paradigm**: Agent-first — all code, tests, and docs are agent-generated
- **Pipeline**: Issue → Agent → Code → PR → CI → Auto-merge (sequential by dependency)
- **Human role**: Intent specification, credential provisioning, outcome validation

---

## Module Boundaries

Define the boundary map for your project. Each module may only import from explicitly
listed dependencies. This is enforced by `scripts/validate_harness.py`.

<!--
EXAMPLE (CLI tool with auth, clients, resolvers, pipeline pattern):

```
app.py                  ← CLI entrypoint only. Parses args, calls pipeline. No logic.
├── auth/
│   ├── service_a_auth.py  ← Service A credential lifecycle only
│   └── service_b_auth.py  ← Service B credential lifecycle only
├── clients/
│   ├── service_a_client.py  ← Service A API I/O only. No business logic.
│   └── service_b_client.py  ← Service B API I/O only. Rate limiting lives here.
├── resolvers/
│   ├── primary_resolver.py  ← Primary matching logic only. No API calls.
│   └── fallback_resolver.py ← Fallback matching logic only. No API calls.
├── pipeline.py             ← Orchestration only. Imports clients + resolvers + models.
├── reporter.py             ← Output only. Reads from models. No logic.
└── models.py               ← Pydantic v2 schemas only. No logic, no internal imports.
```
-->

```
<entrypoint>.py              ← CLI/API entrypoint. Parses args, calls pipeline. No logic.
├── <module_a>/
│   └── ...
├── <module_b>/
│   └── ...
├── pipeline.py              ← Orchestration only.
├── models.py                ← Data schemas only. No logic, no internal imports.
└── tests/
```

### Invariants (enforced by structural linter — `scripts/validate_harness.py`)

<!--
Define which modules may import from which. Update ALLOWED_IMPORTS in
scripts/validate_harness.py to match this table.

EXAMPLE:

| Module | May import from | Must NEVER import from |
|---|---|---|
| `auth/` | `models` | `clients`, `resolvers`, `pipeline`, `reporter` |
| `clients/` | `auth`, `models` | `resolvers`, `pipeline`, `reporter` |
| `resolvers/` | `models` | `auth`, `clients`, `pipeline`, `reporter` |
| `pipeline` | `clients`, `resolvers`, `models`, `reporter` | `auth` (injected) |
| `reporter` | `models` | `auth`, `clients`, `resolvers`, `pipeline` |
| `models` | _(nothing internal)_ | everything |
-->

| Module | May import from | Must NEVER import from |
|---|---|---|
| `<module>` | `<allowed>` | `<forbidden>` |

**Why enforce boundaries**: Keeps modules independently testable and prevents coupling.

---

## Critical Agent Warnings

> These are the spots where agent-generated code most commonly goes wrong on this project.
> Read each one. They encode hard-won knowledge about the specific APIs and patterns used.

<!--
Write warnings as explicit DO/DON'T pairs with code examples.
Each warning should describe a specific failure mode the agent is likely to hit.

EXAMPLE:

### ⚠️ WARNING 1: <API name> uses <auth scheme>, NOT <common wrong scheme>

JWT for <Service> **must** use the ES256 algorithm (ECDSA with P-256).
Most JWT tutorials use RS256 (RSA). Using RS256 will produce tokens
that are silently rejected with a 401.

### ⚠️ WARNING 2: <field> is not always present in <API> responses

`response["data"].get("field")` — always use `.get()`, never direct access.
When field is absent, degrade gracefully to fallback strategy. Never raise, never skip.

### ⚠️ WARNING 3: <Service> rate limits — 429s are guaranteed at scale

All retry/backoff logic lives in `clients/<service>_client.py`. Nowhere else.
Callers must never implement their own retry logic.

### ⚠️ WARNING 4: Idempotency — check before create, not after failure

Before creating a resource, check if one with the same identifier already exists.
Do not rely on catching a "duplicate" error — not all APIs return one reliably.
-->

### ⚠️ WARNING N: <title>

<description of failure mode and correct pattern>

---

## Harness Lessons — Read Before Writing Any Code

These were discovered during initial bootstrap. They will burn you if ignored.

### ⚠️ LESSON 1: Always run `ruff format .` — not just `ruff check .`

`ruff check` and `ruff format` are separate tools. CI runs both.
**Always run both before opening a PR:**
```bash
ruff check .
ruff format .        # ← this one too — not just --check
ruff check .         # ← re-run after format to catch any new issues
```

### ⚠️ LESSON 2: Opening a PR requires an explicit `gh pr create` call

The agent must explicitly create the PR. Do not assume it happens automatically.
After all checks pass, always run:
```bash
gh pr create \
  --title "<title>" \
  --body "Closes #N" \
  --base main \
  --head $(git branch --show-current) \
  --label "agent-task"
```

### ⚠️ LESSON 3: `pyproject.toml` — use exact validated structure

The `pyproject.toml` in this repo is the validated template. Do not modify the
`[build-system]`, `[tool.setuptools]`, or `[tool.pytest.ini_options]` sections
unless you have a specific reason. These were validated with `validate-pyproject`
after multiple CI failures with flat-layout discovery.

Key invariants:
- `build-backend = "setuptools.build_meta"` — not `setuptools.backends.legacy:build`
- `py-modules` is a **flat array** under `[tool.setuptools]` — not a table
- `packages` is a **flat array** under `[tool.setuptools]` — not a find directive
- `pythonpath = ["."]` is required in `[tool.pytest.ini_options]` for flat layout imports

---

## Definition of Done

A task is complete **only when ALL of the following are true**:

- [ ] All existing tests pass
- [ ] New tests written and passing for all new behavior
- [ ] Minimum test coverage: **85%** on changed modules
- [ ] No linter errors (`ruff check .`)
- [ ] No formatter violations (`ruff format .` then `ruff check .` again)
- [ ] No type errors (`mypy --strict .`)
- [ ] Boundary linter passes (`python scripts/validate_harness.py`)
- [ ] Docstrings on all public functions and classes
- [ ] PR opened with `gh pr create` — label `agent-task`, body contains `Closes #N`
- [ ] `docs/` updated if architecture or data contracts changed

Do not open a PR until every item is checked.
If CI fails, read the output fully and fix the root cause.
Do not approximate or work around failures — diagnose them.

---

## Sequential Dispatch Protocol

Issues are dispatched one at a time. Each issue's PR must merge before the next is dispatched.

**Dependency order:**
```
#001 → #002 → #003 → ... → #NNN
```

**Before starting any issue**, check: has the previous issue's PR merged into `main`?
If not, wait. Do not start work on a dependent module before its dependency exists.

---

## Code Conventions

### Python Style
- Python 3.11+ — use `match`, `|` union types, `tomllib`, etc. where appropriate
- Type hints on **all** function signatures — no exceptions
- Pydantic v2 for all data models in `models.py`
- `ruff` for linting and formatting
- `mypy --strict` — no `type: ignore` without an inline comment explaining why

### Async
- All API calls are `async` — use `httpx.AsyncClient`, not `requests`
- Use `asyncio.gather()` for concurrent operations where order doesn't matter
- The CLI entrypoint runs via `asyncio.run(main())`

### Logging
- `structlog` — structured JSON only
- Every client method and pipeline stage logs entry + exit + exceptions
- Fields: `event`, `module`, `duration_ms`, plus domain-relevant identifiers
- **Never use `print()` in production code** — CLI output goes through `reporter.py`

### Environment Variables
All secrets via env vars. Fail loud and early if any are missing:

```python
import os

def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"See docs/setup.md for configuration instructions."
        )
    return value
```

Required vars:
<!--
List all required environment variables for your project.
Example:
- `SERVICE_A_API_KEY`
- `SERVICE_B_CLIENT_ID`
- `SERVICE_B_CLIENT_SECRET`
-->

### Testing
- `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"`)
- All API calls mocked with `respx` (for httpx) or `unittest.mock`
- Fixtures in `conftest.py` — never in individual test files
- One test file per source module: `tests/test_<module>.py`
- Test names: `test_<scenario>_<expected_outcome>`

---

## What to Do When Stuck

1. Do **not** write approximation code or workarounds
2. Identify what's missing: a tool, a guardrail, a missing abstraction, or wrong documentation
3. Open a separate issue with label `harness-gap` describing the missing capability
4. Comment on the current issue referencing the blocker
5. Do not open a partial PR — it will pollute the sequential dispatch chain

---

## Repository Knowledge Map

| Document | Purpose |
|---|---|
| `AGENTS.md` | This file. Operating constitution. |
| `docs/architecture.md` | Module map, data flow, API contracts |
| `docs/setup.md` | Credential provisioning and environment setup |
| `docs/conventions.md` | Patterns and anti-patterns |
| `docs/decisions/` | Architectural decision records |
| `scripts/validate_harness.py` | Boundary linter |

---

## Label Reference

| Label | Meaning |
|---|---|
| `agent-task` | Ready for agent pickup |
| `harness-gap` | Missing capability — blocks agent, requires human |
| `human-review` | Requires human judgment before merge |
| `gc` | Garbage collection / entropy pass |

---

*AGENTS.md changes require `human-review` label — constitutional amendments are not auto-merged.*
