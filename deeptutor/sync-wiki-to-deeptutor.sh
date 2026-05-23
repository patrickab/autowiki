#!/usr/bin/env bash
# ============================================================
# sync-wiki-to-deeptutor.sh
# ============================================================
# Ingests Obsidian wiki articles into DeepTutor's RAG engine.
# The obsidian/wiki/ directory is mounted read-only into the
# container at /app/data/wiki_mount, so no file copying needed.
#
# Run this whenever you add/change wiki articles and want
# DeepTutor to be aware of them.
# ============================================================
set -euo pipefail

CLI_CMD="python -m deeptutor_cli.main"

echo "==> Ingesting obsidian/wiki/ into DeepTutor KB"

if ! docker exec deeptutor $CLI_CMD kb list 2>/dev/null | grep -q '^wiki$'; then
  echo "     Creating KB 'wiki'..."
  docker exec deeptutor $CLI_CMD kb create wiki --docs-dir /app/data/wiki_mount
else
  echo "     Adding new/updated documents to KB 'wiki'..."
  docker exec deeptutor $CLI_CMD kb add wiki --docs-dir /app/data/wiki_mount
fi

echo ""
echo "Sync complete. Open http://localhost:3782 and check the Knowledge tab."
