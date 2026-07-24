# Issue #011: Wire migrate.py — instantiate clients and run pipeline

## Identity

| Field | Value |
|---|---|
| **Issue Number** | `#011` |
| **Depends On** | `#010 — gc-agent entropy pass` (all modules implemented) |
| **Files to Create** | none |
| **Files to Modify** | `migrate.py` |
| **Out of Scope** | Do NOT modify any other module. Do NOT change CLI options or signatures. |

---

## Context

All modules are fully implemented:
- `auth/spotify_auth.py` — `get_spotify_client()`
- `auth/apple_auth.py` — `get_apple_token()`
- `clients/spotify_client.py` — `SpotifyClient`
- `clients/apple_client.py` — `AppleMusicClient`
- `resolvers/isrc_resolver.py` — `IsrcResolver`
- `resolvers/fuzzy_resolver.py` — `FuzzyResolver`
- `pipeline.py` — `MigrationPipeline`
- `reporter.py` — `Reporter`

`migrate.py` currently stubs `main()` with `typer.echo("Not implemented yet.")`.
This issue replaces that stub with real orchestration.

---

## Interface Contract

### What `main()` must do

```python
import asyncio
import typer
from dotenv import load_dotenv

load_dotenv()

@app.command()
def main(dry_run, playlist_id, confidence) -> None:
    asyncio.run(_run(dry_run, playlist_id, confidence))

async def _run(dry_run, playlist_id, confidence) -> None:
    # 1. Instantiate Spotify client via get_spotify_client()
    # 2. Instantiate Apple Music client via get_apple_token()
    # 3. Fetch all playlists via spotify_client.get_all_playlists()
    # 4. If --playlist-id provided, filter to that playlist only
    # 5. Instantiate IsrcResolver(apple_client)
    # 6. Instantiate FuzzyResolver(apple_client)
    # 7. Instantiate Reporter()
    # 8. Instantiate MigrationPipeline(spotify_client, apple_client, isrc_resolver, fuzzy_resolver, reporter)
    # 9. Call pipeline.run(playlists, dry_run=dry_run, confidence=confidence)
    # 10. Call reporter.print_summary(report)
    # 11. Call reporter.write_report(report) — writes migration_report.json
```

### Error handling
- If any env var is missing, `auth` modules raise `EnvironmentError` — let it propagate, print clean message and exit 1
- If Spotify auth fails, print error and exit 1
- If Apple auth fails, print error and exit 1

---

## Domain Warnings

⚠️ `main()` is synchronous (Typer requirement) — use `asyncio.run(_run(...))` to call async code. Do NOT make `main()` itself async.

⚠️ `python-dotenv` is already imported at module level — do not add a second `load_dotenv()` call.

⚠️ `Reporter` constructor signature — check `reporter.py` before instantiating. Do not assume arguments.

⚠️ `IsrcResolver` and `FuzzyResolver` both take `apple_client` as constructor argument — verify against the actual signatures in the resolver files before wiring.

---

## Acceptance Criteria

### Required Test Cases

| Test Function | Scenario | Expected Outcome |
|---|---|---|
| `test_main_dry_run` | `--dry-run` flag set | Pipeline called with `dry_run=True`, no playlists created |
| `test_main_specific_playlist` | `--playlist-id` provided | Only matching playlist passed to pipeline |
| `test_main_all_playlists` | No `--playlist-id` | All playlists passed to pipeline |
| `test_main_missing_env_var` | Env var missing | Exits with code 1, prints error message |
| `test_main_custom_confidence` | `--confidence 0.7` | Pipeline called with `confidence=0.7` |

### Coverage Requirements
- `migrate.py`: **90%+**

---

## Coverage Omit Delta

```toml
# Remove from omit list:
# "migrate.py",
```

Remove `"migrate.py"` from the omit list in `pyproject.toml`.
