# Architecture

What is in this repository, which layer each file belongs to, and how the two
runtime flows move through it.

`AGENTS.md > Module Boundaries` is the **normative** import graph and is enforced
by `scripts/validate_harness.py`. This document does not restate it as law; it
explains the shape the graph has, and covers the parts of the repo that are not
Python packages and therefore have no boundary rule at all.

---

## The three layers

A file in this repo belongs to exactly one of these. Confusing them is the single
most common orientation error, because `AGENTS.md`, `scripts/` and `.github/` all
appear in two roles at once — executed here, *and* copied into generated repos.

### 1. Harness implementation — code this repo runs

Eight source packages, plus `tests/`. These are the product: they scaffold,
register, review, and reconcile generated project repos.

| Package | Owns |
|---|---|
| `cli/` | Entrypoints — `init`, `reconcile`, `render`, `review`, `sync` |
| `stonehaven/` | The long-running service — `listener` (FastAPI webhook), `worker` (review pipeline), `registry`, `admin_api` |
| `github/` | GitHub API I/O — `issues`, `pr`, `webhook`. No business logic. |
| `reviewers/` | Reviewer fan-out (`dispatch`), verdict parsing (`verdicts`), model selection (`models`) |
| `renderer/` | Jinja2 composition (`compose`), `templates_lock.yml` I/O (`lockfile`), `project_context.md` schema (`validators`) |
| `interview/` | Repo analysis for brownfield onboarding (`analyzer`) |
| `notifications/` | ntfy publishing (`publisher`) |
| `verdict_store/` | SQLite schema (`models`) and the client over it (`client`) |
| `tests/` | One file per source module |

### 2. Template payload — files copied into generated repos

`AGENTS.md`, `pyproject.toml.template`, `.github/workflows/`, `scripts/`,
`.github/ISSUE_TEMPLATE/`, and `templates/`. The harness dogfoods all of it: the
same `AGENTS.md` that generated projects receive is this repo's own constitution,
and the same `validate_harness.py` they get is the one gating this repo's PRs.

That dual role is why `AGENTS.md` still carries `<PROJECT-NAME>` and an empty
`Critical Agent Warnings` section while its `Module Boundaries` block is filled in
with this repo's real graph. Project-specific content is supposed to arrive via
`.factory/project_context.md`, not by filling the constitution in — except for the
boundary map, which the linter needs and which therefore has to be concrete.
`docs/harness-hardening-plan.md` Phase 1 is the open proposal to split these.

### 3. Triumvirate extension — the review subsystem

`stonehaven/`, `reviewers/`, `verdict_store/`, `notifications/`, `templates/`, and
the three `review-*` jobs in `ci.yml`. Optional in principle; in practice this
repo requires all three reviewer verdicts before auto-merge
(`AGENTS.md > Definition of Done`).

---

## Import graph

Arrows point the way imports go. The full allow-list, including each module's
forbidden set, is the table in `AGENTS.md > Module Boundaries`.

```
          cli/  ──────────────┬──────────────┬──────────────┐
           │                  │              │              │
           ▼                  ▼              ▼              ▼
      stonehaven/         interview/     renderer/       github/ ◄──┐
       │   │   │                                            │       │
       │   │   └──────────────► verdict_store/              └──────►│
       │   └──────────────────► notifications/                  reviewers/
       └──────────────────────► reviewers/ ─────────────────────────┘
```

Three properties are worth stating because they are load-bearing:

- **`cli/` cannot see `verdict_store/` or `notifications/`.** It reaches both
  through `stonehaven/` — `cli/reconcile.py` and `cli/sync.py` import
  `stonehaven.registry`, which owns the `VerdictStoreClient`. This is what keeps
  persistence swappable behind one package.
- **`github/` ↔ `reviewers/` is a cycle, accepted explicitly.**
  `github/issues.py` imports `reviewers.verdicts.Finding`; `reviewers/dispatch.py`
  imports `github.pr.PRDiff`. Both are type-only — the usual sign that two names
  belong in a shared module neither package owns. It is baselined in
  `KNOWN_CYCLES` so any *new* cycle fails the linter.
- **`renderer/`, `interview/`, `notifications/` and `verdict_store/` are leaves.**
  They import nothing internal and are testable in isolation.

`scripts/` is outside the graph: no `__init__.py`, not importable as a package by
the linter's rules, and deliberately stdlib-only. See *Known gaps* below for what
that costs.

---

## Flow A — a pull request gets reviewed

```
GitHub PR event
   │
   ▼
stonehaven/listener.py ── HMAC verify ── dedupe on X-GitHub-Delivery
   │                                      (in-memory set; see Known gaps)
   ├── returns 200 immediately  ◄── GitHub's timeout is 10s; a review is not
   │                                going to finish inside it
   ▼  (background task)
stonehaven/worker.py
   │
   ├─► github/pr.py ................ fetch PRDiff
   ├─► reviewers/dispatch.py ....... engineer + architect + sre, in parallel,
   │     └─► reviewers/models.py     each blind to the others' output
   ├─► reviewers/verdicts.py ....... parse the mandatory verdict block
   │                                 (templates/_shared/verdict_block.partial.md)
   ├─► verdict_store/client.py ..... write verdict, THEN findings
   │                                 ⚠ this write must succeed before the next step
   ├─► github/issues.py ............ open issues for findings
   └─► notifications/publisher.py .. ntfy
```

Two entrypoints rejoin this pipeline rather than duplicating it:
`cli/review.py` (manual invocation, synthesises a delivery ID) and
`cli/reconcile.py` (walks recent merged PRs and reviews any with no Verdict Store
row — the recovery path for deliveries missed while the listener was down).

`stonehaven/admin_api.py` is read-side only: a FastAPI router mounted on the same
app, serving project/verdict/finding/fleet queries.

## Flow B — a project gets scaffolded and kept current

```
.factory/project_context.md          (the project's own specifics)
   │
   ▼
renderer/validators.py ── schema check
   │
   ▼
cli/render.py ── renderer/compose.py ── Jinja2 over templates/*.template.md
   │                                     + templates/_shared/*.partial.md
   ├──► <output_dir>/{engineer,architect,sre}.md
   └──► <output_dir>/templates_lock.yml     via renderer/lockfile.py

cli/init.py   calls the above with output_dir = .factory/agents/,
              then generates .factory/harness.toml + webhook_config.yml,
              registers with Stonehaven, and registers the GitHub webhook
              (github/webhook.py).

cli/sync.py   reads each fleet project's .factory/templates_lock.yml, diffs it
              against the harness's current template versions, and opens an
              upgrade PR.
```

The harness renders its own reviewers through this exact path:
`scripts/render_own_agents.py` runs `cli.render.render_agents` over `templates/` +
`.factory/project_context.md` into `.claude/agents/`, and `validate_harness.py`
Pass 3 fails if the checked-in output differs from a fresh render. A renderer bug
therefore breaks this repo's own CI before it reaches a generated project.

---

## Enforcement

| Check | What it reads | Fails on |
|---|---|---|
| `scripts/validate_harness.py` Pass 1 | AST of every file in a tracked package | An import outside `ALLOWED_IMPORTS`; also **zero files checked**, which is how this linter once passed green while pointed at modules that did not exist |
| Pass 1b | `ALLOWED_IMPORTS` itself | Any cycle not in `KNOWN_CYCLES`; also reports a `KNOWN_CYCLES` entry whose cycle is gone |
| Pass 2 | `[tool.coverage.run] omit` | An implemented module (real logic, not stubs) still omitted |
| Pass 3 | `templates/`, `.factory/project_context.md`, `.claude/agents/` | Checked-in agent definitions that differ from a fresh render |
| `scripts/check_coverage_floor.py` | `coverage.json` | Any single measured file below 85.00%, compared as a raw float |
| `tests/test_validate_harness.py::TestAgentsMdBoundaryDoc` | `AGENTS.md` | The prose boundary map or its invariants table drifting from `ALLOWED_IMPORTS` |
| `scripts/check-spec-conformance.sh` | PR body + changed files | A `## Files` entry the diff does not touch |
| `.claude/hooks/gate-done.sh` | `Stop` event | The model declaring completion with the linter or the suite red |

---

## Known gaps

Recorded here so the diagrams above are not read as a description of a finished
system. Each is tracked; do not re-file.

- **`verdict_store/client.py` is not the only module that opens SQLite**, despite
  its docstring saying so — `stonehaven/admin_api.py` and `cli/reconcile.py` query
  directly. Issue #34.
- **Webhook dedupe is an in-memory `set`**, so duplicate deliveries survive a
  listener restart. `docs/harness-hardening-plan.md` Phase 7.
- **Reviewer dispatch returns canned text**; there is no real model adapter behind
  `reviewers/dispatch.py`. Phase 8.
- **The template upgrade path in Flow B does not connect.** `cli/render.py` writes
  the lockfile under its `output_dir`, which `cli/init.py` sets to
  `.factory/agents/`, while `cli/sync.py` reads `.factory/templates_lock.yml`.
  The `404` is swallowed as "not fully initialized", so no upgrade PR is ever
  opened and the failure is indistinguishable from "fleet is up to date".
  Issue #57, and `docs/harness-hardening-plan.md` Phase 5.
- **`scripts/` is invisible to coverage unless a test imports it.** Coverage only
  walks importable directories for unmeasured files, and `scripts/` has no
  `__init__.py`, so an unimported script is absent from `coverage.json` rather
  than present at 0% — and the per-file floor gate can only judge what is in the
  report. Issue #42.
- **`stonehaven/admin_api.py` compares the bearer token against a literal in
  source.** Issue #55.
