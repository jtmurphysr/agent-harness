# Agent Harness Hardening Plan

## Status — verified 2026-09-21 (GC pass)

This plan was written against an earlier tree and some of it has landed. Each phase
below now opens with a status line. Three paths it refers to do not exist in this
repository and never did: **`harness-gen/`**, **`docs/PRD.md`** (the input
`prd-to-issues` reads in a *generated* project — this repo has no PRD of its own),
and **`.workstream`** (gitignored, untracked). Actions naming them are struck
through rather than deleted, so the plan still reads as the document it was.

| Phase | Status |
|---|---|
| 1. Clarify repository boundaries | **Partly landed** — `docs/architecture.md` now exists; README still never explains `project_context.md` |
| 2. Split validation | **Partly landed** — the zero-file guard is in; no separate `validate_repo.py`, and the boundary linter became the root-repo linter rather than staying payload-only |
| 3. Repository hygiene | **Landed**, except the CI hygiene check |
| 4. Config and secrets | **Open** — `stonehaven/listener.py:30` still defaults `webhook_secret="webhook-secret-placeholder"` |
| 5. Generated artifact locations | **Landed** — `.factory/templates_lock.yml` is the path everywhere |
| 6. Verdict store and registry boundaries | **Open** — 8 direct-SQL sites outside `verdict_store/` |
| 7. Durable webhook processing | **Open** — `stonehaven/listener.py:42` dedupes in an in-process `set` |
| 8. Real reviewer adapters | **Open** — `reviewers/dispatch.py:300` returns a canned string; superseded in approach by issue #29 |
| 9. Worker concurrency and file handling | **Open** — `stonehaven/worker.py:318` writes `/tmp/agent_<role>.md` |
| 10. CLI consistency | **Mostly landed** — one `print()` remains, `cli/init.py:764`; no `[project.scripts]`, no dry-run modes |
| 11. Test strategy | **Partly landed** — `slow` marker and default deselect are in; the taxonomy is not |

## Purpose

This document lists the actions I would take to make the repository easier to operate, validate, and evolve as a harness for building Python applications with GitHub workflows and Claude Code.

The key assumption is that `AGENTS.md` is intentionally template-like. It is part of the payload copied into generated projects. Project-specific instructions, invariants, sharp edges, and domain context are supplied by generated `project_context.md` files.

The plan separates three concerns:

- **Core harness**: the code that scaffolds and operates generated Python app repos.
- **Template payload**: files copied or rendered into generated repos, including `AGENTS.md`, `pyproject.toml.template`, workflows, scripts, and role templates.
- **Triumvirate extension**: the Stonehaven/reviewer/verdict-store subsystem added by the review-system update.

## Desired End State

- The repo makes it obvious which files are harness implementation and which files are generated-project template payload.
- Root CI validates the harness implementation intentionally, without accidentally linting embedded/generated reference repos.
- Template payload validation remains available for generated projects.
- The Triumvirate extension is clearly marked as an optional subsystem with its own maturity gates.
- Security-sensitive configuration is never hard-coded or committed in plaintext.
- The review pipeline has durable dedupe, real reviewer invocation adapters, and database access through one client boundary.

## Phase 1: Clarify Repository Boundaries

### Actions

1. Add a short architecture document describing the three layers:
   - core harness implementation
   - generated-project template payload
   - Triumvirate extension

2. Update `README.md` to explain that:
   - `AGENTS.md` is a portable template constitution
   - `project_context.md` carries project-specific instructions
   - `AGENTS.md + project_context.md` together form the agent contract in generated repos

3. ~~Move or document `docs/PRD.md` as a historical subsystem PRD rather than the root product definition.~~ — moot: this repo has no `docs/PRD.md`. The path is the *generated project's* PRD input, read by `prd-to-issues.yml`.

4. ~~Decide the intended status of `harness-gen/`.~~ — moot: no such directory exists.

### Acceptance Criteria

- A new contributor can identify which files are copied into generated apps versus executed by the harness itself.
- No documentation implies the Triumvirate PRD is the root source of truth for the whole repo.
- Root quality gates no longer accidentally include reference/generated material.

## Phase 2: Split Validation Between Harness Repo and Generated Apps

### Actions

1. Keep `scripts/validate_harness.py` as a generated-project structural linter template, but make that role explicit in comments and docs.

2. Add a separate root-repo validation script for the harness implementation, for example `scripts/validate_repo.py`.

3. Have root CI run the root-repo validator instead of treating the generated-project validator as meaningful for this repo.

4. Add a guard to the generated-project linter so `Files checked: 0` is either:
   - allowed only in explicit template mode, or
   - treated as a failure when running in project mode

5. Align `pyproject.toml` exclusions with the intended repo structure:
   - ~~exclude `harness-gen/` if it remains reference material~~ — moot, see above
   - exclude cache/artifact paths
   - ~~decide whether scripts are linted as first-class code or intentionally excluded~~
     — **decided**: `extend-exclude = []`, `scripts/` and `tests/` are linted like
     everything else (issues #12/#15). `scripts/` remains excluded from **mypy**
     only, for a packaging reason stated in `pyproject.toml`.

### Acceptance Criteria

- Root CI validates actual harness modules.
- Generated apps still receive a customizable boundary linter.
- A zero-file structural lint pass cannot masquerade as meaningful enforcement.

## Phase 3: Clean Repository Hygiene

### Actions

1. Remove generated artifacts from version control if present:
   - `__pycache__/`
   - `.DS_Store`
   - `.coverage`
   - `.ruff_cache/`

2. Update `.gitignore` to cover those artifacts consistently.

3. ~~Decide whether `.claude/` and `.workstream` are intended repo artifacts.~~
   — **decided**: `.claude/` is tracked deliberately (executable config, listed in
   `CODEOWNERS`); `.workstream` is gitignored and not present.

4. Add a lightweight hygiene check to CI for forbidden committed artifacts.

### Acceptance Criteria

- Fresh test/lint runs do not leave confusing untracked noise.
- Committed files are intentional source, templates, docs, or fixtures.
- CI catches accidental committed cache files.

## Phase 4: Make Configuration and Secrets Production-Safe

### Actions

1. Replace hard-coded Stonehaven admin token usage with configuration from environment or an operator-managed secret store.

2. Replace hard-coded listener defaults such as `webhook-secret-placeholder` with explicit required configuration.

3. Stop writing plaintext webhook secrets to committed project files.

4. Store only non-secret metadata in `.factory/webhook_config.yml`.

5. Use OS keyring, `pass`, or another operator-managed secret backend for webhook secrets and GitHub PATs.

6. Add tests proving secrets are not logged or serialized into generated project manifests.

### Acceptance Criteria

- Missing required secrets fail loudly before network calls.
- No committed `.factory/*` manifest contains plaintext webhook secrets or PATs.
- Admin authentication behavior is configurable and test-covered.

## Phase 5: Fix Generated Artifact Locations and Drift Validation

### Actions

1. Move template lock handling to `.factory/templates_lock.yml`, matching the intended generated-project layout.

2. Keep rendered agents in `.factory/agents/*.md`.

3. Update render, init, sync, and generated-file validation tests to use the same lockfile path.

4. Strengthen generated-file drift validation so it compares:
   - template versions
   - rendered agent content
   - enabled/disabled reviewer set

5. Add a clear command or pre-commit entry for generated-project repos.

### Acceptance Criteria

- `harness render` produces the exact documented `.factory/` layout.
- `harness sync` and drift validation read/write the same lockfile.
- Manual edits to generated agents are detected reliably.

## Phase 6: Complete Verdict Store and Registry Boundaries

### Actions

1. Add missing read APIs to `verdict_store/client.py`, including:
   - list active projects
   - verdict existence by project and PR
   - fleet findings queries
   - invariant coverage queries

2. Refactor `stonehaven/admin_api.py` to stop querying SQLite directly.

3. Refactor `cli/reconcile.py` to stop querying SQLite directly.

4. Implement `ProjectRegistry.list_projects()` through `VerdictStoreClient`.

5. Add transaction coverage for multi-table writes where verdicts and findings must remain consistent.

### Acceptance Criteria

- `verdict_store/client.py` is the only module that opens SQLite connections.
- Registry, admin API, reconcile, and worker code use explicit client methods.
- Fleet sync and reconciliation no longer depend on direct SQL workarounds.

## Phase 7: Make Webhook Processing Durable

### Actions

1. Persist webhook delivery IDs instead of using an in-memory `set`.

2. Make dedupe atomic at the storage layer.

3. Store enough delivery metadata to support reconciliation and debugging:
   - delivery ID
   - repo
   - event type
   - received timestamp
   - processing status

4. Keep webhook response fast by acknowledging after durable enqueue/dedupe, not after review completion.

5. Add restart and duplicate-delivery tests.

### Acceptance Criteria

- Duplicate deliveries are rejected across process restarts.
- Listener remains fast and does not block on reviewer execution.
- Failed background reviews can be inspected and reconciled.

## Phase 8: Replace Mock Reviewer Execution With Real Adapters

### Actions

1. Define a reviewer invocation interface that hides provider details from `ReviewerDispatcher`.

2. Implement a local inference adapter for the operator's local model endpoint.

3. Implement a Claudegate/cloud fallback adapter.

4. Enforce project monthly cost caps in a durable store, not only in process memory.

5. Make adapter selection explicit in configuration.

6. Keep deterministic fake adapters for tests.

### Acceptance Criteria

- Production reviewer dispatch no longer returns canned review text.
- Tests can still run without external model calls.
- Cost cap behavior survives process restart.
- Reviewer failures are isolated so one failed role does not necessarily fail the whole review.

## Phase 9: Harden Worker Concurrency and File Handling

### Actions

1. Stop writing reviewer prompts to fixed paths like `/tmp/agent_engineer.md`.

2. Pass prompt content directly to dispatch where possible.

3. If files are required, use unique temporary directories and clean them up.

4. Add concurrent-review tests for multiple repos and PRs.

5. Ensure all long-lived async HTTP clients have a clear lifecycle and are closed.

### Acceptance Criteria

- Concurrent reviews cannot overwrite each other's temporary prompt files.
- No stale prompt content remains in predictable temp paths.
- Client lifecycle is explicit in worker construction and shutdown.

## Phase 10: Make CLI Behavior Consistent

### Actions

1. Replace production `print()` calls with a CLI reporting layer or structured logger.

2. Expose actual command entrypoints if the harness is intended to be installed as a CLI.

3. Make CLI side effects explicit:
   - local file writes
   - git branch/commit/push
   - GitHub PR creation
   - Stonehaven registration

4. Add dry-run modes for init, sync, reconcile, and review where practical.

5. Add clear failure messages for missing git remotes, missing credentials, and missing project context.

### Acceptance Criteria

- CLI output is consistent and testable.
- Dangerous or networked side effects are visible in command behavior.
- Dry-run output is useful enough to review planned changes before execution.

## Phase 11: Rebuild Test Strategy Around Current Reality

### Actions

1. Classify tests into:
   - core harness unit tests
   - generated-template tests
   - Triumvirate extension tests
   - slow/soak/integration tests

2. Ensure default `pytest` runs the current reliable test set.

3. Mark network, soak, and aspirational subsystem tests explicitly.

4. Add tests for the adjusted boundaries:
   - `AGENTS.md` remains template-like
   - generated `project_context.md` provides project specificity
   - root CI validates harness implementation separately

5. Add a dependency setup path that works consistently on Python 3.11, matching CI.

### Acceptance Criteria

- Local and CI test commands run the same default scope.
- Future-gate tests do not break day-to-day harness development unless intentionally selected.
- The test suite reflects the layered architecture.

## Suggested Implementation Sequence

1. Documentation and repo-boundary cleanup.
2. Root CI and validation split.
3. Hygiene ignore rules and artifact cleanup.
4. Lockfile path correction.
5. Verdict store API completion and direct-SQL removal.
6. Durable webhook dedupe.
7. Secret/config hardening.
8. Fleet sync unblocking.
9. Real reviewer adapters.
10. Worker temp-file and concurrency hardening.
11. CLI polish and dry-run modes.
12. Test taxonomy and slow/integration gating.

## Immediate First PR

The first PR should be deliberately small:

1. ~~Add documentation explaining the three repo layers.~~ — `docs/architecture.md` §1.
2. Update `README.md` to explain `AGENTS.md + project_context.md`. — still open.
3. ~~Exclude `harness-gen/` from root lint.~~ — moot.
4. ~~Add or update `.gitignore` for cache artifacts.~~ — done.
5. ~~Add a root validation note that `scripts/validate_harness.py` is template payload, not root-repo enforcement.~~
   — **superseded.** It is now both: real `ALLOWED_IMPORTS`, a `files_checked == 0`
   guard, and two passes (coverage-omit drift, rendered-agent drift) that only make
   sense against this repo. The note that would have been written is no longer true.

This reduces future confusion without touching the runtime behavior of the harness or the Triumvirate extension.
