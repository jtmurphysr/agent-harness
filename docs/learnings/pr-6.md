---
pr: 6
issue: none
module: .claude/hooks (Stop gate) + repository hygiene
date: 2026-08-24
tags: [clean-pass, compound-loop-closed, no-linked-issue, fail-closed, hook-testing, gitignore-as-config, vacuous-gate, predicate-scope, governance-conflict]
outcome: clean
---

# Learning: PR #6 — the first change this repository made *because of* a learning file

`docs/learnings/pr-4.md` was written on 2026-08-24 and listed eight suggested actions.
PR #6, merged the same day, executes three of them. This is the first time the compound
mechanism has produced work rather than prose — the loop closed. That is the headline,
and it is worth as much as the bug that got fixed.

## What Was Specified

No issue, again. `gh pr view 6` shows a self-specified change whose body opens:
*"All three items come from `docs/learnings/pr-4.md`."* The learning file was the spec.

The three items it implemented, from pr-4.md's Suggested Actions:

| pr-4 action | Status in PR #6 |
|---|---|
| Fix the Stop gate's pytest-missing path | done |
| Provision the compound-learning job **or** scope the gate to touched files | done (scoped) |
| Untrack `tests/__pycache__/` | done, and widened to all 98 artifacts |

## What Was Delivered

109 insertions / 125 deletions across 101 files, **one commit, one CI run, six checks
green on first push** (run `32774222574`), auto-merged 3m28s after the push. No retry
runs on the branch. Three files carry logic; the other 98 are deletions.

**1. Precondition replaces rc archaeology.** `gate-done.sh:90` now asks
`"$PY" -c 'import pytest'` *before* invoking the suite, rather than trying to
disambiguate `rc=1` afterward. The old `2|3|4` branch was written for the
unprovisioned-environment case and could never see it, because
`python -m <missing module>` exits **1** — the same code as pytest's own
"tests ran and failed."

**2. A three-state gate replaces a two-state one.**

| Condition | Behavior |
|---|---|
| pytest importable | run the suite (unchanged) |
| absent, no `.py` touched | skip, exit 0 |
| absent, `.py` touched | block, exit 2 |

`py_touched()` (`gate-done.sh:57`) unions four git queries — worktree diff, index,
untracked, and `@{upstream}...HEAD` — because an agent may edit and stop *or* commit
and stop, and both are "this turn." It returns **true when it cannot tell**. `git`
joined `jq` as a hard `require()` dependency to make that guarantee real.

**3. 98 of 212 tracked files were build artifacts** — 93 `.pyc` + 5 `agent_harness.egg-info`.
Verified post-merge: `git ls-files` now returns **114**. Exactly 98 removed, matching the
PR's claim and pr-4's count. `.gitignore` had contained no Python patterns at all.

## Delta Analysis

There is no issue to measure against, so the measurement is learning-file-vs-diff. Every
verifiable claim in the PR body holds:

- The 98/212 → 114 arithmetic is exact.
- CI green on first push is confirmed by run list — one `CI` run on the branch, no retries.
- The two new `test-hooks.sh` assertions exist and are run by **Hook Guards**, a required
  check that passed (job `97581466472`).

**The process detail worth copying:** the PR body states each claim from pr-4.md was
*verified independently before being acted on*. That is the correct posture. A learning
file is one agent's analysis, not a test result — it carries no more authority than the
evidence it cites. Treating it as a work queue of *hypotheses to confirm* rather than
*facts to implement* is what kept this PR honest, and it should be the standing rule.

### One residual gap, found in this analysis

`py_touched()` greps `\.py$`. The suite's evidence surface is wider than that:

- `tests/test_templates.py` asserts on `templates/engineer.template.md`,
  `architect.template.md`, `sre.template.md`
- `tests/test_shared_partials.py` asserts on `templates/_shared/*.partial.md`

A turn that edits only `templates/engineer.template.md` touches zero `.py` files, so on
an unprovisioned machine the new skip path waves through the exact change the skipped
suite covers. The window is narrow — it requires pytest to be absent — but `gc-agent`
and any prompt-tuning turn edit precisely those files. `pyproject.toml` has the same
shape. The predicate should track what the suite *verifies*, not what language it is
written in.

### And the skip path's stated safety net is currently empty

The skip branch justifies itself with: *"Structural invariants above still ran, and still
had to pass."* Those invariants are `scripts/validate_harness.py`, whose
`ALLOWED_IMPORTS` (line 39) names `auth`, `clients`, `resolvers`, `pipeline`, `reporter`,
`models`. This repository contains `cli/`, `github/`, `interview/`, `notifications/`,
`renderer/`, `reviewers/`, `stonehaven/`, `verdict_store/` — and no top-level `.py` files
at all. `get_module_layer()` returns `None` for every file in the repo, so `lint_file()`
returns `[]` for every file and the linter passes green having classified nothing.

So on a doc-only turn with no pytest — which is *every* compound-learning run, including
this one — the Stop gate now performs no substantive verification whatsoever. That is
defensible for prose, but the comment in `gate-done.sh:101` claims a backstop that does
not currently exist. Carried forward unchanged from pr-4.md, where it was flagged and not
yet fixed. **Second cycle in a row.**

## Learnings

### For Future Issue Specs

- **`docs/learnings/*.md` is now the de facto issue queue, and it works.** Six numbered
  items in this repo, all six are PRs; `prd-to-issues` → `agent-task` → dispatch has
  still never run end to end. Rather than treat that as a defect to apologize for twice,
  formalize it: give learning files a machine-readable Suggested Actions block and let
  `prd-to-issues` (or a small script) open one issue per unchecked box. The mechanism
  that demonstrably produced a merged fix should be the one that gets automated.
- Until that happens, every "Specification Quality" dimension this prompt asks about —
  interface contract honored, FILES TO CREATE accurate, test names as specified — remains
  unanswerable. Noting the pattern, not relitigating it: see `pr-4.md` § *For Future
  Issue Specs*.
- **A spec that bundles a logic change with a bulk untrack should require separate
  commits.** PR #6 is 101 changed files, 98 of them deletions, in a single commit.
  The coupling argument is real but narrow: only the `.venv/` **line** in `.gitignore` is
  load-bearing for `py_touched()`; the 98 deletions are not coupled to anything. Two
  commits in the same PR would have preserved the coupling and kept
  `git log -p .claude/hooks/` readable. The body compensated by naming the three logic
  files — good practice, but a commit boundary is cheaper than a paragraph.

### For Future Domain Warnings

- **⚠️ Once a hook branches on git's untracked-file list, `.gitignore` is executable
  configuration.** `py_touched()` calls `git ls-files --others --exclude-standard`.
  Leave `.venv/` unignored and the predicate answers "yes" unconditionally, silently
  deleting the skip path. Over-broaden an ignore rule around generated `.py` and you
  silently delete the *block* path — the dangerous direction. Any future `.gitignore`
  edit must be checked against `gate-done.sh:57`, and any new git-reading predicate must
  state which ignore rules it depends on.
- **⚠️ Scope a skip predicate to what the check verifies, not to the file extension the
  check is written in.** Generalizes the `templates/*.md` gap above. Before adding
  "did the turn touch X?" to any gate, enumerate the gate's actual evidence surface —
  here, `grep -rn "templates/" tests/` answers it in one command.
- **⚠️ A green linter is not a passing check until you know how many files it inspected.**
  `validate_harness.py` has passed on every PR in this repo's history while classifying
  zero files. Any tool that filters its input set should print the count and fail — or at
  minimum warn — when that count is zero. Compare `gate-done.sh`'s own `rc=5` branch:
  *"pytest collected no tests — the gate cannot verify anything."* The right instinct
  already exists in this codebase; it just was not applied to the linter beside it.
  Cumulative with pr-4.md's **"Prove the positive, not the absence of a negative"** —
  this is the same failure wearing a different hat, now observed twice.

### For AGENTS.md

Three candidates. **None applied in this commit** — the governance conflict below is
unresolved, and this run follows the precedent pr-4.md set rather than quietly breaking it.

1. **Harness Lesson — every skip path ships with its paired block assertion.** The two
   tests added here are a matched pair: `absent pytest + no Python touched exits 0` and
   `absent pytest + Python touched blocks (2)`. The first alone would be an untested hole
   dressed as a feature. Rule: *a gate that gains a permissive branch gains both tests in
   the same commit.*
2. **Harness Lesson — predicates that gate a safety check default to running the check.**
   `py_touched()` returns true on "no git dir," "no upstream," "git missing." State it as
   a rule so the next predicate is not written the convenient way round.
3. Carry forward, unchanged and unapplied from pr-4.md: pinned-action pins record *what
   call sites they were validated against*; and every workflow step producing an artifact
   has a companion step that fails when the artifact is absent.

**Governance conflict — second run, now with a measurable cost.** AGENTS.md closes with
*"AGENTS.md changes require `human-review` label — constitutional amendments are not
auto-merged."* This prompt's Step 4 says edit it directly; Step 5 says push to main.
`compound-learning.yml:134-149` still contains both instructions verbatim; nothing changed
between PR #4 and PR #6. Two cycles have now produced five amendment candidates and
applied zero. The proposed text above is written to be copy-pasteable so a human can
apply it under review in one pass — but the fork itself will recur on every single run
until someone decides. It is the cheapest unfixed thing in this repository.

Related and also unchanged: AGENTS.md is still an unfilled template — `<PROJECT-NAME>`,
placeholder module table, `WARNING 1`–`4` as commented examples. Agents are told to read
it first. What they read is scaffolding, and the boundary table they read is the same
fiction `validate_harness.py` is enforcing against nothing.

### Reusable Patterns

- **Stub-interpreter injection makes the unprovisioned branch testable on a provisioned
  machine.** The strongest artifact in this diff:

  ```bash
  #!/usr/bin/env bash
  [ "$1" = "-c" ] && [ "$2" = "import pytest" ] && exit 1
  [ "$1" = "-m" ] && [ "$2" = "pytest" ] && { echo "No module named pytest" >&2; exit 1; }
  exec python3 "$@"
  ```

  Pointed at via `HARNESS_PYTHON=$_stub`. The branch that had never executed in four
  months now executes on every CI run. Generalize: **any hook that shells out to an
  external tool routes it through an env-overridable variable**, precisely so its
  absent-tool branch can be driven in a test. `gate-done.sh` already did this for the
  interpreter; the same is not yet true for `jq` or `git`, and both are now hard
  dependencies whose `require()` failure paths are unexercised.
- **Fixtures that create real repository state, then clean it up.** The block-path test
  writes `tests/_gate_probe_$$.py`, runs the gate, captures `rc`, then removes the probe
  *before* asserting — so a failed assertion cannot leave a stray file that changes the
  next test's answer. `$$` in the name keeps concurrent runs from colliding. Copy this
  shape for anything testing a git-state-reading predicate.
- **Comment the counterfactual at the call site** — pr-4.md named this pattern; PR #6
  applied it without being told to. `gate-done.sh:27-30` explains why `git` is required,
  `:54-56` why the predicate fails true, `.gitignore:19-22` why `.venv/` is load-bearing
  rather than cosmetic. Each pre-empts a plausible future "simplification." The pattern
  transferred across cycles on its own, which is the first evidence that these files are
  read as well as written.
- **Reading the file did not catch the bug; running it did.** `gate-done.sh` carried a
  five-line comment about exit-code semantics directly above the line with the exit-code
  bug, through at least three prior PRs. The compound-learning agent found it by being
  *blocked by it*. Where a gate's behavior is load-bearing, invest in exercising its
  branches over documenting them — and treat a comment adjacent to a defect as evidence
  that careful reading is not a sufficient control.

## Suggested Actions

- [ ] **Widen `py_touched()` beyond `\.py$`.** Concretely: `\.(py|toml|cfg|ini)$` plus
      `^templates/` and `^tests/`. `tests/test_templates.py` and
      `tests/test_shared_partials.py` assert on `templates/*.md`, which the current
      predicate classifies as "nothing to verify."
- [ ] **Fix `validate_harness.py`'s `ALLOWED_IMPORTS`** to name the modules that exist —
      `cli`, `github`, `interview`, `notifications`, `renderer`, `reviewers`,
      `stonehaven`, `verdict_store` — and update AGENTS.md's boundary table to match.
      **Second cycle carrying this.** Until it lands, "Harness Structure" is a green
      check over zero files, and it is the *only* verification the new skip path leaves
      standing on a doc-only turn.
- [ ] **Make the linter fail (or loudly warn) on `files_checked == 0`.** Cheap, and it
      would have surfaced the item above four PRs ago. Mirror `gate-done.sh`'s `rc=5`
      wording.
- [ ] **Decide the AGENTS.md governance conflict.** Either grant compound-learning
      explicit authority to amend AGENTS.md on main and amend the constitution's closing
      line, or change Step 4 of `compound-learning.yml` to open a PR labelled
      `human-review`. **Second cycle blocked on this.** Five amendment candidates now
      queued and unapplied.
- [ ] **Apply the queued Harness Lessons** (paired skip/block tests; predicates default
      to running the check; pinned-action call-site records; artifact-presence guards) —
      whichever way the governance decision goes.
- [ ] **Add coverage for `require jq` and `require git` failure paths** in
      `test-hooks.sh`, using the same PATH/stub technique. Both are now hard dependencies
      whose failure branches have never executed.
- [ ] **Automate the learning→issue hop.** Parse the Suggested Actions checkboxes and
      open one `agent-task` issue per unchecked item. This would simultaneously exercise
      the never-run middle of the pipeline and stop learning files from depending on a
      human reading them.
- [ ] **Fill in AGENTS.md** — carried from pr-4.md, still a template.
