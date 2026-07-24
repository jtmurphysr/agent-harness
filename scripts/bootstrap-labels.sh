#!/usr/bin/env bash
# bootstrap-labels.sh — Create required harness labels
# Run once after creating a repo from the agent-harness template.
# Usage: ./scripts/bootstrap-labels.sh [owner/repo]

set -euo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

echo "Bootstrapping labels for $REPO..."

gh label create agent-task \
  --repo "$REPO" \
  --color 0E8A16 \
  --description "Autonomous agent task" \
  --force 2>/dev/null && echo "  ✅ agent-task" || echo "  ⏭️  agent-task (exists)"

gh label create gc \
  --repo "$REPO" \
  --color FBCA04 \
  --description "Entropy/cleanup pass" \
  --force 2>/dev/null && echo "  ✅ gc" || echo "  ⏭️  gc (exists)"

gh label create human-review \
  --repo "$REPO" \
  --color D93F0B \
  --description "Block auto-merge — requires human review" \
  --force 2>/dev/null && echo "  ✅ human-review" || echo "  ⏭️  human-review (exists)"

echo "Done. Labels ready for harness operation."
