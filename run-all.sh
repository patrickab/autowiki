#!/bin/sh
set -eu

SCRIPT_DIR="$(dirname "$0")"
cd "$SCRIPT_DIR"

echo "=== autowiki: processing all PDFs from inbox ==="

INBOX="inbox/lectures"
PDFS=$(find "$INBOX" -maxdepth 1 -name "*.pdf" 2>/dev/null || true)

if [ -z "$PDFS" ]; then
  echo "No PDFs found in $INBOX"
  exit 0
fi

for pdf in $PDFS; do
  echo ""
  echo "=== $(date +%H:%M:%S) Processing: $pdf ==="
  ./run.sh process "$pdf" --type lecture || echo "WARNING: $pdf failed (continuing)"
done

echo ""
echo "=== $(date +%H:%M:%S) Moving done/ to obsidian/ ==="
if [ -d done ]; then
  rm -rf obsidian/done 2>/dev/null || true
  mv done obsidian/done
  echo "done/ -> obsidian/done/"
fi

echo ""
echo "=== Complete ==="
