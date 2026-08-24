---
pr: 4
issue: none
module: .github/workflows (harness infrastructure)
date: 2026-08-24
tags: [clean-pass, silent-failure, pinned-dependency, no-linked-issue, verification-gate, unexercised-path, governance-conflict]
outcome: clean
---

# Learning: PR #4 — migrating `claude-code-action` beta → v1.0.201, and the end of four months of silent no-ops

This is the **first learning file this repository has ever produced.** `docs/learnings/`
contained nothing but `.gitkeep` before this commit. That fact is the finding, not a
footnote: the mechanism designed to make every merge compounding was itself dead from
2026-04-27 to 2026-08-24, and reported success the entire time.

## What Was Specified

Nothing — there is no linked issue. The repository has four numbered items and **all
four are pull requests**; `gh issue list` returns zero non-PR issues. The advertised
pipeline (`PRD → issues → label dispatch → agent → PR`) has never run end to end. PRs
#1–#4 were authored directly against branches and merged through CI + auto-merge.

The de facto spec was PR #4's own body, which is unusually strong for a self-specified
change: root cause with the upstream source cited, a v0→v1 rename table, an explicit
call-site audit, and a falsifiable success criterion.

## What Was Delivered

53 insertions / 30 deletions across 5 files, one commit, CI green on first push
(run `32771...`, `pull_request`, success; no retry runs on the branch).

All six `claude-code-action` call sites across four workflows repinned
`28f8362` (beta, 2026-04-25) → `3a12287` (v1.0.201), with the v1 input migration:

| v0 input | v1 |
|---|---|
| `mode: agent` / `mode: tag` | removed — inferred by `detectMode()` |
| `direct_prompt` | `prompt` |
| `allowed_tools: "..."` | `claude_args: --allowedTools "..."` |

Plus two non-mechanical decisions:

- `track_progress: true` added to the two **entity-event** steps in `agent-dispatch.yml`
  (`issues`, `issue_comment`). Without it, v1's `detectMode()` resolves an entity event
  carrying a `prompt` to *agent* mode, which does not post tracking comments — the
  rename alone would have silently deleted a user-visible behaviour.
- `track_progress` deliberately **omitted** from the `workflow_dispatch` step, because
  `validateTrackProgressEvent()` throws on non-entity events.

README corrections: troubleshooting rows rewritten (the old one told readers to add
`mode: agent`, an input that no longer exists), and the pipeline diagram corrected from
4-stage to 5-stage. Verified against `ci.yml`: Check Project, Harness Structure, Hook
Guards, Lint & Types, Tests — five gates, plus auto-merge. The edit is accurate.

## Delta Analysis

No delta to measure against a spec, because there was no spec. Measured instead against
the PR's own claims, every checkable one holds:

- Six call sites claimed, six migrated — confirmed against the diff.
- The dead-gate root cause is confirmed by log, not just by reading upstream source.
  Run `32767906313` (PR #2, `docs/hook-guards`) logged
  `No trigger found, skipping remaining steps` at 19:23:57 and the job concluded
  **success**. Green check, five seconds, zero output.
- The predicted proof landed. Run `32769839838` (PR #3, `fix/artifact-fail-closed`)
  concluded **failure** — the new `Verify the learning landed on main` guard going red
  exactly as the PR body said it would. This run is the first to reach the agent.

One gap, and it is the PR's own framing that makes it visible: **merging proves two of
six call sites.** `compound-learning` (this run) and, transitively, nothing else. The
`agent-dispatch` `issues` path, the `issue_comment` retry path, `prd-to-issues`, and
`gc-agent` are all still unexercised under v1 — and the two `track_progress` additions
are precisely the subtlest, most reasoning-dependent edits in the diff. They are
correct on inspection and unproven in execution.

## Learnings

### For Future Issue Specs

- **The absence of issues is the story.** Four PRs, zero issues, and every learning
  dimension this prompt asks about ("did the agent honor the interface contract", "were
  the FILES TO CREATE lists accurate", "were test names implemented as specified")
  is unanswerable. The compound-learning prompt assumes an issue-driven pipeline that
  has not yet run once. Either drive the next change through `prd-to-issues` →
  `agent-task` label, or accept that these learnings measure PR-body-vs-diff.
- When a change is infrastructural and self-specified, PR #4's body is the template
  worth copying: cite the upstream source lines that prove the root cause, enumerate
  **every** call site in a table with before/after, state what merging does and does
  not prove, and give a falsifiable prediction. It made this analysis verifiable
  rather than a summary of assertions.
- A spec for a version migration should require an explicit
  **"which call sites does merging actually exercise?"** section. PR #4 volunteered a
  partial version; it should be mandatory, because "all inputs validate against the
  new `action.yml` schema" is a static check that says nothing about runtime.

### For Future Domain Warnings

- **⚠️ A pinned third-party action's *inputs* are a contract; its *trigger semantics*
  are too.** The beta gated agent mode on
  `isAutomationContext()`, allowlist exactly `["workflow_dispatch", "schedule"]`.
  `compound-learning.yml` fires on `pull_request: closed`. That pairing could never
  fire — not a misconfiguration, a categorical impossibility — and nothing in the
  action's input schema would ever flag it. When pinning or repinning an action,
  check the trigger gate against each call site's `on:` block, not just the inputs.
- **⚠️ Removing an input can change behaviour even when nothing errors.** `mode` was
  not deleted, it was made inferred. Mechanically dropping `mode: tag` from an entity
  event would have produced a valid workflow, a green CI run, and a silently missing
  tracking comment. Treat "input removed, now inferred" as the highest-risk kind of
  migration note: it is the one that passes every validator.
- **⚠️ `python -m <missing module>` exits 1 — colliding with "tests failed."**
  Found live on this run. `.claude/hooks/gate-done.sh:60` runs
  `python3 -m pytest tests/`, and has a well-written branch for an unprovisioned
  environment (`rc` in `2|3|4` → "could not run… `pip install -e \".[dev]\"`").
  But when pytest is *absent entirely*, CPython's `-m` machinery prints
  `No module named pytest` and exits **1**, which falls through to the `*)`
  catch-all: *"Test suite is failing. You are not done."* Exit code 1 is
  overloaded — it is also pytest's own "tests ran and failed." The two are
  indistinguishable by `rc` and trivially distinguishable by output. Guard the
  precondition instead: `"$PY" -c 'import pytest'` before line 60, dying with the
  same provisioning message the `2|3|4` branch already writes.
- **⚠️ Two independent defects can share one symptom.** A missing `ANTHROPIC_API_KEY`
  and the dead trigger gate both manifested as *green check, no output.* Fixing the
  key "moved the no-op three seconds later." When a silent failure is fixed, assume
  the symptom may be overdetermined and demand positive proof of the intended effect,
  not just absence of the previous error.

### For AGENTS.md

Two candidates. **Neither was applied in this commit** — see the governance note below.

1. A new Harness Lesson: **pinned action versions must record what call sites they
   were validated against.** The `# beta as of 2026-04-25` comment on the old pin
   said when, not what-with — and the pin outlived the assumption silently for four
   months. The new comments in `compound-learning.yml:26-32` are the right form and
   worth generalizing into a rule.
2. A Definition of Done addition: for harness/workflow changes, **"any workflow step
   that produces an artifact has a step that fails when the artifact is absent."**
   PR #3 built exactly this for `compound-learning`; the pattern is not yet a rule.

**Governance conflict, flagged rather than resolved.** AGENTS.md's closing line reads:
*"AGENTS.md changes require `human-review` label — constitutional amendments are not
auto-merged."* This prompt's Step 4 instructs the compound-learning agent to edit
AGENTS.md directly and Step 5 to `git push origin main` — bypassing PR, label, and
review entirely. Those two instructions cannot both be honored. This run deferred to
the constitution and left AGENTS.md untouched; the proposed amendments are recorded
above so a human can apply them under review. **This needs an explicit decision, and
until it is made every future compound-learning run will face the same fork.**

Related: AGENTS.md is still an unfilled template (`<PROJECT-NAME>`, placeholder module
table, `WARNING 1`–`4` as examples). Agents are instructed to "read AGENTS.md in full"
as their mandatory first step, and what they currently read is scaffolding.

### Reusable Patterns

- **Prove the positive, not the absence of a negative.** `if-no-files-found: warn`,
  an action that no-ops and exits 0, an empty artifact upload — three ways to be green
  while doing nothing. `Verify the learning landed on main` inverts this: it asserts
  a named file exists **on `origin/main`** and exceeds 200 bytes. Checking the remote
  rather than the working tree is the load-bearing detail — an agent can write a file
  and fail to push, and an unpushed learning is not a learning. Copy this shape for
  any workflow whose output is a committed file.
- **Comment the counterfactual at the call site.** The strongest artifact in this diff
  is not code, it is `compound-learning.yml:26-32` and the two `track_progress`
  comments: each explains what the *previous* configuration did wrong and what would
  break if someone "simplified" the new one. `agent-dispatch.yml`'s note that omitting
  `track_progress` on `workflow_dispatch` is deliberate — because setting it throws —
  pre-empts a plausible future consistency-driven edit. Codify: when a call site's
  configuration is asymmetric with its siblings, the asymmetry gets a comment.
- **A failing gate is a successful gate.** PR #3's guard went red on PR #3's own merge.
  That red was the harness working — first honest signal in four months. Resist the
  reflex to treat a newly-red check as a regression to be suppressed.

## Suggested Actions

- [ ] **Decide the AGENTS.md governance conflict.** Either grant compound-learning
      explicit authority to amend AGENTS.md on main (and amend the constitution's
      closing line to say so), or change Step 4 of the prompt in
      `compound-learning.yml` to open a PR labelled `human-review` instead of pushing.
      Blocking every future run until resolved.
- [ ] **Fix the Stop gate's pytest-missing path, and provision this job.** Two
      separate defects, both hit on this run. (a) `gate-done.sh` misreports absent
      pytest as a failing suite — add an `import pytest` precondition check.
      (b) `compound-learning.yml` has no `setup-python` and no `pip install`
      (unlike `ci.yml`, which has both in its `test` job), so pytest can *never*
      exist here and the Stop gate blocks **every** compound-learning run at the
      same line — on a job whose only output is a Markdown file. Either provision
      the job or scope the gate to the files the turn actually touched.
- [ ] **Untrack `tests/__pycache__/`.** `git ls-files tests/` returns 62 committed
      `.pyc` files, including artifacts from two different pytest versions
      (8.3.5 and 9.1.1). Add to `.gitignore` and `git rm -r --cached`. Textbook
      `gc-agent` work.
- [ ] **Exercise the four unproven v1 call sites.** File one issue with the
      `agent-task` label (proves `agent-dispatch` `issues` + `track_progress`),
      comment `/agent retry` on it (proves `issue_comment`), and manually dispatch
      `prd-to-issues`. `gc-agent` proves itself on its next schedule tick.
- [ ] **Fill in AGENTS.md.** Replace `<PROJECT-NAME>`, the placeholder module table,
      and `WARNING 1`–`4` with real content, or agents' mandatory first step reads a
      template.
- [ ] Add Harness Lesson: pinned action pins record *what call sites were validated*,
      not just the date. Note PR #4 as the prompting change.
- [ ] Add to Definition of Done (harness changes): every workflow step that produces
      an artifact has a companion step that fails when the artifact is absent.
- [ ] Sweep for the same silent-green shape elsewhere: any `if-no-files-found` not set
      to `error`, any `continue-on-error`, any step whose only failure mode is a log
      line.
- [ ] Run the harness end to end once — PRD → issues → dispatch → PR → merge → learning
      — before adding features to it. Four PRs in, the pipeline's middle has never
      executed.
