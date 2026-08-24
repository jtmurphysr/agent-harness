---
pr: 7
issue: none
module: scripts/validate_harness.py + .github/workflows/ci.yml + .claude/hooks (Stop gate) + AGENTS.md
date: 2026-08-24
tags: [clean-pass, no-linked-issue, compound-loop-closed, self-validating-fix, vacuous-gate-closed, narrowed-fix, hermetic-tests, pattern-retracted, constitution-unenforced, budget-tension, governance-conflict]
outcome: clean
---

# Learning: PR #7 — the linter stopped lying, and the fix merged itself

Three cycles of learning files carried the same two items — *point `ALLOWED_IMPORTS` at
real modules* and *subscribe `ci.yml` to `labeled`*. PR #7 landed both, plus the
`files_checked == 0` guard and the `py_touched` widening, in one commit. **Six checks
green on first push, auto-merged 3m31s after the label, no retrigger commit.**

Two things make this cycle worth more than its diff:

1. **The label fix validated itself on its own PR.** The `labeled` trigger this commit
   added is the trigger that merged this commit.
2. **`gate-done.sh`'s skip path had a comment claiming a backstop that did not exist.**
   pr-6.md found that; PR #7 made the comment true. `files_checked: 0 → 30`.

## What Was Specified

No issue — **fourth consecutive cycle.** The spec was `docs/learnings/pr-6.md` and
`pr-5.md`; the PR body says so in its first line: *"Four items — three from
`docs/learnings/pr-6.md`, one from diagnosing why #5 stalled."*

| Source action | Status in PR #7 |
|---|---|
| pr-5.md — `types: [..., labeled, unlabeled]` in `ci.yml` | **partial** — `labeled` only, see Delta |
| pr-6.md — widen `py_touched()` beyond `\.py$` | done, exactly as specified |
| pr-6.md — fix `ALLOWED_IMPORTS` + AGENTS.md map (3rd cycle) | done |
| pr-6.md — fail on `files_checked == 0` | done |
| pr-5.md — fix/remove the actor allowlist | not attempted, carried |
| pr-4/5/6 — decide the AGENTS.md governance conflict | not attempted, carried |

The learning→PR mechanism is now the established spec channel. Recording the count, not
relitigating it (see pr-4.md, pr-6.md, pr-5.md § *For Future Issue Specs*): **seven
numbered items, seven PRs, zero issues.** `prd-to-issues → agent-task → dispatch` has
still never run end to end.

## What Was Delivered

173 insertions / 38 deletions across 5 files, one commit, one surviving CI run.

**1. `ci.yml` — `types: [opened, synchronize, reopened, labeled]`.** Diagnosed rather
than guessed: the body carries a two-row table with run IDs (`32772561760` `opened` →
Auto-merge **skipped**; `32774943774` `synchronize` → **success**) on the same branch,
same label, byte-identical `ci.yml` blob, and names what was ruled out first (label
timing — #4 had the identical +2s lag and merged; then SHA mismatch; then workflow
drift).

**2. `gate-done.sh` — `\.py$` → `\.(py|toml|cfg|ini)$|^templates/|^tests/`.** Reproduced
before believing it: `py_touched` returned false for a modified
`templates/sre.template.md`, which `tests/test_templates.py` covers.

**3. `validate_harness.py` + `AGENTS.md` — the real module graph.** `ALLOWED_IMPORTS`
held the template's *example* set (`auth`, `clients`, `resolvers`, `pipeline`,
`reporter`, `models`). None exist here, so Pass 1 walked zero files and "Harness
Structure" — a required status check — printed *"No boundary violations found"* on every
run while classifying nothing. Verified post-merge: all eight declared directories exist
and hold exactly **30** `.py` files. The body's framing is the correct one and worth
copying: **"This was never drift — the templating step was never done."**

**4. Pass 1b + the zero-files guard.** A new cycle in the declared graph exits 1; a
`KNOWN_CYCLES` entry that outlives its cycle warns; `files_checked == 0` exits 1 and
names the ghost modules.

**5. Hermetic hook tests.** The two assertions PR #6 added ran against the ambient
working tree. They are now driven in a `mktemp -d` scratch git repo.

### The fix proved itself on the artifact that carried it

`pull_request` workflows run the *head* ref's YAML, so PR #7's own CI used the trigger
list PR #7 added. The timeline:

| Time | Event |
|---|---|
| 20:56:45 | commit authored |
| 20:57:10 | `labeled` — `agent-task` |
| 20:57:12 | **two** CI runs created — `32776802543` and `32776802575` |
| — | `32776802543` **cancelled** by `concurrency: ci-${{ github.ref }}`, `cancel-in-progress: true` |
| — | `32776802575` **success**, all six jobs incl. **Auto-merge** |
| 21:00:41 | merged |

Compare PR #5: 25 minutes, one wasted run, one junk `chore: retrigger CI` commit in
`main`. **This is the strongest verification shape available — the change is exercised by
the mechanism that ships it — and it should be sought deliberately whenever a fix touches
the delivery pipeline itself.**

One consequence to know rather than fix: the `opened` run is now *routinely* cancelled by
the `labeled` run. The checks a reviewer sees on an agent PR come from the label event.
That is fine here, and it also means **adding any label to a PR with CI in flight cancels
that run.**

## Delta Analysis

### The `labeled` fix is narrower than the action it implements, and the omission is unstated

pr-5.md's action reads `types: [opened, synchronize, reopened, labeled, unlabeled]`.
PR #7 shipped `labeled` only. Neither the body nor the commit message mentions
`unlabeled` or why it was dropped.

The gap is not hypothetical. `ci.yml`'s auto-merge condition is
`!contains(...labels.*.name, 'human-review')`. So:

- Human adds `human-review` → `labeled` fires → CI reruns → auto-merge skips. Correct.
- Human **removes** `human-review` to release the hold → `unlabeled` fires → **not in
  `types`** → no run → the PR sits green and unmerged forever.

That is the same failure this PR set out to kill — *permanent, silent, every check green,
nothing anywhere saying why* — reachable through the exact workflow the `human-review`
label exists to support. One word closes it.

### Pass 1b detects two-node cycles only

```python
cycles = {frozenset({a, b}) for a, deps in ALLOWED_IMPORTS.items()
          for b in deps if a in ALLOWED_IMPORTS.get(b, set())}
```

Strictly pairwise. A declared three-node cycle — `cli → stonehaven`,
`stonehaven → github`, `github → cli` — passes **both** passes: Pass 1 permits it because
it is declared, Pass 1b never looks. With `cli` and `stonehaven` both already importing
`github`, that shape is one edge away. A DFS over the declared graph is a few lines and
removes the whole class.

### `KNOWN_CYCLES` staleness is measured against the declaration, not the code

The "delete it" warning fires when `ALLOWED_IMPORTS` no longer declares the cycle — i.e.
after a human has already tightened the map. It can never tell you that
`github/issues.py:20` and `reviewers/dispatch.py:11` stopped importing each other. Useful
for declaration hygiene; it is not a refactor detector, and the comment reads as though
it might be.

### AGENTS.md was amended by an auto-merged agent PR carrying only `agent-task`

`AGENTS.md:307` still reads: *"AGENTS.md changes require `human-review` label —
constitutional amendments are not auto-merged."* PR #7 changed 28 lines of AGENTS.md,
carried `agent-task` alone, and auto-merged in 3m31s.

Nothing checked. There is no CI step that inspects the diff for `AGENTS.md`, and
`MERGE_LABELS: "agent-task,!human-review"` only *excludes* a label that was never
required. **The constitution's single self-protection clause is not a rule; it is a
sentence.** Three cycles of learning files have deferred amendments out of respect for
it while agent PRs amended the file freely. That asymmetry is the finding — it is no
longer a governance *conflict*, it is an unenforced clause.

### Small and stated: the cap number in the body is wrong, and headroom is thinner than reported

The body warns the SessionStart excerpt grew *"6,671 → 8,314 chars against a 10,000
cap."* `preamble.sh:76` sets **`HOOK_OUTPUT_CAP=9000`**. The excerpt is AGENTS.md lines
10–203 = **8,092 chars / 8,298 bytes**, plus ~225 chars of header and footer the hook
adds: **~8,320–8,525 injected against 9,000.** Real headroom is roughly **475–680
characters, not 1,686** — and because bash's `${#s}` counts characters under a UTF-8
locale and bytes under `LANG=C`, the effective headroom differs by ~200 chars between
environments. See § *Reusable Patterns* for why the direction of overflow matters.

## Learnings

### For Future Issue Specs

- **A spec derived from a learning file must quote the action verbatim, and any narrowing
  must be argued in the body.** PR #7 implemented four of pr-5/pr-6's actions and silently
  dropped one word from one of them. Everything else in this PR is over-evidenced; the
  single unstated deviation is the only thing a reviewer had no chance to catch. Rule:
  *if the delivered change is narrower than the action it cites, the body says so and says
  why.*
- **When a spec's acceptance criterion is a count, state where the count comes from.**
  The body's "10,000 cap" is a remembered number, not a read one; the file says 9,000.
  Cumulative with pr-5.md's *"define the unit before verifying the count"* — that was two
  agents deriving different fives from one file; this is one agent citing a limit it did
  not open. Same shape, third instance: **a number in prose is not a number in the repo.**
- Cumulative, fourth cycle: still no issues, and the "Specification Quality" dimensions
  this prompt asks about remain unanswerable. Recording, not relitigating.

### For Future Domain Warnings

- **⚠️ A `pull_request` workflow runs the head ref's YAML — so a trigger change tests
  itself on its own PR.** Exploit it: when fixing anything in the delivery pipeline,
  design the PR so the fix is exercised by the act of merging it, and read the run list
  afterward to prove it. Costs nothing and beats any amount of local reasoning.
- **⚠️ `types: [..., labeled]` without `unlabeled` is half a subscription.** Any workflow
  whose condition reads a label *negatively* (`!contains(...)`) needs `unlabeled` too, or
  removing the blocking label is an event nothing observes. Applies to every `!contains`
  in `ci.yml` today.
- **⚠️ `labeled` in `types` + `cancel-in-progress: true` means labeling cancels in-flight
  CI.** Not a defect — the newer run supersedes — but know it before adding a label to a
  PR whose checks are running.
- **⚠️ A cycle detector that compares pairs is not a cycle detector.** `a↔b` is the
  easiest cycle to see and the least likely one to survive review. Any tool that accepts
  a declared dependency graph must walk it, not scan it.
- **⚠️ An exception list keyed on the declaration cannot observe the code.**
  `KNOWN_CYCLES` warns when the *map* stops declaring a cycle — never when the *imports*
  stop existing. State which artifact an exception is keyed to, because the reader will
  assume it is keyed to the one that matters.
- **⚠️ `clamp` truncates the tail, and the tail of the SessionStart excerpt is
  `## Definition of Done`.** The five injected sections are contiguous and emitted in
  document order; `Critical Agent Warnings` sits *before* `Definition of Done`. Filling in
  `WARNING 1`–`4` — a carried action since pr-4.md — will push the checklist that tells
  agents when they may open a PR out of every session, at ~500 chars of headroom. **Two
  carried actions are now in direct tension, and the losing one fails by disappearing.**

### For AGENTS.md

**Deferred again — fourth cycle — and this time the reason is different, so it is worth
one paragraph rather than four.**

Prior cycles deferred out of deference to `AGENTS.md:307`. PR #7 shows that clause has
never been enforced against anyone: an agent PR amended AGENTS.md, carried only
`agent-task`, and auto-merged. Deference to an inert rule is not a reason; deliberately
breaking a written rule in order to file a note about the rule being broken is worse.
The unblock is not another queued candidate — it is **one human keystroke plus one CI
step**, both listed under Suggested Actions. Candidate amendments from this cycle
(paired-subscription rule for label-gated workflows; state the precondition when
codifying a test pattern; a narrowed fix must argue the narrowing) are recorded above in
copy-pasteable form.

Also unchanged for a fourth cycle: `## Repository Identity` and `## Critical Agent
Warnings` are still template placeholders. `## Module Boundaries` is now real — the first
section of AGENTS.md to say something true about this repository.

### Reusable Patterns

- **A gate's own tests must not read the ambient working tree — and pr-6.md codified the
  version that did.** pr-6.md praised *"fixtures that create real repository state, then
  clean it up"* (`tests/_gate_probe_$$.py`) as a pattern to copy. It was correct only
  while the tree contained no other changes matching the predicate under test, which is
  false for **any commit that edits the predicate**. It broke on the first one — this one.
  The replacement is a `mktemp -d` scratch repo with a stub `validate_harness.py`,
  `CLAUDE_PROJECT_DIR` pointed at it, and a `_gate()` helper: hermetic, and it also stops
  the template case from writing into real `templates/`.

  The meta-learning is the valuable half: **a learning file can codify a pattern whose
  correctness depends on a precondition its author never noticed holding.** Cumulative
  with pr-6.md's own *"a learning file is one agent's analysis, not a test result"* and
  pr-5.md's *"the compound-learning agent is subject to its own findings"* — third
  instance, now with a codified pattern retracted within one cycle. Standing rule when
  writing a Reusable Pattern here: **name the precondition, or do not call it reusable.**
- **Frame an exception list as a baseline, not an amnesty — and make the tool police its
  own staleness.** `KNOWN_CYCLES` ships with the two file:line imports that justify it,
  a written reason for not fixing it now, new entries failing the build, and a warning
  when an entry outlives its cause. Copy this shape for every allowlist, ignore-list, and
  `# type: ignore` cluster: *the exception carries its evidence, and the tool tells you
  when it can go.*
- **Refuse the adjacent refactor, out loud, with the cost.** The AST walk surfaced a real
  `github ↔ reviewers` cycle. Breaking it spans two packages under 471 tests, so it was
  recorded and left — *"deliberately not bundled into a commit whose job is to make this
  linter read real files,"* and **"That call is yours."** pr-6.md criticized PR #6 for
  bundling 98 unrelated deletions into a logic commit. One cycle later the discipline
  transferred without being told. Second confirmed instance of a pattern crossing cycles
  on its own (pr-6.md logged the first, *comment the counterfactual*), which is the real
  evidence that these files are read.
- **Prove it with run IDs, not with a hypothesis.** pr-5.md observed *"the body diagnosed
  the symptom; the timeline located the fix."* PR #7's body opens with the timeline: two
  run IDs, the invariants held constant between them (same branch, same label,
  byte-identical blob), and the alternatives ruled out in order. That is what turned a
  three-cycle-old suspicion into a one-line change nobody had to re-derive.
- **Every path executed, none reviewed.** The body's verification table lists six paths —
  zero-files, new cycle, stale baseline, real violation (2 found across 30 files), hook
  guards 31/31, pytest+ruff. Note the fourth: they introduced a *real* violation to
  confirm the linter still fails on the thing it was always supposed to catch. A linter
  that just started reading files needs a positive control, not only the negative one.

## Suggested Actions

- [ ] **Add `unlabeled` to `ci.yml`'s `types`.** One word. Without it, removing
      `human-review` to release a held PR is an event nothing observes, and the PR stalls
      green and silent — the exact failure PR #7 fixed, on the exact workflow
      `human-review` exists for.
- [ ] **Enforce `AGENTS.md` → `human-review`, or delete the clause.** PR #7 amended
      AGENTS.md with `agent-task` alone and auto-merged; nothing checked. Add a CI step
      that fails when the diff touches `AGENTS.md` and `human-review` is absent — reading
      labels **live via `gh api`**, not from `github.event`, so the guard does not inherit
      the race it is guarding. Or strike `AGENTS.md:307` and say amendments ship like any
      other change. Either is fine; the current state is a rule that only constrains the
      agent that reads it.
- [ ] **Decide compound-learning's authority. Fourth cycle, ~10 candidates, zero
      applied.** PR #7 demonstrates the working channel: a labelled PR. Change
      `compound-learning.yml` Step 4 to open a PR labelled `human-review` instead of
      pushing `AGENTS.md` to `main` — that resolves the fork *and* satisfies the clause,
      without needing the clause changed first.
- [ ] **Make Pass 1b walk the graph.** Pairwise `frozenset({a, b})` misses every cycle of
      length ≥ 3, and `cli`/`stonehaven` → `github` puts one edge from existing.
- [ ] **Fix the SessionStart budget before filling in `Critical Agent Warnings`.**
      ~8,320–8,525 chars injected against `HOOK_OUTPUT_CAP=9000`; `clamp` drops the tail,
      and the tail is `## Definition of Done`. Either emit the wanted sections in priority
      order (Definition of Done first) with a per-section budget, or raise the cap and
      state the new number in `inject-context.sh`'s header comment.
- [ ] **Assert the excerpt fits.** A `test-hooks.sh` case that renders the injection and
      fails when it exceeds `HOOK_OUTPUT_CAP` turns a silent truncation into a red check.
      Same instinct as `files_checked == 0`, applied one hook over.
- [ ] **Carried, second cycle — fix or remove the actor allowlist at `ci.yml:139-140`.**
      Names `claude-code[bot]` and `github-actions[bot]`; PR #7's author is `jtmurphysr`,
      as was #5's. It has never evaluated true. A fallback that has never fired is not a
      fallback.
- [ ] **Carried, second cycle — cover the `require jq` / `require git` failure paths.**
      Now trivial: the scratch-repo harness plus a PATH stub does it in the shape
      `_gate()` already establishes.
- [ ] **Carried, third cycle — automate the learning → issue hop.** Four learning files,
      ~30 unchecked boxes, and the only mechanism for acting on them is a human reading
      them. Still the cheapest way to finally exercise
      `prd-to-issues → agent-task → dispatch`, which has never run.
- [ ] **Carried, fourth cycle — finish AGENTS.md.** `## Repository Identity` and
      `## Critical Agent Warnings` are still the template's placeholders. `## Module
      Boundaries` is now real; it is the proof that filling these in is a bounded task.
      Sequence it after the budget fix above.
