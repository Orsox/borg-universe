#!/bin/bash
set -e

# Skill — Borg Worktree Orchestration (Helper Script)
# Usage: ./manage_worktree.sh <action> [options]

ACTION=$1
REPO_ROOT=$(git rev-parse --show-toplevel)

case "$ACTION" in
  prepare)
    # Args: workflow_id, branch_name, worktree_path, base_commit
    WF_ID=$2
    BRANCH=$3
    WT_PATH=$4
    BASE_COMMIT=$5

    if [ -z "$BRANCH" ] || [ -z "$WT_PATH" ]; then
      echo "Error: Missing arguments for prepare"
      exit 1
    fi

    # Ensure worktree directory parent exists
    mkdir -p "$(dirname "$REPO_ROOT/$WT_PATH")"

    # Check if branch already exists
    if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
      echo "Branch $BRANCH already exists. Updating to $BASE_COMMIT..."
      git branch -f "$BRANCH" "$BASE_COMMIT"
    else
      echo "Creating branch $BRANCH at $BASE_COMMIT..."
      git branch "$BRANCH" "$BASE_COMMIT"
    fi

    # Add worktree
    if [ -d "$REPO_ROOT/$WT_PATH" ]; then
      echo "Removing existing directory at $WT_PATH..."
      rm -rf "$REPO_ROOT/$WT_PATH"
    fi
    
    echo "Adding worktree at $WT_PATH for branch $BRANCH..."
    git worktree add "$REPO_ROOT/$WT_PATH" "$BRANCH"
    
    # Store metadata (JSON format for easier agent parsing)
    META_FILE="$REPO_ROOT/$WT_PATH/.borg-workspace.json"
    cat > "$META_FILE" <<EOF
{
  "workflow_id": "$WF_ID",
  "branch_name": "$BRANCH",
  "worktree_path": "$WT_PATH",
  "base_commit": "$BASE_COMMIT",
  "lifecycle_state": "prepared"
}
EOF
    echo "Workspace prepared at $WT_PATH"
    ;;

  finalize)
    # Args: worktree_path, state (reviewable|archived|discarded)
    WT_PATH=$2
    STATE=$3

    if [ -z "$WT_PATH" ] || [ ! -d "$REPO_ROOT/$WT_PATH" ]; then
      echo "Error: Invalid worktree path $WT_PATH"
      exit 1
    fi

    # Commit all changes in the worktree
    echo "Committing changes in worktree $WT_PATH..."
    (cd "$REPO_ROOT/$WT_PATH" && git add . && git commit -m "Automated commit: finalizing $STATE" || echo "No changes to commit")

    META_FILE="$REPO_ROOT/$WT_PATH/.borg-workspace.json"
    if [ -f "$META_FILE" ]; then
      # Update state in metadata
      python3 -c "import json, sys; d=json.load(open('$META_FILE')); d['lifecycle_state']='$STATE'; d['head_commit']=sys.stdin.read().strip(); json.dump(d, open('$META_FILE', 'w'), indent=2)" <<EOF
$(cd "$REPO_ROOT/$WT_PATH" && git rev-parse HEAD)
EOF
    fi

    echo "Workspace at $WT_PATH finalized as $STATE"
    ;;

  sync)
    # Args: source_branch, target_branch
    SRC=$2
    TGT=$3
    if [ -z "$SRC" ] || [ -z "$TGT" ]; then
      echo "Usage: $0 sync <source_branch> <target_branch>"
      exit 1
    fi
    echo "Syncing $SRC into $TGT..."
    git checkout "$TGT"
    git merge "$SRC" --ff-only || (echo "Fast-forward merge failed. Manual intervention or conflict review required." && exit 1)
    echo "Successfully synced $SRC into $TGT"
    ;;

  cleanup)
    # Args: worktree_path
    WT_PATH=$2
    if [ -z "$WT_PATH" ]; then
      echo "Error: Missing worktree path"
      exit 1
    fi

    echo "Removing worktree at $WT_PATH..."
    git worktree remove --force "$REPO_ROOT/$WT_PATH" || rm -rf "$REPO_ROOT/$WT_PATH"
    git worktree prune
    ;;

  *)
    echo "Unknown action: $ACTION"
    echo "Usage: $0 {prepare|finalize|cleanup} [args]"
    exit 1
    ;;
esac
