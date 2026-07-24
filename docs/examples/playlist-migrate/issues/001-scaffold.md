# Issue #001: Scaffold repo structure and base configuration

**Labels:** `agent-task`
**Depends on:** nothing — this is the foundation

---

## Intent

Create the complete directory structure, base configuration files, and stub modules
for `playlist-migrate`. This is issue #001 — all subsequent issues depend on this
structure existing. Do not implement any logic — stubs only.

---

## Acceptance Criteria

- [ ] Directory structure matches the spec below exactly
- [ ] All stub modules created with correct docstrings and `__all__` where applicable
- [ ] `pyproject.toml` present and valid (already exists in repo root — verify, don't overwrite)
- [ ] `conftest.py` created in `tests/` with placeholder fixture comment
- [ ] `ruff check .` passes with zero errors
- [ ] `mypy --strict .` passes with zero errors (stubs must have correct type signatures)
- [ ] `python scripts/validate_harness.py` exits 0
- [ ] `pytest tests/` passes (no tests yet — just verifies test runner works)

---

## Directory Structure to Create

```
playlist-migrate/
├── migrate.py              ← CLI entrypoint stub (Typer app, no logic)
├── pipeline.py             ← Stub only
├── reporter.py             ← Stub only
├── models.py               ← Pydantic models (implement fully — see below)
├── auth/
│   ├── __init__.py
│   ├── spotify_auth.py     ← Stub
│   └── apple_auth.py       ← Stub
├── clients/
│   ├── __init__.py
│   ├── spotify_client.py   ← Stub
│   └── apple_client.py     ← Stub
├── resolvers/
│   ├── __init__.py
│   ├── isrc_resolver.py    ← Stub
│   └── fuzzy_resolver.py   ← Stub
└── tests/
    ├── conftest.py         ← Placeholder fixtures
    ├── test_models.py      ← Tests for models.py (implement fully)
    └── (stub test files for each module)
```

---

## models.py — Implement Fully

Define these Pydantic v2 models. These are the data contracts the entire system uses.

```python
# SpotifyTrack — represents a track as returned from Spotify API
class SpotifyTrack(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    isrc: str | None = None          # Not always present — see AGENTS.md Warning 2
    duration_ms: int
    playlist_position: int

# SpotifyPlaylist — a playlist with its tracks
class SpotifyPlaylist(BaseModel):
    id: str
    name: str
    track_count: int
    public: bool
    collaborative: bool
    tracks: list[SpotifyTrack] = []

# MatchResult — result of attempting to resolve a Spotify track to Apple Music
class MatchResult(BaseModel):
    spotify_track: SpotifyTrack
    apple_music_id: str | None = None
    match_strategy: Literal["isrc", "fuzzy", "unresolved"]
    confidence: float                # 1.0 for ISRC, 0.0-1.0 for fuzzy, 0.0 for unresolved
    matched: bool

# UnresolvedTrack — written to unresolved.json
class UnresolvedTrack(BaseModel):
    spotify_id: str
    title: str
    artist: str
    isrc: str | None = None
    reason: str                      # "no_isrc_match" | "fuzzy_below_threshold" | "api_error"
    playlist_name: str
    playlist_position: int

# MigrationReport — written to migration_report.json
class MigrationReport(BaseModel):
    run_at: datetime
    playlists_migrated: int
    total_tracks: int
    matched_tracks: int
    unresolved_tracks: int
    match_rate: float                # matched / total, 0.0-1.0
    isrc_matches: int
    fuzzy_matches: int
    duration_seconds: float
```

---

## migrate.py — CLI Stub

Use Typer. Three options: `--dry-run`, `--playlist-id`, `--confidence`.
The stub should define the CLI interface and print "Not implemented" then exit.

```python
import typer
app = typer.Typer()

@app.command()
def main(
    dry_run: bool = typer.Option(False, "--dry-run"),
    playlist_id: str | None = typer.Option(None, "--playlist-id"),
    confidence: float = typer.Option(0.85, "--confidence"),
) -> None:
    """Migrate Spotify playlists to Apple Music."""
    typer.echo("Not implemented yet.")
    raise typer.Exit(0)

if __name__ == "__main__":
    app()
```

---

## Test Requirements

`tests/test_models.py` — implement fully:
- Test that `SpotifyTrack` with no ISRC field is valid (isrc=None)
- Test `MatchResult` with each strategy value
- Test `MigrationReport.match_rate` is computed correctly when set manually
- Test `UnresolvedTrack` serializes to dict with correct field names

All other test files: stubs with a single `pass` test that will be replaced in later issues.

---

## Notes for Agent

- Do not implement any auth, API, or migration logic in this issue
- `models.py` is the exception — implement it fully since everything depends on it
- Type stubs for all other modules: correct signatures, `raise NotImplementedError` bodies
- Verify `python -m pytest tests/` runs without error before opening PR
