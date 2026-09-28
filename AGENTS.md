# AGENTS.md — Agent Operating Constitution
# agent-harness

This file is the primary context document for all agents operating in this repository.
Read it in full before taking **any** action. It is the single source of truth for
conventions, module boundaries, and the definition of "done."

---

## Repository Identity

- **Purpose**: An autonomous development harness that turns a PRD into a working codebase —
  issues generated from the PRD, dispatched one at a time to agents, gated by CI, auto-merged,
  and mined for learnings on every merge.
- **Stack**: Python 3.11+, FastAPI, SQLite, Jinja2. Declared in `.factory/project_context.md`.
- **This repo is its own first user.** The reviewers that review this repository are rendered
  from `templates/` + `.factory/project_context.md` exactly the way a generated project's are.
  If the pipeline is wrong, it is wrong here first.
- **Paradigm**: Agent-first — all code, tests, and docs are agent-generated
- **Pipeline**: Issue → Agent → Code → PR → CI → Auto-merge (sequential by dependency)
- **Human role**: Intent specification, credential provisioning, outcome validation

---

## Module Boundaries

Each module may only import from explicitly listed dependencies. This is enforced
by `scripts/validate_harness.py`. This repo's live map. It mirrors `ALLOWED_IMPORTS` in `scripts/validate_harness.py`
exactly; the two are checked against each other and must be edited together.

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
templates/        ← 7 .md files (3 role templates + 4 _shared partials), zero .py —
                    not importable. Covered by
                    tests/test_templates.py and tests/test_shared_partials.py.
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

This table is the row-by-row form of the map above and of `ALLOWED_IMPORTS` in
`scripts/validate_harness.py`. All three are one rule written three times; edit
them together. "Must NEVER import from" is not a second list the linter holds —
it is every internal module absent from the middle column, spelled out so the
prohibition is readable without mentally subtracting one set from another. A
module importing itself is always allowed and is not listed.

| Module | May import from | Must NEVER import from |
|---|---|---|
| `cli/` | `github`, `interview`, `renderer`, `stonehaven` | `notifications`, `reviewers`, `verdict_store` |
| `stonehaven/` | `github`, `notifications`, `reviewers`, `verdict_store` | `cli`, `interview`, `renderer` |
| `github/` | `reviewers` | `cli`, `interview`, `notifications`, `renderer`, `stonehaven`, `verdict_store` |
| `reviewers/` | `github` | `cli`, `interview`, `notifications`, `renderer`, `stonehaven`, `verdict_store` |
| `renderer/` | _(nothing internal)_ | everything |
| `interview/` | _(nothing internal)_ | everything |
| `notifications/` | _(nothing internal)_ | everything |
| `verdict_store/` | _(nothing internal)_ | everything |

`scripts/` is not in the table because it is not a boundary-tracked layer: it has
no `__init__.py`, `collect_python_files` never walks it, and its files reach into
the packages by appending the repo root to `sys.path`. Adding a row would declare
a rule nothing checks.

**Why enforce boundaries**: Keeps modules independently testable and prevents coupling.

---

## Critical Agent Warnings

> These are the spots where agent-generated code most commonly goes wrong on this project.
> Read each one. They encode hard-won knowledge about the specific APIs and patterns used.

Each is a failure this repository has actually shipped. The full case for each,
with the fix that holds it closed, is in `.factory/project_context.md` >
`sharp_edges` — the same file the reviewers are rendered from. That file is the
source; this list is the summary an agent reads before writing code.

### ⚠️ WARNING 1: A gate written as a job-level `if:` is not a gate

`human-review` and `harness-gap` were checked in an `if:` only the `labeled`
event could satisfy. The auto-advance path (`workflow_dispatch` from
`close-issue-on-merge.yml`) and `/agent retry` carry no labels in their payload,
so both went around it and a held issue got an agent. **DO**: put the check in
one job that every dispatch job `needs`, reading its input itself
(`scripts/refuse-held-issue.sh`, `scripts/resolve-predecessor.sh`). **DON'T**:
move a label or predecessor check back into an `if:` expression.

### ⚠️ WARNING 2: Every gate fails CLOSED, including on a lookup miss

`(invariant: gate_fails_closed)`. An unresolvable predecessor, an unreadable
label list, an unparseable verdict, a cancelled reviewer job — each means "did
not verify," and each must block. **DON'T** write `!= 'failure'`: it swallows
`cancelled` and `skipped`, which is how a timed-out review merges itself.
**DO** require `== 'success'` explicitly.

### ⚠️ WARNING 3: Never hand-edit `.claude/agents/*.md`

They are rendered from `templates/*.template.md` + `.factory/project_context.md`
by `cli.render.render_agents`. They had drifted 106 lines when they were
hand-maintained. Claude Code's protected-path guard also refuses agent writes
under `.claude/`, before any allow rule. **DO**: edit the template or the
context, then run `python scripts/render_own_agents.py`. `validate_harness.py`
Pass 3 fails on drift `(invariant: rendered_agents_match_templates)`.

### ⚠️ WARNING 4: Two tokens, and only one of them may touch `.github/workflows/`

GitHub rejects any push touching a workflow file from a token without `workflow`
scope. `GH_PAT` carries `repo` and nothing else and is used in ten read/label
places; `GH_WORKFLOW_PAT` is the only one that can push a workflow change. The
`workflow-guard` job labels any PR touching one `human-review`, and auto-merge
reads that job's output directly. **An agent may propose a change to the rules;
it may not land one alone.**

### ⚠️ WARNING 5: A green workflow run is not evidence the agent did anything

`gc-agent.yml` ran for three weeks reporting success with
`permission_denials_count` at 18 and zero output: `claude-code-action` v1 does
not read `.claude/settings.json`, so without `claude_args --allowedTools` the
agent has only the read-only default tool set. **DO**: before believing a green
run that produced nothing, read `permission_denials_count` in the result JSON.

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
After all checks pass, write the body to a file **outside the worktree** (a
committed body file is out of scope and fails the spec-conformance gate), then:
```bash
gh pr create \
  --title "<title>" \
  --body-file /tmp/pr-body.md \
  --base main \
  --head $(git branch --show-current) \
  --label "agent-task"
```
The body is the input to three machine reviewers and to the spec-conformance
gate, so it is not three lines. Its shape — `Closes #N` first, then `## What`,
`## Files`, `## Verified`, `## Not done / out of scope` — is given in full in
the dispatch prompt; every backticked path in it must be a path the diff touches.
`Closes #N` is **your own issue** and nothing else. See LESSON 5 before writing a
closing keyword against any other issue number.

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
3. **Give it FILES TO CREATE and FILES TO MODIFY headings.** An issue you file is a
   dispatch spec for the next agent, and `check-spec-conformance.sh` returns
   `unresolved no-files-section` — fail closed, no auto-merge — for an issue that is
   only prose. List the paths you believe the fix touches; "Read for context only"
   entries go under FILES TO MODIFY and grant no permission to change them.

Five agents in one generated project filed the same `.venv` finding five times
because step 1 did not exist. Do step 1.

<!-- step 3 added after PR #43 — third occurrence (#28, #29, #36), see docs/learnings/pr-43.md -->

Step 3 is not paperwork. Issues #28, #29 and #36 were each dispatched as prose, and each
blocked the PR that answered it — #43 for six days, on a diff that was correct on its
first push and never changed. The sections were then retrofitted onto the issue with the
diff already visible, which makes the resulting `pass` a mirror rather than a check.
Guessing the file list wrong is cheap; omitting it is not.

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

<!-- Added after PR #40: the rule above was applied to the issue's premises and
     not to the agent's own, which is where the defect actually landed. -->
**The same rule binds your PR body.** Three machine reviewers read it and it is the
permanent record of the change, so a claim you write there is an assertion, not
narration. Two kinds go wrong and both are checkable before you push:

- **Behaviour of code you did not open.** PR #40 bumped three template versions and
  devoted a section to how `cli/sync.py` would propagate them to the fleet. It does
  not: `cli/render.py` writes the lock under `.factory/agents/` and `cli/sync.py`
  reads `.factory/`, so the upgrade path is dead, and the one branch that is live
  rewrites the lockfile without shipping a template — marking projects as upgraded
  while their render stays broken. All three reviewers caught it. Read the path, or
  describe only what your diff does.
- **Counts, and "these tests fail without the fix."** That second claim is your
  LESSON 10 evidence, so state it only for the cases you actually re-ran: PR #40
  said thirteen cases, shipped ten functions / eighteen cases, and at least two of
  them passed against the unfixed templates. `pytest --collect-only -q` gives you
  the number; a claim you did not count is one a reviewer will.

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

<!-- generalised after PR #43 — see docs/learnings/pr-43.md -->

**The rule is wider than defaults: an assertion that holds with the mechanism deleted
proves nothing.** PR #43 shipped
`test_print_table_width_never_shrinks_below_the_header`, which calls the printer and
asserts `"Path" in out`. Python's `:<{width}}` pads and never truncates, so the header
prints whether or not the `max(..., len("Path"))` guard it names exists. The check is
mechanical and takes a minute: **delete the line you are testing, re-run the test, and
watch it fail.** If it passes, you have written a decoration — on this repo, in a PR
whose own premise was that a check which cannot fail is one.

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

### ⚠️ LESSON 16: A verdict you cannot retract is not a verdict

The reviewer jobs post findings as one comment per role, edited on re-run. The
first version rendered an empty body for `PASS`, and the CI step wrote only a
non-empty body — so a `BLOCK` comment survived the push that fixed it. The PR
then carried a comment saying "this PR does not auto-merge" while auto-merging,
and `/agent retry`, which is instructed to address every BLOCKING line in every
`review-*` comment, replayed a resolved finding as a live one. The gate caught
this on its own first run, on the PR that introduced it.

The rule generalises past comments. **Any state a check writes about a commit
must be rewritable by that same check on the next commit, the clean case
included.** "Nothing to say" is a thing to say when something was said before.
Whenever you add a check that writes where a human or an agent will read it — a
comment, a label, a status, a file — write the retraction path in the same
change and test it. Silence on the happy path leaves the last bad news standing.

<!-- paragraph added after PR #31 — see docs/learnings/pr-31.md -->

**Because verdicts retract, you must write the rounds down yourself.** A retracted
comment is gone: compound-learning reads PR comments once, at merge, and by then
every `review-*` comment shows only the last round. If a reviewer BLOCKed you and
you fixed it, add a section to the PR body naming the round, the reviewer, the
finding and the commit that fixed it. PR #31 was blocked ten times across five
rounds and merged showing three WARNs; its learning file exists only because the
agent narrated the rounds in the body. Findings that live only in a comment the
next push erases are findings this repository never learns from.

### ⚠️ LESSON 17: A prompt over 128 KiB kills `claude-code-action` before it starts

<!-- added after PR #31 — cost a full review round, see docs/learnings/pr-31.md -->

The action hands its `prompt` input to a subprocess as one argv string, and Linux
caps a single argument at 128 KiB (`MAX_ARG_STRLEN`). A ~135 KB assembled prompt
dies with `Argument list too long` — before the model runs, with no output to
parse, so a step that depends on the result posts nothing and whatever the last
run wrote stays up. Any workflow that concatenates an issue body, a PR body or a
diff into a prompt will reach this.

Write the payload to a file **inside the workspace** (gitignored) and pass a short
pointer. Two follow-ons, both found the round after:

- Outside the workspace the read-only tool grant cannot reach the file at all.
- One `Read` returns at most 2000 lines. Give the exact line count and tell the
  agent to page, or it silently reviews the first 2000 lines. A sentinel on the
  last line that the agent must quote back catches truncation — it does not prove
  the agent read the middle, since `tail` is in the grant.

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
- [ ] **Three reviewer verdicts on the PR.** `review-engineer`, `review-architect`
      and `review-sre` each run on every `agent-task` PR and each must have
      SUCCEEDED before auto-merge will fire. A `VERDICT: BLOCK` from any one of
      them is a **hard merge-fail** — not a label, not a comment to argue with in
      the PR description. The ways past it are a push that re-reviews clean, or a
      human merging by hand. A reviewer that produces no parseable verdict fails
      the same way: it did not review, and that is never read as a pass.

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
            f"See README.md for configuration instructions."
        )
    return value
```

Required vars: **none, in application code.** No module under `cli/`, `github/`,
`interview/`, `notifications/`, `renderer/`, `reviewers/`, `stonehaven/`,
`verdict_store/` or `scripts/` reads `os.environ` or `os.getenv` — every
credential is passed in as an argument. The secrets this repository uses
(`ANTHROPIC_API_KEY`, `GH_PAT`, `GH_WORKFLOW_PAT`) are consumed by
`.github/workflows/`, not by Python. If you add the first `os.environ` read to
application code, use the `_require_env` pattern above and add the name here in
the same change.

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

Every path in this table exists. Four entries here named `docs/architecture.md`,
`docs/setup.md`, `docs/conventions.md` and `docs/decisions/` until 2026-09-28; none
of the four had ever been written in this repo, so a map whose job is to tell an
agent where to look sent it to four dead paths and omitted `docs/learnings/`, the
one directory it most needs. If you add a row, add the file in the same change.

| Document | Purpose |
|---|---|
| `AGENTS.md` | This file. Operating constitution — boundaries, lessons, definition of done. |
| `README.md` | What the harness is, its pipeline, and the step-by-step bootstrap for a new repo. |
| `.factory/project_context.md` | This repo's own project context: stack, invariant ids, sharp edges. Input to the renderer and to the verdict parser's citation check. |
| `docs/learnings/` | Compound learnings from merged PRs — one file per PR. Read before repeating a pattern. |
| `docs/examples/` | Reference material from a validated project (`playlist-migrate`): its issue specs and learnings. Another repo's code; not this one's. |
| `docs/issues/` | Issue specs written by `prd-to-issues`. Empty in this repo — its issues live on GitHub. |
| `docs/harness-hardening-plan.md` | Standing plan for the harness's own evolution. Aspirational, not current law. |
| `templates/` | Reviewer role templates and `_shared/` partials. The verdict and output contracts live here. |
| `scripts/validate_harness.py` | Structural linter: boundaries, cycles, coverage-omit drift, rendered-agent drift. |
| `scripts/check_coverage_floor.py` | Per-file 85% coverage gate (raw float, two decimals). |
| `.github/workflows/ci.yml` | Every gate, in the order it runs. The auto-merge `if:` is the authoritative list of what must pass. |

Nothing in this repo is an ADR store. `docs/learnings/` carries decisions in
retrospect; the standing decisions are in this file.

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
