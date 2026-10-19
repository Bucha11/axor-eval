#!/usr/bin/env bash
# Recreate the f227951 (c9v5 + §9.13a fix) kernel worktree used for the Claude live run.
# Usage: recreate_kernel_worktree.sh [dest_dir]   (default: /home/user/kf227951)
set -euo pipefail
KREPO="${KREPO:-/home/user/core-m1}"          # any checkout of the axor-core repo
COMMIT="f22795152ff5c7ea4e9fe362a3af3efe1dba49d2"
DEST="${1:-/home/user/kf227951}"
if git -C "$KREPO" cat-file -e "$COMMIT^{commit}" 2>/dev/null; then :; else
  echo "commit $COMMIT not in $KREPO — fetch axor-core first" >&2; exit 1
fi
if [ -d "$DEST/.git" ] || git -C "$KREPO" worktree list | grep -q "$DEST"; then
  echo "worktree already at $DEST"; else
  git -C "$KREPO" worktree add --detach "$DEST" "$COMMIT"
fi
test "$(git -C "$DEST" rev-parse HEAD)" = "$COMMIT" && echo "OK $DEST @ $COMMIT"
test -f "$DEST/examples/agentdojo/run_agentdojo.py" && echo "harness present"
