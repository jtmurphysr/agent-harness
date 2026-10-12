# Architecture

The module map, the data flow between modules, and the data contracts that cross
module lines. `AGENTS.md` > Module Boundaries is the enforceable version of the
first of those — `scripts/validate_harness.py` reads it and fails CI. This file is
the explanation: what each layer is for, what actually calls what, and where the
map and the running code currently disagree.

Written 2026-10-12 by the GC agent against the code as it stands. If you change a
boundary, change `AGENTS.md`, `ALLOWED_IMPORTS` in `scripts/validate_harness.py`,
and this file together.

---

## Three layers in one repository

The repo holds three things that are easy to confuse for each other:

| Layer | What it is | Where it lives |
|---|---|---|
| **Core harness** | Code that scaffolds and operates generated project repos | `cli/`, `renderer/`, `interview/`, `github/`, `scripts/` |
| **Template payload** | Files copied or rendered *into* generated repos | `AGENTS.md`, `pyproject.toml.template`, `.github/workflows/`, `templates/`, `scripts/validate_harness.py` |
| **Triumvirate extension** | The review subsystem: listener, worker, three reviewers, verdict store | `stonehaven/`, `reviewers/`, `verdict_store/`, `notifications/` |

Two of those overlap deliberately. `scripts/validate_harness.py` is both a working
linter for this repo and the linter template every generated project receives; the
`ALLOWED_IMPORTS` map at its top is the part a generated project replaces.
`AGENTS.md` is the same shape — its Module Boundaries section is filled in for this
repo, while Repository Identity, Critical Agent Warnings and the Invariants table
are still the unfilled template placeholders a generated project fills in.

---

## Module map

```
cli/              init, reconcile, render, review, sync
  └── imports: github, interview, renderer, stonehaven

stonehaven/       admin_api, listener, registry, worker
  └── imports: github, notifications, reviewers, verdict_store

github/           issues, pr, webhook          └── imports: reviewers
reviewers/        dispatch, models, verdicts   └── imports: github

renderer/         compose, lockfile, validators    └── imports nothing internal
interview/        analyzer                         └── imports nothing internal
notifications/    publisher                        └── imports nothing internal
verdict_store/    client, models                   └── imports nothing internal

templates/        7 .md files, zero .py — payload, not importable
scripts/          tools, no __init__.py — not a package, carries no boundary rule
```

**The one accepted cycle is `github` ↔ `reviewers`.** `github/issues.py` imports
`reviewers.verdicts.Finding`; `reviewers/dispatch.py` imports `github.pr.PRDiff`.
Both are type-only, which is the usual sign that two names belong in a shared
module neither package owns. It is recorded in `KNOWN_CYCLES` so that any *new*
cycle fails the linter.

---

## Data flow: a review

This is the Triumvirate extension's only path, end to end.

```
GitHub webhook (pull_request)
      │
      ▼
stonehaven/listener.py  WebhookHandler.handle_webhook
      │   verifies HMAC on X-Hub-Signature-256
      │   deduplicates on X-GitHub-Delivery  (in-memory set — see Known gaps)
      │   returns 200 immediately, enqueues the rest as a BackgroundTask
      ▼
stonehaven/worker.py  ReviewWorker.process_review
      │
      ├─► github/pr.py        PRClient            fetch the diff
      ├─► reviewers/dispatch.py ReviewerDispatcher dispatch engineer, architect and
      │                                           sre in parallel, blind to each other
      ├─► reviewers/verdicts.py VerdictParser      parse each reviewer's verdict block
      ├─► verdict_store/client.py VerdictStoreClient  write verdicts, then findings
      ├─► github/issues.py    IssueCreator        open issues for findings
      └─► notifications/publisher.py NotificationPublisher  notify
```

Ordering is a durability contract, not a style choice: the Verdict Store write
must succeed **before** issue creation, so that a failure after the write is
replayable and a failure before it leaves no orphaned issues.

The reviewer prompts come from `.factory/agents/<role>.md` and the project's
`.factory/project_context.md`, read out of the repo under review at the PR's SHA.

## Data flow: rendering a project's reviewers

```
templates/<role>.template.md + templates/_shared/*.partial.md
      │                          (Jinja2, each file version-stamped in frontmatter)
      ▼
renderer/validators.py   validate_project_context   ← .factory/project_context.md
renderer/compose.py      compose_agent              → <output_dir>/<role>.md
renderer/lockfile.py     write_lock                 → <output_dir>/templates_lock.yml
      ▲
cli/render.py  render_agents   orchestrates the three
```

`scripts/render_own_agents.py` runs that same pipeline on this repository, writing
`.claude/agents/`. `scripts/validate_harness.py` Pass 3 re-renders and diffs, so a
hand-edit of `.claude/agents/` fails CI. Edit `templates/` or
`.factory/project_context.md` and re-render; never edit the rendered file.

---

## Data contracts

### The verdict block — reviewer → parser

Defined in `templates/_shared/verdict_block.partial.md`, parsed by
`reviewers/verdicts.py::VerdictParser`, which `scripts/parse_review_verdict.py`
wraps for the `review-*` CI jobs. One implementation, per AGENTS.md LESSON 11.

```
## Verdict
VERDICT: PASS | WARN | BLOCK
BLOCKING:
- <finding> (invariant: <id> | spec: <section> | scope: <issue section>)
WARNINGS:
- <finding>
```

Severity is **declared, not inferred** — taken from the `VERDICT:` line and
nowhere else. A parse failure is handled as a failed review, never as a PASS.

### The verdict store — tables and records

`verdict_store/models.py` holds the SQL; `verdict_store/client.py` holds the
dataclass per table and is the only module that is *supposed* to open SQLite.

| Table | Record dataclass | Notes |
|---|---|---|
| `projects` | `ProjectRecord` | `stonehaven_id` and `repo` are both UNIQUE |
| `verdicts` | `VerdictRecord` | `UNIQUE(delivery_id, reviewer)` is the dedupe key |
| `findings` | `FindingRecord` | `invariant_id` nullable; indexed only where non-null |

WAL mode is enabled at init for concurrent reads under webhook load.

### The admin API — response models

`stonehaven/admin_api.py` declares a Pydantic response model per endpoint
(`ProjectResponse`, `VerdictResponse`, `ProjectStatsResponse`,
`FleetStatsResponse`, `FindingResponse`, `InvariantCoverageResponse`). Each field
set matches the columns its query selects; `FindingResponse` adds `project_id`,
`project_name` and `reviewed_at`, which come from the joins to `verdicts` and
`projects` rather than from the `findings` table itself.

---

## Known gaps

Recorded here because reading the code does not reveal them and an agent that
assumes these work will write something that cannot run. Each names its issue.

- **Nothing executes `cli/` or `stonehaven/`.** `pyproject.toml` declares no
  `[project.scripts]` and no module has a `__main__`. The `harness render` and
  `harness sync` commands named in `.claude/agents/*.md` and in
  `docs/harness-hardening-plan.md` do not exist; `create_listener_app` and
  `create_admin_router` have no production caller, which is also why `uvicorn` is
  a declared dependency nothing imports (#60, #35).
- **`renderer/lockfile.py::update_template_version` is exported and never called.**
  `cli/render.py` round-trips the whole version map instead (#59).
- **`harness sync` could not upgrade anything even if invoked.** `cli/render.py`
  writes the lock to `<output_dir>/templates_lock.yml` under `.factory/agents/`;
  `cli/sync.py` reads `.factory/templates_lock.yml` (#57).
- **`admin_api` and `cli/reconcile` open SQLite directly**, against the contract
  in `verdict_store/client.py`'s own docstring, because
  `ProjectRegistry.list_projects()` raises `NotImplementedError` (#34).
- **Webhook dedupe is an in-memory `set`.** It does not survive a restart, and it
  is not atomic. Phase 7 of the hardening plan is the fix.
- **The admin bearer check compares against the literal `"admin-token"`** in
  source, on both the server and the client side (#55).
