# Architecture

`AGENTS.md` > Repository Knowledge Map has pointed at this file since the template
was written. It did not exist until the 2026-09-21 GC pass; this is that document.

It describes what the repository **is today**, with file and line references you can
check. Where a thing is aspirational, or declared but unenforced, it says so — an
architecture doc that describes the intended system rather than the running one is
the same defect as a linter pointed at modules that do not exist.

For what is *planned*, see `docs/harness-hardening-plan.md`. For why a particular
rule exists, see `AGENTS.md` > Harness Lessons and `docs/learnings/`.

---

## 1. Three layers, one repository

The repo is three things at once, and most confusion about it comes from reading a
file as the wrong one.

| Layer | What it is | Lives in |
|---|---|---|
| **Core harness** | Python that scaffolds and operates generated project repos | `cli/`, `renderer/`, `interview/`, `github/` |
| **Template payload** | Files copied or rendered *into* generated repos | `AGENTS.md`, `pyproject.toml.template`, `templates/`, `.github/workflows/`, `scripts/` |
| **Triumvirate extension** | The review subsystem: listener, worker, reviewers, verdict store | `stonehaven/`, `reviewers/`, `verdict_store/`, `notifications/` |

`AGENTS.md` is payload **and** this repo's live constitution. `scripts/validate_harness.py`
is payload **and** this repo's enforced boundary linter. Both facts are true
simultaneously; when you edit either, ask which role you are editing it in.

**The harness is its own first user.** `.factory/project_context.md` is this repo's
own Layer-2 context, and `.claude/agents/*.md` are its own reviewers, rendered from
`templates/` by the same code path a generated project takes. That dogfooding is
enforced: `validate_harness.py` Pass 3 re-renders and diffs.

### Agent composition — the three template layers

```
templates/*.template.md          Layer 1  — shipped to every generated project
  + templates/_shared/*.md       (shared partials: output contract, verdict block,
                                  posture directives, refusal conditions)
  + <project>/.factory/project_context.md   Layer 2 — one project's invariants,
                                             sharp edges, reviewer set
  ─────────────────────────────────────────
  = .claude/agents/<role>.md     Layer 3 — what Claude Code loads
```

Rendered by `renderer/compose.py` (Jinja2) via `cli/render.py:render_agents`.
Never hand-edit Layer 3: Claude Code's protected-path guard refuses agent writes
under `.claude/` anyway, so the supported move is to edit Layer 1 or Layer 2 and run
`python scripts/render_own_agents.py`.

The Layer-3 output is currently mangled — `trim_blocks=True` in `compose.py` eats the
newline that separates list items, so invariants, sharp edges and structural
decisions each render as one run-on line, and `loop.index` numbers the *unfiltered*
list (issue #37). Pass 3 stays green because it diffs the render against a fresh
render of the same templates: self-consistency, not correctness.

---

## 2. Module map

Eight importable packages. The import direction is one-way apart from a single
recorded cycle; `AGENTS.md` > Module Boundaries carries the same map as a table, and
`ALLOWED_IMPORTS` in `scripts/validate_harness.py` is the copy that is enforced.

```
cli/            Entrypoints. init, reconcile, render, review, sync.
                → github, interview, renderer, stonehaven
stonehaven/     Orchestration. admin_api, listener, registry, worker.
                → github, notifications, reviewers, verdict_store
github/         GitHub API I/O. issues, pr, webhook.        → reviewers
reviewers/      Dispatch, model resolution, verdict parsing. → github
renderer/       compose, lockfile, validators.              → (nothing internal)
interview/      analyzer.                                   → (nothing internal)
notifications/  publisher.                                  → (nothing internal)
verdict_store/  client, models.                             → (nothing internal)
templates/      3 role templates + 4 shared partials, zero .py. Not importable.
```

`github` ↔ `reviewers` is a cycle: `github/issues.py` imports `reviewers.verdicts.Finding`
and `reviewers/dispatch.py` imports `github.pr.PRDiff`. Both are type-only, which is
the usual sign the two names belong in a module neither package owns. It is recorded
in `KNOWN_CYCLES` so a *new* cycle fails the linter.

### What each module is for

| Module | Responsibility |
|---|---|
| `cli/init.py` | Greenfield and brownfield project init: analyse, render, register, PR |
| `cli/render.py` | Render `.factory/project_context.md` + `templates/` → agent definitions |
| `cli/sync.py` | Propagate template version upgrades across the fleet |
| `cli/reconcile.py` | Recover reviews for webhook deliveries that were missed |
| `cli/review.py` | Manual, on-demand triumvirate invocation for one PR |
| `interview/analyzer.py` | Analyse an existing repo into a `project_context.md` draft |
| `renderer/compose.py` | Jinja2 composition of one agent definition |
| `renderer/validators.py` | Schema validation of `project_context.md` (9 section validators) |
| `renderer/lockfile.py` | Read/write `.factory/templates_lock.yml` |
| `github/pr.py` | Fetch PR diffs and file contents |
| `github/issues.py` | Turn findings into GitHub issues |
| `github/webhook.py` | Register and manage repo webhooks |
| `reviewers/dispatch.py` | Invoke the three reviewers in parallel, track cost |
| `reviewers/models.py` | Resolve a model *class* to a concrete model config |
| `reviewers/verdicts.py` | Parse the reviewer verdict block, literally |
| `stonehaven/listener.py` | FastAPI webhook endpoint: HMAC verify, dedupe, enqueue |
| `stonehaven/worker.py` | Review pipeline: diff → dispatch → parse → store → notify |
| `stonehaven/registry.py` | Project registration CRUD over `VerdictStoreClient` |
| `stonehaven/admin_api.py` | Fleet/project/finding read endpoints |
| `verdict_store/models.py` | SQLite DDL: `projects`, `verdicts`, `findings` |
| `verdict_store/client.py` | The database access layer |
| `notifications/publisher.py` | ntfy push on review completion |

---

## 3. Data flow

### 3a. The build loop (what the harness does to a project)

```
docs/PRD.md
   │  prd-changed.yml (push to main) → prd-to-issues.yml
   ▼
sequenced GitHub issues, each a binding spec
   │  `agent-task` label → agent-dispatch.yml
   │     refuse-held job      → scripts/refuse-held-issue.sh   (holding labels)
   │     predecessor gate     → scripts/resolve-predecessor.sh (sequential order)
   ▼
Claude Code agent — reads AGENTS.md, implements, opens a PR
   │
   ▼
ci.yml  (§4)
   │
   ▼
auto-merge → close-issue-on-merge.yml → next issue dispatched
   │
   ▼
compound-learning.yml → docs/learnings/pr-N.md  → feeds the next PRD cycle
```

Weekly, `gc-agent.yml` runs an entropy pass over the result and opens a `gc` PR.

### 3b. The review loop (the Triumvirate extension)

```
GitHub PR webhook
   ▼
stonehaven/listener.py      HMAC verify → dedupe on X-GitHub-Delivery → 202
   ▼
stonehaven/worker.py        ReviewWorker.process_review
   ├── github/pr.py            fetch the diff
   ├── reviewers/models.py     resolve each role's model class
   ├── reviewers/dispatch.py   invoke engineer / architect / sre in parallel, blind
   ├── reviewers/verdicts.py   parse each response into ParsedVerdict + Findings
   ├── verdict_store/client.py write_verdict, then write_findings
   ├── github/issues.py        file findings as issues
   └── notifications/publisher.py  ntfy
```

Recovery path: `cli/reconcile.py` walks recent PRs for registered repos and
re-runs anything with no verdict on record.

**Maturity, stated plainly.** This loop is wired end-to-end and tested, but is not
in production: `reviewers/dispatch.py` returns a canned response rather than calling
a model (`reviewers/dispatch.py:300`), nothing serves the FastAPI apps (no `[project.scripts]`,
no `uvicorn.run` call site), and `stonehaven/listener.py` dedupes in an in-process
`set`, so a restart forgets every delivery. Issue #29 replaces this path with three
CI jobs. Read `docs/harness-hardening-plan.md` phases 6–9 before building on it.

### 3c. Persistence

Three SQLite tables, defined in `verdict_store/models.py`, WAL mode:

```
projects (stonehaven_id UNIQUE, repo UNIQUE, project_name, harness_version, active)
   └── verdicts (delivery_id, pr_number, pr_sha, reviewer, severity,
   │             good, bad, ugly, closing_question, raw_response, template_version)
   │             UNIQUE(delivery_id, reviewer)   ← the durable dedupe key
   └────── findings (bucket, text, severity, invariant_id)
```

`verdict_store/client.py` is **intended** to be the only module that opens a
connection. It is not: `stonehaven/admin_api.py` has six direct-SQL sites and
`cli/reconcile.py` two, one of which says so in its own docstring. The one module
that could have bypassed the boundary and does not is `stonehaven/registry.py`,
whose `list_projects()` raises `NotImplementedError` rather than reaching past the
client.

---

## 4. Enforcement points

Where a claim in this repo is actually checked, and by what.

| Invariant | Enforced by | Blocking? |
|---|---|---|
| Module import boundaries | `scripts/validate_harness.py` Pass 1 | Yes — required check `Harness Structure` |
| No new import cycles | Pass 1b, against `KNOWN_CYCLES` | Yes |
| Implemented modules are not coverage-omitted | Pass 2 | Yes |
| `.claude/agents/` matches a fresh render | Pass 3 | Yes |
| The linter is pointed at real files | `files_checked == 0` → exit 1 | Yes |
| Hook guards behave (fail-open vs fail-closed) | `.claude/hooks/test-hooks.sh`, 31 assertions | Yes — required check `Hook Guards` |
| Sequential dispatch order | `scripts/resolve-predecessor.sh` | Yes, at dispatch |
| Holding labels (`human-review`, `harness-gap`) | `scripts/refuse-held-issue.sh`, in a job every trigger needs | Yes, at dispatch |
| PR conforms to its dispatched issue | `scripts/check-spec-conformance.sh` → `Spec Conformance` job | Yes for auto-merge; not a branch-protection check |
| Workflow changes get a human | `workflow-guard` job in `ci.yml` | Yes for auto-merge; not a branch-protection check |
| Lint, format, types | `ruff check` / `ruff format --check` / `mypy --strict` | Yes — required check `Lint & Types` |
| 85% total coverage | `pytest --cov-fail-under=85` | Yes — required check `Tests` |
| 85% **per-file** coverage | `scripts/check_coverage_floor.py` | Yes, within `Tests` |
| Stop-hook "done" claim | `.claude/hooks/gate-done.sh` (fails **closed**, `exit 2`) | Yes, locally |
| `AGENTS.md` boundary table matches `ALLOWED_IMPORTS` | — **nothing**, by hand | No |
| `verdict_store` is the only SQLite writer | — **nothing**, and it is broken (#34) | No |
| Reviewer prose sections match the output contract | — **nothing**, and they do not (#33) | No |
| Declared dependencies are actually imported | — **nothing** (#35) | No |

The four branch-protection required checks are exactly: `Harness Structure`,
`Hook Guards`, `Lint & Types`, `Tests`. `Workflow Change Guard` and
`Spec Conformance` gate auto-merge through `needs` + `result == 'success'`, which is
a different mechanism: they stop the robot, not the human.

### Coverage has a blind spot

`[tool.coverage.run] source = ["."]`, but `scripts/` has no `__init__.py`, so
coverage does not walk it and reports only the one script a test happens to import
(`scripts/validate_generated_files.py`). `scripts/validate_harness.py`,
`check_coverage_floor.py`, `backfill_learnings.py` and `render_own_agents.py` are in
no coverage report and therefore invisible to the per-file floor gate — including
the boundary linter and the floor gate itself. They are exercised only by being run
in CI. Tracked as issue #36.

---

## 5. Conventions that are architecture, not style

- **`print()` is not the output layer.** `structlog`, structured JSON, entry + exit
  + exceptions. The template's `reporter.py` does not exist here. One violation is
  on record: `cli/init.py:764`.
- **Severity is declared, never inferred.** `reviewers/verdicts.py` takes it from the
  `VERDICT:` line and nowhere else; a keyword table sniffing the prose is what #28
  removed, and `tests/test_verdicts.py::TestNoKeywordSeverity` fails if one returns.
  The prose sections around it are a different story: the contract asks for `### Good`
  and the parser matches `##` only, so all four come back `None` (issue #33).
- **A parse failure is a failed review, never a `PASS`.** A reviewer must not be able
  to pass a change by going silent or by echoing the template.
- **Gates fail closed.** An unresolvable input blocks. `exit 2` blocks a Claude Code
  hook; `exit 1` is a logger. `validate_harness.py` exits 1, so `gate-done.sh`
  translates it — wiring the script in directly would pass every violation it finds.
- **All API calls are `async`** via `httpx.AsyncClient`. `asyncio_mode = "auto"`;
  never call `asyncio.run()` inside a test.
