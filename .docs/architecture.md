# Architecture

## Purpose

`autowiki` turns lecture and exercise PDFs into source-grounded articles in an
Obsidian vault.

## Data flow

```text
inbox/{lectures,exercises}/*.pdf
  → shared PDF/MinerU cache lookup
  → MinerU extraction when uncached
  → source-faithful LLM preprocessing
  → obsidian/raw/<stem>.md
  → `synto run --auto-approve`
  → obsidian/wiki/
```

`ingest-pdf.sh` is the single entry point. With no arguments it processes every
PDF in both inbox directories; explicit PDF paths restrict the batch. Synto runs
once after all PDFs have been prepared, including when the inbox is empty so
pending raw notes can resume.

## Ownership boundary

Autowiki owns PDF discovery, MinerU extraction, shared caching, preprocessing,
source metadata, and original-PDF archival. Its output contract is canonical
Markdown under `obsidian/raw/`.

Synto owns provider routing, concept extraction, state, compilation, retries,
linting, approval, and published wiki articles. Autowiki invokes Synto through
its public CLI and does not import its pipeline or database internals.

## Storage and caching

- `obsidian/done/mineru_raw/` caches MinerU Markdown locally.
- `obsidian/done/preprocessed/` caches LLM-preprocessed Markdown locally.
- `obsidian/done/original_pdfs/` archives successfully prepared PDFs.
- `~/Nextcloud/linux/Documents/PDFs/` mirrors source PDFs best-effort.
- `~/Nextcloud/linux/Documents/Mineru/` shares MinerU Markdown and images with
  `gigachad-bot`.

## Configuration

- `config-preprocessing.yaml` configures only Autowiki preprocessing and MinerU.
- `obsidian/synto.toml` is the sole owner of Synto models and pipeline settings.
- `obsidian/vault-schema.md` controls final article style.
