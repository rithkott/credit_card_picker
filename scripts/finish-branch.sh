#!/usr/bin/env bash
# Post-merge cleanup for a shipped worktree branch.
# Usage: scripts/finish-branch.sh <branch> [worktree-dir-name]
# Refuses to delete anything that isn't fully merged into origin/main.
set -euo pipefail

BRANCH="${1:?usage: finish-branch.sh <branch> [worktree-dir-name]}"
DIR_NAME="${2:-$BRANCH}"
REPO_ROOT="$(git rev-parse --path-format=absolute --git-common-dir)/.."
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
WORKTREE="$REPO_ROOT/.claude/worktrees/$DIR_NAME"

git fetch origin main --prune

if ! git merge-base --is-ancestor "refs/heads/$BRANCH" origin/main; then
  echo "REFUSED: $BRANCH is not fully merged into origin/main" >&2
  exit 1
fi

if [ -d "$WORKTREE" ]; then
  git worktree remove "$WORKTREE"
fi
git branch -d "$BRANCH"
git push origin --delete "$BRANCH" 2>/dev/null \
  || echo "(no remote branch $BRANCH to delete)"
git worktree prune
echo "Cleaned: $BRANCH"
