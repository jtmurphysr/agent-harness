---
project:
  name: "agent-harness"
  description: "An autonomous development harness that turns a PRD into a working codebase: issues are generated from the PRD, dispatched one at a time to Claude Code agents, gated by CI, auto-merged, and mined for learnings on every merge. This repository is both the harness and its first user — the reviewers rendered from this file review the harness itself."

stack:
  language: "python"
  framework: "fastapi"
  database: "sqlite"
  primary_files:
    high_blast_radius:
      - ".github/workflows/agent-dispatch.yml"
      - ".github/workflows/ci.yml"
      - "scripts/resolve-predecessor.sh"
      - "scripts/validate_harness.py"
      - "AGENTS.md"
    generated:
      - ".claude/agents/architect.md"
      - ".claude/agents/engineer.md"
      - ".claude/agents/sre.md"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants:
  - id: "layering"
    rule: "Import direction is models <- {interview, notifications, renderer, verdict_store} <- {github, reviewers} <- stonehaven <- cli, as encoded in ALLOWED_IMPORTS in scripts/validate_harness.py. No module imports upward."
    severity: "correctness"
  - id: "gate_fails_closed"
    rule: "Every gate that can block a merge (the sequential dispatch gate, the workflow-change guard, the hook guards) must fail CLOSED on any error or unresolvable input. A gate that opens on a lookup miss is a report, not a gate."
    severity: "irreversibility"
  - id: "no_unchecked_write_to_main"
    rule: "No workflow pushes to main without CI having gated the change. compound-learning.yml is the current exception and is tracked; do not add another."
    severity: "data_consistency"
  - id: "closing_keyword_is_executable"
    rule: "A PR body may contain a closing keyword only for the issue it was dispatched on. Under auto-merge no human reads the body; GitHub acts on the keyword unreviewed."
    severity: "irreversibility"
  - id: "rendered_agents_match_templates"
    rule: ".claude/agents/*.md are rendered from templates/*.template.md plus this file, by cli.render.render_agents. They are never edited by hand. validate_harness.py Pass 3 fails if they drift."
    severity: "data_consistency"

sharp_edges:
  - location: ".github/workflows/agent-dispatch.yml"
    issue: "The predecessor gate once extracted the LAST #N on the DEPENDS ON line and treated any unresolvable predecessor as satisfied. Every GC-filed or hand-written dependency was ungated."
    fix: "scripts/resolve-predecessor.sh resolves the FIRST #N, falls back to canonical title, and returns `unresolved` (which blocks) on neither. 17 tests in scripts/test-resolve-predecessor.sh. Do not reintroduce inline extraction."
  - location: ".github/workflows/agent-dispatch.yml (refuse-held job)"
    issue: "human-review and harness-gap were checked in a job-level `if:` that only the `labeled` event could satisfy. The auto-advance path (workflow_dispatch from close-issue-on-merge) and /agent retry carry no labels in their payload, so they went ungated; a held issue was dispatched seconds after its predecessor merged."
    fix: "scripts/refuse-held-issue.sh, run by the refuse-held job that both dispatch jobs `needs`. Reads labels via REST, fails on a read error, never edits labels or comments. 11 tests in scripts/test-refuse-held-issue.sh. Do not move a label check back into an `if:`."
  - location: ".github/workflows/compound-learning.yml"
    issue: "Pushes docs/learnings/pr-N.md straight to main. ruff formats Python blocks inside Markdown, so one unformatted fenced example turned main red for three weeks with nothing to surface it."
    fix: "ruff is installed before the agent step, Bash(ruff:*) is granted, the prompt formats-then-checks, and the verify step fails if the pushed file is not ruff-clean. The direct push itself is still open (elp-mosaic#57 option 4)."
  - location: ".github/workflows/gc-agent.yml"
    issue: "Ran for three weeks reporting success with permission_denials_count 18 and zero output. claude-code-action v1 does not read .claude/settings.json; without claude_args --allowedTools the agent has only the read-only default set."
    fix: "claude_args is passed. Any successful run that produced nothing: read permission_denials_count in the result JSON before believing the green."
  - location: ".claude/agents/"
    issue: "Claude Code's protected-path guard refuses agent Write/Edit under .claude/ and runs BEFORE allow rules, so no settings entry can grant it. The three definitions here were hand-written, never rendered, and had drifted 106 lines from their templates."
    fix: "They are now rendered from templates/ + this file by scripts/render_own_agents.py, which agents may run; Pass 3 checks the output. Edit the template or this context, never the rendered file."
  - location: "pyproject.toml [tool.ruff]"
    issue: "`exclude` replaces ruff's defaults; `extend-exclude` keeps them. tests/ was excluded entirely, so every test-only PR passed the pre-PR sequence without its one changed file being read."
    fix: "extend-exclude = []. tests/ and scripts/ are linted. mypy on tests/ is a ratchet with an explicit waived-code list (#17)."
  - location: "GH_PAT vs GH_WORKFLOW_PAT"
    issue: "GitHub rejects any push touching .github/workflows/ from a token without workflow scope. With repo-only, the factory could fix everything except the factory."
    fix: "Agents push with GH_WORKFLOW_PAT. ci.yml's workflow-guard job applies human-review to any PR touching a workflow file and auto-merge checks its output directly. An agent may propose a change to the rules; it may not land one alone."

structural_decisions:
  - decision: "The harness renders its own reviewers from its own templates."
    rationale: "Until 2026-09-18 the harness shipped a rendering pipeline it never used on itself; its own agent definitions were stale hand copies. A generator that does not consume its own output cannot notice when that output is wrong."
  - decision: "Harness lessons live in AGENTS.md as rules; case histories live in docs/learnings/."
    rationale: "elp-mosaic's AGENTS.md grew to 4.4x this template by appending every PR's history to every rule. A constitution too long to hold stops being read, which is the failure mode that produces the lessons in the first place."
  - decision: "Two tokens, not one."
    rationale: "GH_PAT is used in ten places that only read and label. Widening it to workflow scope for one push path multiplies the blast radius of a leak by every one of them."

becoming: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: true
    model_class: "structural_review"
  sre:
    enabled: true
    model_class: "adversarial_review"
  deploy:
    enabled: false
    surfaces: []
---

# agent-harness — project context

This file is Layer 2 of the three-layer agent composition: `templates/*.template.md`
(Layer 1, shipped to every generated project) plus this context (Layer 2, specific
to one project) renders `.claude/agents/*.md` (Layer 3, what Claude Code loads).

The harness is its own first user. The reviewers that review this repository are
rendered from this file exactly the way a generated project's reviewers are. If
the pipeline is wrong, it is wrong here first.
