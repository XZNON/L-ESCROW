#!/usr/bin/env bash
# doc-sync.sh — PostToolUse hook for autonomous documentation maintenance.
# Fires after Edit/Write/MultiEdit. Reads JSON from stdin, extracts the
# modified file path, then runs doc-audit asynchronously (non-blocking).

set -euo pipefail

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
tool_input = data.get('tool_input', {})
path = tool_input.get('file_path') or tool_input.get('path') or ''
print(path)
" 2>/dev/null || echo "")

# No path — nothing to do
if [[ -z "$FILE_PATH" ]]; then exit 0; fi

# Skip doc files — avoid infinite loop
if [[ "$FILE_PATH" == *"CLAUDE.md"* ]]; then exit 0; fi
if [[ "$FILE_PATH" == *"api-reference"* ]]; then exit 0; fi

# Only trigger on source files
if [[ "$FILE_PATH" != *.py  && "$FILE_PATH" != *.ts  && "$FILE_PATH" != *.tsx && \
      "$FILE_PATH" != *.js  && "$FILE_PATH" != *.jsx && "$FILE_PATH" != *.go  && \
      "$FILE_PATH" != *.rs  && "$FILE_PATH" != *.rb  && "$FILE_PATH" != *.java ]]; then
  exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
LOG_FILE="$REPO_ROOT/.claude/doc-sync.log"
mkdir -p "$(dirname "$LOG_FILE")"

# Debounce: skip if this directory was audited within the last 5 minutes
DIR_KEY=$(dirname "$FILE_PATH" | tr '/' '_')
STAMP_FILE="$REPO_ROOT/.claude/.doc-sync-stamp-$DIR_KEY"
if [[ -f "$STAMP_FILE" ]]; then
  LAST=$(cat "$STAMP_FILE")
  NOW=$(date +%s)
  if (( NOW - LAST < 300 )); then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] debounce skip: $FILE_PATH" >> "$LOG_FILE"
    exit 0
  fi
fi
date +%s > "$STAMP_FILE"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] doc-sync triggered: $FILE_PATH" >> "$LOG_FILE"

# Run async — never blocks Claude Code
python3 "$REPO_ROOT/scripts/doc-audit.py" "$FILE_PATH" >> "$LOG_FILE" 2>&1 &

exit 0
