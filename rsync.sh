#!/usr/bin/env bash

set -e

# === CONFIG ===
GLOBAL_CLAUDE_DIR="$HOME/.claude"
PROJECT_DIR="$(pwd)"
PROJECT_CLAUDE_DIR="$PROJECT_DIR"

# Optionen
DRY_RUN=false
BACKUP=true

# === ARG PARSING ===
for arg in "$@"; do
  case $arg in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --no-backup)
      BACKUP=false
      shift
      ;;
    *)
      ;;
  esac
done

echo "== Claude Sync Script =="
echo "Global:   $GLOBAL_CLAUDE_DIR"
echo "Project:  $PROJECT_CLAUDE_DIR"
echo

# === CHECKS ===
if [ ! -d "$GLOBAL_CLAUDE_DIR" ]; then
  echo "❌ Global .claude directory not found!"
  exit 1
fi

mkdir -p "$PROJECT_CLAUDE_DIR"

# === RSYNC FLAGS ===
RSYNC_FLAGS="-av"

if [ "$DRY_RUN" = true ]; then
  RSYNC_FLAGS="$RSYNC_FLAGS --dry-run"
fi

if [ "$BACKUP" = true ]; then
  RSYNC_FLAGS="$RSYNC_FLAGS --backup --backup-dir=$PROJECT_CLAUDE_DIR/.backup_$(date +%s)"
fi

# === SYNC FUNCTION ===
sync_folder() {
  local name=$1

  if [ -d "$GLOBAL_CLAUDE_DIR/$name" ]; then
    echo "➡️ Syncing $name..."
    mkdir -p "$PROJECT_CLAUDE_DIR/$name"

    rsync $RSYNC_FLAGS \
      "$GLOBAL_CLAUDE_DIR/$name/" \
      "$PROJECT_CLAUDE_DIR/$name/"
  else
    echo "⚠️ Skipping $name (not found globally)"
  fi

  echo
}

# === EXECUTION ===
sync_folder "agents"
sync_folder "skills"

echo "✅ Done."