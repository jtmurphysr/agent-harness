---
pr: 6
issue: 4
module: apple_client
date: 2026-02-24
tags: [required-iteration, lint-fix, coverage-drift, format-fix]
outcome: required-iteration
---

# Learning: PR #6 — feat: implement Spotify authentication and client modules

## What Was Specified
Issue #4: apple_client.py — catalog search + playlist CRUD

Key acceptance criteria from spec:

- [ ] `search_by_isrc(isrc)` — returns `str | None` (Apple Music track ID)
- [ ] `search_by_metadata(artist, title)` — returns `list[tuple[str, float]]` (id, confidence)
- [ ] `create_playlist(name)` — checks for existing playlist first (idempotency)
- [ ] `add_tracks_to_playlist(playlist_id, track_ids)` — batches correctly
- [ ] `find_playlist_by_name(name)` — returns existing playlist ID or None
- [ ] All requests go through `_request_with_backoff` — see AGENTS.md Warning 3
- [ ] 429 response

## What Was Delivered
Feature commits:
  - feat: implement Spotify authentication and client modules

Fix commits (iterations):
  - fix: omit stub modules from coverage until implemented
  - fix: exclude NotImplementedError stubs from coverage
  - fix: ruff auto-fix all formatting issues

Files changed:
  - agent-dispatch.yml
  - auth/spotify_auth.py
  - clients/spotify_client.py
  - pyproject.toml
  - tests/conftest.py
  - tests/test_auth.py
  - tests/test_clients.py

## Delta Analysis
Required 3 fix commit(s) after initial implementation:
  - fix: omit stub modules from coverage until implemented
  - fix: exclude NotImplementedError stubs from coverage
  - fix: ruff auto-fix all formatting issues

## Learnings

### For Future Issue Specs
- Add explicit pre-PR checklist: `ruff check --fix . && ruff format . && ruff check .` as a named step in the issue spec, not just in AGENTS.md
- Coverage omit drift: each issue spec should include explicit coverage omit delta section

### For Future Domain Warnings
- Agent required iteration on this module. Review fix commits for patterns that should become warnings.

### For AGENTS.md
- No AGENTS.md updates suggested.

### Reusable Patterns
- Centralized retry with exponential backoff — single ownership of retry logic

## Suggested Actions
- [ ] Review fix patterns from PR #6 for preventable failures
- [ ] Add coverage omit validation to structural linter
