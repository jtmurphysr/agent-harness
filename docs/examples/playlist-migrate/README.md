# Example: playlist-migrate

This directory contains the issue specs and compound learnings from the harness's
first end-to-end validation project — [playlist-migrate](https://github.com/jtmurphysr/playlist-migrate),
a CLI tool that migrates Spotify playlists to Apple Music.

These files serve as **reference implementations** showing:

- How to write tight issue specs that minimize agent drift (`issues/`)
- What compound learning documents look like after merge analysis (`learnings/`)
- The level of specificity needed in interface contracts, domain warnings, and test cases

## Using These as Templates

When writing issue specs for your own project:

1. Read the issue specs in `issues/` to understand the format and level of detail
2. Note how each issue includes: acceptance criteria, module specs with full type signatures,
   domain warnings as DO/DON'T pairs, named test cases, per-file coverage requirements,
   and an explicit out-of-scope section
3. Adapt the format to your project's modules, APIs, and domain

## Results from This Validation

- **27 sequential issues** dispatched, implemented, and auto-merged
- **0 human-authored lines of code** — all agent-generated
- **3,685 lines of tests** across 9 test files
- **92% track match rate** on real production data
- **4 clean passes, 3 iterations** — iteration rate improved as learnings accumulated
