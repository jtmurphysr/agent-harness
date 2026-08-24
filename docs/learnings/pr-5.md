---
pr: 5
issue: none
module: README.md (documentation) + .github/workflows/ci.yml (auto-merge gate)
date: 2026-08-24
tags: [no-linked-issue, docs-drift, required-iteration, event-payload-snapshot, label-race, orphaned-commit, incomplete-fix, verification-scope, governance-conflict]
outcome: required-iteration
---

# Learning: PR #5 — the docs caught up, and a 2-second label race cost 25 minutes

Two independent findings, neither of which is about the diff:

1. **A one-line fix in PR #4 was two-thirds of a fix, and pr-4.md certified it as
   complete.** The compound-learning agent verified the lines that changed and never
   looked at the lines that didn't.
2. **`gh pr create --label` is not atomic, and `ci.yml` does not listen for `labeled`.**
   The auto-merge gate read an empty labels array from a payload snapshotted 2 seconds
   before the label existed, skipped, and stayed skipped — because no later event
   rebuilt the payload. An empty commit was needed to unstick it.

The diff itself is 14 insertions / 2 deletions in one file and is entirely correct.

## What Was Specified

No issue — **third consecutive cycle**. `gh api .../pulls/5` shows no `Closes #N`; the
branch name `docs/architecture-diagram` carries no issue number. The de facto spec was
the PR body, which is again strong: it states the verification method up front
(*"Verified in both directions"*), gives a falsifiable count (31/31 paths resolve), and
volunteers a housekeeping note about an orphaned commit rather than hiding it.

The pattern is now established rather than notable. See pr-4.md § *For Future Issue
Specs* and pr-6.md § *For Future Issue Specs* — six numbered items, six PRs, zero issues,
and `prd-to-issues → agent-task → dispatch` has still never run end to end. Not
relitigating it a third time; recording that the count went 4 → 6 → 6.

## What Was Delivered

One file, `README.md`. Every claim in the body verifies against disk:

| Claim | Verification |
|---|---|
| `.claude/` omitted entirely | `ls .claude/` → `settings.json`, `agents/{architect,engineer,sre}.md`, `hooks/{gate-done,inject-context,test-hooks}.sh`, `hooks/lib/preamble.sh`. All now in the tree; none were before. |
| tree listed 6 workflows, disk has 7 | `ls .github/workflows/` → 7 files. `prd-changed.yml` was the missing one. |
| tree listed 2 of 4 scripts | `ls scripts/` → `backfill_learnings.py`, `bootstrap-labels.sh`, `validate_generated_files.py`, `validate_harness.py`. |
| `.github/CODEOWNERS` unlisted | present on disk. |
| boundary lint and hook guards run **in parallel** | `ci.yml:36` and `ci.yml:48` — both `needs: check-project`, neither needs the other. The old arrow-chain implied sequence. |
| "the first four are the required status checks on `main`" | `gh api .../branches/main/protection` → `["Harness Structure","Hook Guards","Lint & Types","Tests"]`. Exact. |
| "auto-merge additionally requires the `agent-task` label" | `ci.yml:154` — `MERGE_LABELS: "agent-task,!human-review"`. Exact. |

Descriptions were read from the files rather than inferred, and spot-checking confirms
it: `prd-changed.yml` does dispatch `prd-to-issues` on a `docs/PRD.md` push.

**CI: six checks green on the first push** (run at 20:12:28). The iteration was not a
test failure — see below.

## Delta Analysis

### The stage count was fixed in two of three places, and pr-4.md called it accurate

`git log -L` settles this exactly. Commit `c0b7888` (initial) wrote **three**
occurrences of the CI stage count. PR #4 (`f078e03`) fixed two:

```
README.md:14  - CI Gate (4-stage)                          →  5-stage
README.md:61  - 4-stage CI pipeline with auto-merge         →  5-stage
```

and left the third, at `README.md:29`, reading **"Four-stage pipeline"** — spelled out,
not numeric. PR #5 fixed it, 30 minutes later.

The mechanism is mundane and the lesson is not: **a grep for `4-stage` finds two of
three; the third is only reachable by grepping `[Ff]our`.** A count duplicated across a
document in mixed numeral and word forms is a single fact with three storage locations
and no consistency check.

The sharper half is what pr-4.md did with it. That file wrote:

> *"the pipeline diagram corrected from 4-stage to 5-stage. Verified against `ci.yml`:
> Check Project, Harness Structure, Hook Guards, Lint & Types, Tests — five gates, plus
> auto-merge. **The edit is accurate.**"*

The edit *was* accurate. It was also incomplete, and "accurate" was read as "done." The
compound-learning agent verified the changed lines against ground truth and never asked
whether the same fact appeared on an unchanged line. **Reviewing a diff structurally
cannot find an omission, because omissions are not in the diff.**

### And the two "fives" do not enumerate the same five

Worth stating precisely, because it is invisible to every check in this repo:

- **pr-4.md's five:** Check Project, Harness Structure, Hook Guards, Lint & Types, Tests
  — *"plus auto-merge."* Auto-merge excluded.
- **PR #5's five:** boundary lint, hook guards, ruff+mypy, pytest, auto-merge.
  Check Project excluded.

`ci.yml` defines **six** jobs. Two agents independently "verified the count against
`ci.yml`," both landed on 5, and they excluded different jobs to get there. Neither is
wrong — "stage" is undefined — but the number's stability across two verifications is
what makes the ambiguity undetectable. A number that survives review by coincidence
looks exactly like a number that survives review by correctness.

### The auto-merge iteration: a 2-second race, and no event that could clear it

This is the concrete new defect, and the timestamps are unambiguous:

| Time | Event |
|---|---|
| 20:12:25 | PR #5 created. `pull_request.opened` payload built — `labels: []` |
| 20:12:27 | `agent-task` applied (timeline `labeled` event) |
| 20:12:28 | CI run starts on the **20:12:25 payload** |
| — | Auto-merge job: `conclusion: skipped` |
| 20:37:24 | Empty commit `a19d850` "chore: retrigger CI" |
| 20:37:30 | CI run on `synchronize` — payload rebuilt, labels present |
| 20:41:00 | merged |

Two compounding causes:

1. **`gh pr create --label X` is two API calls, not one.** GitHub creates the PR, then
   applies labels. The `opened` webhook fires between them. The gap here was 2 seconds;
   it is never 0.
2. **`ci.yml:3-5` declares no `types:`,** so it defaults to
   `[opened, synchronize, reopened]`. `labeled` is not among them. Nothing after 20:12:27
   ever rebuilt the payload, so the skip was permanent, not transient.

`ci.yml:126-133` also offers an actor escape hatch —
`github.actor == 'claude-code[bot]' || github.actor == 'github-actions[bot]'` — which did
not fire because PR #5's author is `jtmurphysr` (the PAT identity). The actor allowlist
names bot identities the harness does not actually push as. The label check was the only
live path, and it was reading a stale array.

**Cost: 25 minutes and one junk commit in `main`'s history.** It will recur on every
agent-authored PR.

### The orphaned commit

The PR body discloses that commit `48b7be0e` was originally pushed to
`chore/claude-code-action-v1`, but PR #4 had auto-merged (20:11:04) and the branch was
gone before the push landed — PR #5 was created at 20:12:25, **81 seconds later**. The
commit was cherry-picked onto a fresh branch unchanged.

Disclosing this rather than quietly re-branching is the correct instinct and should be
noted as such. The underlying hazard is structural: **auto-merge deletes the branch an
agent may still be working on.** With PRs merging ~20 minutes apart in this repo, any
agent that pushes a follow-up to a branch it already opened a PR from is racing the
merge. This is the second timing race in one PR, from the same root: the harness assumes
agent actions are instantaneous relative to workflow events. They are not.

## Learnings

### For Future Issue Specs

- **A spec that corrects a duplicated fact must state the expected occurrence count.**
  "Fix the stage count in the README" is unbounded; "the stage count appears 3× in
  `README.md` (lines 14, 29, 61) — all three must read 5" is checkable, and would have
  closed this in PR #4. Any spec touching a magic number, version string, or count
  should carry `grep -c` output as its acceptance criterion.
- **Docs-only PRs need a bidirectional verification clause.** PR #5 volunteered one
  (*"every path the tree claims resolves; every file on disk appears in the tree"*) and
  it is the reason this diff is trustworthy. Make it mandatory for any change to a
  structural diagram: one direction catches stale entries, the other catches omissions,
  and only the second would have found `.claude/` — the directory `CODEOWNERS` singles
  out as executable configuration and the tree did not mention at all.
- Cumulative with pr-4.md and pr-6.md: still no issues. Recording, not relitigating.

### For Future Domain Warnings

- **⚠️ `github.event.pull_request.labels` is a snapshot, not a query.** Any workflow
  gating on a label must either subscribe to `types: [..., labeled, unlabeled]` or read
  labels live via the API at job time. A `pull_request` workflow with default `types:`
  and a `contains(github.event.pull_request.labels.*.name, ...)` condition is a race by
  construction — and it fails *closed and silently*, presenting as a skipped job with no
  error anywhere. This is a new instance of pr-4.md's **"green check, no output"** shape:
  the third distinct mechanism in this repo for a gate to do nothing while looking fine.
- **⚠️ `gh pr create --label` does not apply the label atomically.** Assume a window
  between PR creation and label application in which the label does not exist. Never
  build a first-fire gate on it.
- **⚠️ Auto-merge deletes the head branch — do not push to a branch whose PR may have
  merged.** PR #5's first commit was orphaned 81 seconds after PR #4 merged. Before any
  follow-up push, confirm the PR is still open. If it is not, branch fresh from `main`
  and cherry-pick — and say so in the body, as PR #5 did.
- **⚠️ When correcting a fact in prose, grep for every written form of it.** Numerals
  and words are different strings: `4-stage` and `Four-stage` are the same fact and no
  single grep finds both. Applies equally to versions (`v1` / `1.0.201`), counts spelled
  out, and any number that also appears in a diagram.
- **⚠️ Define the unit before verifying the count.** Two agents verified "five stages"
  against a six-job `ci.yml` and excluded different jobs. If a count is load-bearing in
  docs, the doc must enumerate the members, not just state the total — an enumeration is
  falsifiable and a total is not.

### For AGENTS.md

Candidates, **none applied in this commit** — see the governance note below.

1. **Harness Lesson — workflows that gate on labels subscribe to `labeled`.** Concretely,
   `ci.yml:3-5` should read
   `types: [opened, synchronize, reopened, labeled, unlabeled]`, or the auto-merge job
   should fetch labels with `gh api` instead of reading the event payload. This is the
   only candidate across three cycles that has a *measured* cost attached: 25 minutes and
   a junk commit, recurring per PR.
2. **Harness Lesson — before pushing to an existing branch, verify its PR is still
   open.** Auto-merge can delete it out from under an in-flight push.
3. **Definition of Done addition — a change that corrects a duplicated fact records the
   occurrence count it verified.** Would have prevented this PR from being necessary.

**Governance conflict — third cycle, and the queue is now eight candidates.**

`AGENTS.md`'s closing line (line 287) still reads: *"AGENTS.md changes require
`human-review` label — constitutional amendments are not auto-merged."* This prompt's
Step 4 says edit it directly; Step 5 says `git push origin main`. Because
compound-learning pushes to `main` with no PR, there is no artifact to label — honoring
Step 4 does not merely bend the constitution, it makes the required label
*unrepresentable*.

This run defers to the constitution, consistent with pr-4.md and pr-6.md. Three cycles
have now produced eight amendment candidates and applied zero. pr-6.md called this *"the
cheapest unfixed thing in this repository."* It is now also the most expensive to keep
deferring, because candidate 1 above is a defect that bills 25 minutes every PR.

Also unchanged for a third cycle: AGENTS.md is a template. `<PROJECT-NAME>`, a
placeholder module table, `WARNING 1`–`4` as commented-out examples. The
`inject-context.sh` hook faithfully injects 6,671 characters of scaffolding into every
session — including this one.

### Reusable Patterns

- **Verify in both directions.** The pattern that made this PR correct, and the one whose
  absence made PR #4 incomplete. *Forward:* does everything the doc claims exist, exist?
  *Reverse:* does everything that exists appear in the doc? Forward-only verification is
  what "the edit is accurate" meant in pr-4.md, and it is structurally blind to omission.
  Generalizes past docs: a test suite that only asserts on what the code does cannot
  find what the code fails to do.
- **Disclose the messy provenance.** The orphaned-commit note cost the PR body three
  lines and turned an unexplainable force-push into a documented cherry-pick. A reviewer
  seeing an identical commit on a dead branch would otherwise have had to reconstruct it.
  Copy the shape: when the git history will look odd, explain it in the body rather than
  letting the next reader do archaeology.
- **The compound-learning agent is subject to its own findings.** pr-4.md certified an
  incomplete fix as accurate, and that certification is why nobody re-checked for 30
  minutes. Adding a standing question to this analysis — *"what did the change leave
  unchanged that shares its fact?"* — is cheap and would have caught it. A learning file
  asserting completeness carries the same authority problem pr-6.md identified for
  learning files asserting facts: it is one agent's analysis, not a test result.
- **Timestamps beat narratives.** Every claim in the auto-merge section above came from
  `gh api .../issues/5/timeline` and the workflow-run list, not from the PR body's
  hypothesis. The body guessed *"the opened-event payload appears not to have carried the
  label"* — correct, but hedged. The timeline proves it to the second and also supplies
  the part the body missed: that `labeled` is not in `ci.yml`'s trigger types, which is
  why the skip was permanent rather than transient. **The body diagnosed the symptom; the
  timeline located the fix.**

## Suggested Actions

- [ ] **Add `types: [opened, synchronize, reopened, labeled, unlabeled]` to `ci.yml:4`,**
      or have the auto-merge job read labels via `gh api` at run time instead of from
      `github.event`. Measured cost of not doing this: one wasted CI run, one junk commit,
      and ~25 minutes per agent-authored PR. **Highest-value item in this file.**
- [ ] **Fix or remove the actor allowlist at `ci.yml:130-131`.** It names
      `claude-code[bot]` and `github-actions[bot]`; PRs are actually authored by
      `jtmurphysr`. It has never matched, so the label path is load-bearing and unbacked.
      Instance of pr-6.md's *"a green check over zero files"* — a condition that has
      never evaluated true is not a fallback.
- [ ] **Add a CI check for cross-document fact drift.** Minimum viable: assert the
      README's stage count equals the number of `jobs:` in `ci.yml`, and that no
      `[Ff]our.stage` string survives. Cheap, and it closes the exact hole PR #4 left.
- [ ] **Enumerate the stages in `README.md:29` rather than counting them,** and state
      whether `Check Project Exists` and `Auto-merge` are in or out. Two agents have now
      produced different fives from the same file.
- [ ] **Decide the AGENTS.md governance conflict. Third cycle, eight candidates queued.**
      Either grant compound-learning explicit authority to amend `AGENTS.md` on `main`
      and amend line 287 to say so, or change `compound-learning.yml` Step 4 to open a
      PR labelled `human-review`. Note that the current instructions make the required
      label unrepresentable, so "just apply the label" is not available without a
      workflow change either way.
- [ ] **Apply the queued Harness Lessons** — from this cycle: label-gated workflows
      subscribe to `labeled`; verify a PR is open before pushing to its branch; duplicated-
      fact corrections record their occurrence count. Carried from pr-4.md/pr-6.md:
      paired skip/block tests; predicates default to running the check; pinned-action
      call-site records; artifact-presence guards.
- [ ] **Carried, third cycle — fix `validate_harness.py`'s `ALLOWED_IMPORTS`** to name
      the modules that exist, and make the linter fail on `files_checked == 0`. Still a
      green check over zero files, and still the only verification standing on a
      doc-only turn like this one.
- [ ] **Carried, third cycle — fill in AGENTS.md.** Still a template.
- [ ] **Carried from pr-6.md — automate the learning → issue hop.** Three learning files
      now carry ~25 unchecked boxes and the only mechanism for acting on them is a human
      reading them. This is also the cheapest way to finally exercise
      `prd-to-issues → agent-task → dispatch`, which has still never run.
