#!/bin/sh
set -eu

SCRIPT_DIR="$(dirname "$0")"
cd "$SCRIPT_DIR"

echo "=== autowiki: processing all PDFs from inbox ==="

process_inbox() {
  dir="$1"
  type="$2"
  pdfs=$(find "$dir" -maxdepth 1 -name "*.pdf" 2>/dev/null || true)
  if [ -z "$pdfs" ]; then
    echo "No PDFs found in $dir"
    return
  fi
  for pdf in $pdfs; do
    echo ""
    echo "=== $(date +%H:%M:%S) Processing: $pdf ==="
    ./run.sh process "$pdf" --type "$type" || echo "WARNING: $pdf failed (continuing)"
  done
}

process_inbox "inbox/lectures" lecture
process_inbox "inbox/exercises" exercise

echo ""
echo "=== $(date +%H:%M:%S) Moving done/ to obsidian/ ==="
if [ -d done ]; then
  mkdir -p obsidian/done
  cp -ra done/* obsidian/done/
  rm -rf done
  echo "done/ -> obsidian/done/ (merged)"
fi

echo ""
echo "=== Complete ==="
