# Current Focus

## Active work

- The legacy obsidian-llm-wiki integration has been replaced by a public Synto
  CLI boundary.
- Root configuration is now preprocessing-only; Synto owns its settings in the
  vault.
- One `ingest-pdf.sh` command replaces the former single/batch scripts and runs
  Synto once per prepared batch.
- Canonical lecture and exercise prerequisite notes declare
  `source_type: textbook`, while `document_kind` preserves their original type.
- Preprocessing is explicitly source-faithful and leaves enrichment and
  wikilinking to Synto.
- Lecture preprocessing now condenses for study speed: slide-administration
  noise and incremental-reveal duplicates are dropped, and notes are structured
  under few concept-named sections so the note itself surfaces what matters.
- A papers variant exists: `inbox/papers/` routes to `prompts/paper_writing.md`
  (`document_kind: paper`), which drops publication noise, merges
  abstract/intro/conclusion redundancy, and trims reproducibility detail while
  keeping method, results, and ablation conclusions.

## Open questions

- `.gitmodules` is present but empty and may be removable in a separate cleanup.
- End-to-end quality still needs evaluation on representative lecture PDFs; the
  repository smoke test covers the Synto command boundary only.
