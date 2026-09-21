# AGENTS.md — Agent Operating Constitution
# agent-harness

This file is the primary context document for all agents operating in this repository.
Read it in full before taking **any** action. It is the single source of truth for
conventions, module boundaries, and the definition of "done."

It is **both** this repo's constitution and the template copied into generated
projects. Filled-in sections describe `agent-harness`; `<angle-bracketed>` ones are
unfilled payload, and filling them is step one of templating.

---

## Repository Identity

- **Purpose**: An autonomous development harness that turns a PRD into a working
  codebase — issues generated from the PRD, dispatched one at a time to Claude Code
  agents, gated by CI, auto-merged, and mined for learnings on every merge. The repo
  is both the harness and its first user.
- **Stack**: Python 3.11+, FastAPI (Stonehaven admin API + webhook listener), SQLite
  (verdict store), Jinja2 (agent-definition rendering), httpx, structlog, Pydantic v2
- **Paradigm**: Agent-first — all code, tests, and docs are agent-generated
- **Pipeline**: Issue → Agent → Code → PR → CI → Auto-merge (sequential by dependency)
- **Human role**: Intent specification, credential provisioning, outcome validation

---

## Module Boundaries

Define the boundary map for your project. Each module may only import from explicitly
listed dependencies. This is enforced by `scripts/validate_harness.py`.

<!-- When templating: the filled-in map and table below are the worked example.
     Replace both, and replace ALLOWED_IMPORTS in scripts/validate_harness.py to
     match. A fictional second example used to sit here; it was 900 characters of
     SessionStart budget describing a project that does not exist. -->

This repo's live map. It mirrors `ALLOWED_IMPORTS` in `scripts/validate_harness.py`
exactly and the two must be edited together.

> **By hand — nothing checks it.** The linter enforces `ALLOWED_IMPORTS` against
> the code and never reads this file. Until 2026-09-21 this said the two "are
> checked against each other"; the table below had sat unfilled the whole time
> and no run ever went red.

```
cli/              ← Entrypoints: init, reconcile, render, review, sync.
                    May import: github, interview, renderer, stonehaven
stonehaven/       ← Orchestration: admin_api, listener, registry, worker.
                    May import: github, notifications, reviewers, verdict_store
github/           ← GitHub API I/O: issues, pr, webhook.   May import: reviewers
reviewers/        ← Dispatch and verdict models.           May import: github
renderer/         ← Template composition, lockfile, validators.  Imports nothing internal.
interview/        ← Analysis.                                    Imports nothing internal.
notifications/    ← Publishing.                                  Imports nothing internal.
verdict_store/    ← Verdict persistence: client, models.         Imports nothing internal.
templates/        ← 3 role templates + 4 _shared partials, zero .py — not
                    importable. Covered by tests/test_templates.py and
                    tests/test_shared_partials.py.
tests/
```

**Known exception — `github` ↔ `reviewers` is a cycle.** `github/issues.py:20` imports
`reviewers.verdicts.Finding`; `reviewers/dispatch.py:11` imports `github.pr.PRDiff`.
Both are type-only, which usually means the two names belong in a shared module
neither package owns. It is recorded in `KNOWN_CYCLES` so that any *new* cycle
fails the linter; do not add to that set without a written reason.

> Until 2026-08-24 the map above was the unfilled template placeholder and
> `ALLOWED_IMPORTS` still held the example modules, so the linter walked **zero
> files** and "Harness Structure" passed as a required check while verifying
> nothing. If you are templating this repo, replacing both is step one, and the
> linter now fails on `files_checked == 0` rather than letting it pass quietly.

### Invariants (enforced by structural linter — `scripts/validate_harness.py`)

<!-- Both columns must agree with ALLOWED_IMPORTS in scripts/validate_harness.py. -->

| Module | May import from | Must NEVER import from |
|---|---|---|
| `interview/` | _(nothing internal)_ | everything |
| `notifications/` | _(nothing internal)_ | everything |
| `renderer/` | _(nothing internal)_ | everything |
| `verdict_store/` | _(nothing internal)_ | everything |
| `github/` | `reviewers` | `cli`, `interview`, `notifications`, `renderer`, `stonehaven`, `verdict_store` |
| `reviewers/` | `github` | `cli`, `interview`, `notifications`, `renderer`, `stonehaven`, `verdict_store` |
| `stonehaven/` | `github`, `notifications`, `reviewers`, `verdict_store` | `cli`, `interview`, `renderer` |
| `cli/` | `github`, `interview`, `renderer`, `stonehaven` | `notifications`, `reviewers`, `verdict_store` |

`templates/` is in pyproject's `packages` list but holds only `.md` files, so it is
not importable and has no row. `tests/` and `scripts/` are not boundary-tracked.

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

### ⚠️ For this repo: read `.factory/project_context.md` > `sharp_edges`

`agent-harness` keeps its warnings there rather than here, because that file is
Layer 2 of the agent composition and is what the three reviewers are rendered
from — a warning written here reaches an agent's context; one written there also
reaches every reviewer judging the result. Seven are on record, covering the
dispatch gate, the holding-label gate, `compound-learning.yml`'s direct push to
`main`, `gc-agent.yml`'s missing `--allowedTools`, the protected-path guard on
`.claude/`, `[tool.ruff] exclude`, and the two-PAT split.

When templating this repo, write project warnings as DO/DON'T pairs under this
heading, in the shape of the commented example above.

---

## Harness Lessons — Read Before Writing Any Code

Lessons 1–3 were discovered during initial bootstrap. Lessons 4–13 were learned
the expensive way in `jtmurphysr/elp-mosaic` across 41 agent-authored PRs and
distilled here as rules; the case histories stay in that repo's `docs/learnings/`.
A rule in this section is current law. If a lesson's cause is fixed and the rule
no longer binds, delete it — this section is not an archive.

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
`Closes #N` here is **your own issue** and nothing else. See LESSON 5 before
writing a closing keyword against any other issue number.

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

### ⚠️ LESSON 4: Out-of-scope findings — check first, then file, never defer

If you find a real defect outside your issue's scope, do not fix it in your PR
and do not leave it only in a PR comment. Auto-merge means no human reads the
PR between open and merge; a finding that lives only there is lost.

1. **Search before filing.** `gh issue list --search "<file or symbol>" --state open`.
   If it is already on file, comment there with what you saw and move on.
2. If it is new, open it labelled `human-review`, and cite the number in your PR body.

Five agents in one generated project filed the same `.venv` finding five times
because step 1 did not exist. Do step 1.

### ⚠️ LESSON 5: A closing keyword is an executable instruction

Under auto-merge, GitHub acts on `Closes #N` unreviewed and the issue leaves the
dispatch queue permanently. Reopening it does not restore its place in the chain.

- Write `Closes #N` **only for the issue you were dispatched on.**
- For any other issue your PR advances, **read its current comments first** —
  issues are re-scoped while a chain is in flight — and write `Refs #N` with a
  sentence on what remains.
- **Writing *about* the keyword executes it.** GitHub scans the whole body;
  backticks, quotation marks and negation do not exempt it. Say "the closing
  keyword for #N", never the keyword itself.
- `close-issue-on-merge.yml` matches only the **first** `Closes #N` and uses that
  number to compute the next dispatch. A stray keyword above your own line
  reroutes the chain.

### ⚠️ LESSON 6: When the issue spec and reality disagree, here is who wins

Issue specs are written before the code runs. Three kinds of conflict, three rules:

- **INTERFACE CONTRACT vs REQUIRED TESTS → the tests win.** The contract is
  illustrative; the tests are executable. Keep the specified test name, change
  the mechanism to one that actually reaches the target line.
- **INTERFACE CONTRACT vs OUT OF SCOPE prose → the contract wins.** The prose
  summarises the pre-change state, usually written first; the contract is the
  prescription.
- **Any premise about what `main` currently looks like → unverified until you
  check it.** "Stays as it is", "unchanged from", "as today" — `grep` it against
  your branch point before treating it as a constraint. A false prescription
  fails loudly; a false premise is inert and you ship the wrong thing green.

Never assert defective behaviour as the contract. If the only way to reach a line
is through a bug, cover it with `@pytest.mark.xfail(strict=True)` naming the
issue, and assert the **correct** contract — the eventual fix then fails via
XPASS, which is the signal to drop the marker. Declare every such resolution in a
named PR-body section.

### ⚠️ LESSON 7: An aggregate coverage number proves nothing about any one file

`--cov-fail-under` gates the total. A module can sit at 0% under a green total.
And `coverage report` rounds to integer percent, so `84.69%` prints as `85%` —
the sub-floor band is invisible at default precision.

- Per-file floors are enforced in CI by `scripts/check_coverage_floor.py` (raw
  float comparison, two decimals), as a step after the total gate. Run it locally
  with `coverage json -o coverage.json && python scripts/check_coverage_floor.py`.
- `[tool.coverage.report] precision = 2` is set, so every report you see prints
  two decimals. If you see an integer percentage, you are looking at stale output.
- A COVERAGE REQUIREMENTS floor *above* the module's current figure is a hidden
  test requirement: the named tests are not sufficient by construction. Measure
  first, then write.

### ⚠️ LESSON 8: `asyncio.run()` inside a test deadlocks silently

`asyncio_mode = "auto"` is set. Never call `asyncio.run()` in a test — it hangs
CI at a fixed percentage forever with no error. Use `async def` (pytest-asyncio
owns the loop) or the synchronous `TestClient`. No exceptions.

### ⚠️ LESSON 9: `client.get()` on a streaming endpoint never returns

Any route that returns `StreamingResponse` blocks a plain `client.get()` until
the stream closes — which for a heartbeat loop is never. Use
`client.stream("GET", path)` as a context manager. If the endpoint has a
heartbeat, disable it via its env var with `monkeypatch.setenv()` first.

The same hazard applies to **middleware**: anything that consumes
`response.body_iterator` must exempt streaming endpoints, or the request hangs.
The hang presents as a dead endpoint, not a failing test.

### ⚠️ LESSON 10: Asserting on a field that has a default proves nothing

If a response model declares `voice: str = "mosaic"`, then
`assert body["voice"] == "mosaic"` passes with the enforcement code deleted.
It tests the default, not the mechanism. Assert on something the mechanism
*adds* and nothing defaults — a block, a header, a computed field. To test the
enforcer in isolation, drive a route that omits the field entirely.

This is Governing Principle 2 applied to tests: coverage proves the code runs,
not that it enforces.

### ⚠️ LESSON 11: Forbid a duplicated helper with a test, not a comment

When one function must be the only implementation of something (a parser, a
validator, a client), add a test that reads the candidate modules with
`inspect.getsource` and fails if the forbidden name or call reappears. A comment
saying "do not duplicate this" is read once; the test is run every PR. Five
copies of one timestamp parser shipped in a generated project before the test
existed; none since.

### ⚠️ LESSON 12: "0 commits, no PR" is not proof the cycle failed

The dispatch workflow's empty-branch guard runs *after* the agent step and cannot
distinguish "nothing committed" from "already merged." It has posted that comment
seconds after a green merge, with a re-dispatch instruction that would redo
merged work. **Before acting on it, check for a merged PR whose head was that
branch.** Red dispatch runs with green merges behind them make dispatch health
unreadable; do not add to the noise.

### ⚠️ LESSON 13: Lint every tree, or say exactly which you do not

`[tool.ruff] exclude` **replaces** ruff's defaults — use `extend-exclude`. And a
test-only PR whose test directory is excluded passes every pre-PR step without
its one changed file being read. This template now lints `tests/` and `scripts/`.
If a project ever excludes a tree, AGENTS.md must name it and say why; "no
exceptions" with a silent exception is the defect, not the policy.

### ⚠️ LESSON 14: A gate on one trigger is not a gate

`human-review` blocked dispatch — on the `labeled` event. The auto-advance path
(`workflow_dispatch` from `close-issue-on-merge.yml`) and `/agent retry` went
around it, because a job-level `if:` can only read what the payload carries, and
those payloads carry no labels. The caller said "the dispatcher gates"; the
dispatcher gated the path the caller never used. A held issue got an agent the
moment its predecessor merged. **Every gate lives in one job that every trigger
depends on**, reads its input itself, and fails when it cannot. If a check sits
in an `if:` expression, ask which events can reach the job without it.

### ⚠️ LESSON 15: Read GitHub with `gh api`, never `gh pr view --json`

<!-- added after PR #30 — third occurrence, see docs/learnings/pr-30.md -->

`gh pr view --json` and `gh issue view --json` route through GraphQL, whose
`login`, `name` and `slug` fields require the `read:org` scope. `GH_PAT`
deliberately carries `repo` and nothing else, so those calls fail with a scope
error in CI and in any agent session — including read-only ones, and including
the compound-learning agent, which is how this became a lesson rather than a
comment. Use REST:

```bash
gh api "repos/$repo/pulls/$pr" -q '.body'          # not: gh pr view --json body
gh api "repos/$repo/pulls/$pr/files" --paginate -q '.[].filename'
gh api "repos/$repo/issues/$n/comments" -q '.[].body'
```

`gh pr create`, `gh pr diff` and `gh issue list` are fine. It is the `--json`
flag on `view` that crosses into GraphQL.

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
- Type hints on **all** function signatures — no exceptions in source. **Known waiver:**
  `tests/` is under a mypy ratchet (`[[tool.mypy.overrides]]` in `pyproject.toml`) that
  waives untyped test signatures and a named list of error codes while the existing debt
  is paid down. New test code should still be fully typed; the waiver keeps CI green, it
  does not make the debt acceptable. Removing a code from that list is how the check
  comes back on. Tracked in the follow-up to #12.
- Pydantic v2 for all data models in `models.py`
- `ruff` for linting and formatting — **every** directory, including `tests/` and
  `scripts/`. There is no excluded tree. (There was, silently, until #12.)
- `mypy --strict` — no `type: ignore` without an inline comment explaining why

### Async
- All API calls are `async` — use `httpx.AsyncClient`, not `requests`
- Use `asyncio.gather()` for concurrent operations where order doesn't matter
- The CLI entrypoint runs via `asyncio.run(main())`

### Logging
- `structlog` — structured JSON only
- Every client method and pipeline stage logs entry + exit + exceptions
- Fields: `event`, `module`, `duration_ms`, plus domain-relevant identifiers
- **Never use `print()` in production code.** The example map in this template routes
  CLI output through a `reporter.py`; **this repo has no such module**, so the rule
  here is `structlog` or nothing. One violation is on record and unfixed —
  `cli/init.py:764` prints the created PR URL. Do not add a second, and do not cite
  `reporter.py` as though it existed.

### Environment Variables
All secrets via env vars. Fail loud and early if any are missing:

```python
import os


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"See README.md > Getting Started for configuration instructions."
        )
    return value
```

Required vars:
<!--
When templating this repo, list all required environment variables for your project.
Example:
- `SERVICE_A_API_KEY`
- `SERVICE_B_CLIENT_ID`
- `SERVICE_B_CLIENT_SECRET`
-->

**This repo reads none.** No module under `cli/`, `github/`, `interview/`,
`notifications/`, `renderer/`, `reviewers/`, `stonehaven/`, `verdict_store/` or
`scripts/` calls `os.environ` or `os.getenv`; credentials are passed in as
arguments by the caller. The secrets that exist are consumed by GitHub Actions,
not by Python:

| Secret | Consumed by | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | every `claude-code-action` step | Agent invocation |
| `GH_PAT` | gates, labels, comments, auto-merge | Read and annotate; **no** workflow scope |
| `GH_WORKFLOW_PAT` | the agent's `git push` only | Pushes touching `.github/workflows/` |

Add a row here the moment a module starts reading one, and use `_require_env`
above so a missing value fails before the first network call.

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

Every row below names a path that exists. Four of them did not until 2026-09-21
— `docs/setup.md`, `docs/conventions.md` and `docs/decisions/` were never created
and `docs/architecture.md` was written by that GC pass. A map to documents that
do not exist costs an agent a failed `Read` and a guess about where the answer
actually lives; if you add a row, add the file.

| Document | Purpose |
|---|---|
| `AGENTS.md` | This file. Operating constitution. |
| `docs/architecture.md` | The three layers, module map, data flow, enforcement points |
| `README.md` | Credential provisioning, environment setup, getting started |
| `AGENTS.md` > Code Conventions | Patterns and anti-patterns |
| `docs/learnings/` | Case histories behind the Harness Lessons above |
| `docs/harness-hardening-plan.md` | Standing hardening backlog, with per-phase status |
| `.factory/project_context.md` | This project's invariants, sharp edges, reviewer set |
| `scripts/validate_harness.py` | Boundary linter (3 passes) |
| `scripts/check_coverage_floor.py` | Per-file coverage floor gate |

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
