---
type: harness-evolution-summary
date: 2026-02-24
tags: [meta, harness, infrastructure]
---

# Harness Evolution Summary

## Infrastructure Commits (chronological)
- harness: merge method fix + explicit issue close in auto-merge job
- harness: close issue on merge workflow + issue template
- harness: explicit issue close on agent PR merge
- harness: use MERGE not SQUASH so Closes keyword auto-closes issues
- harness: overwrite PR body with Closes keyword when agent creates PR first
- harness: enable auto-merge via graphql on PR creation
- harness: remove apple_auth.py from coverage omit — now implemented
- harness: always label PR with agent-task even if agent created it first
- harness: auto-create PR after agent completes via github-script
- harness: ruff --fix in dispatch, explicit pr create instructions

## Iteration Patterns
Features that required fix commits after initial implementation:

### feat: add harness scaffold — AGENTS.md, workflows, docs, linter
- fix: add id-token write permission for claude-code-action
- fix: allow bash and file tools for claude-code-action

### feat: scaffold complete repo structure and base configuration
- fix: add pythonpath to pytest config for flat package layout
- fix: use setuptools.build_meta backend for CI compatibility
- fix: explicit package discovery for flat layout
- fix: py-modules must be flat array not table
- fix: validated pyproject.toml — explicit packages and py-modules
- fix: ruff import order and list unpacking in validate_harness.py
- fix: validated harness — pyproject.toml, validate_harness.py ruff-clean
- fix: ruff format

### feat: implement Spotify authentication and client modules
- fix: ruff auto-fix all formatting issues
- fix: exclude NotImplementedError stubs from coverage
- fix: omit stub modules from coverage until implemented

### feat: implement ISRC-based track resolution
- fix: ruff auto-fix trailing whitespace

### feat: implement migrate.py main orchestration
- fix: ruff whitespace and B011 assert False


## Key Takeaways
These harness changes represent the delta between "what we thought the agent needed"
and "what the agent actually needed." Each commit is a learning about agent behavior
that should inform the harness template for future projects.
