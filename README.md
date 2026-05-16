# autowiki

Zero-touch PDF → Obsidian wiki pipeline.

**Pipeline:** PDF → MinerU (markdown) → LLM (restructure) → obsidian-llm-wiki (ingest + compile + approve)

## Usage

1. Drop PDFs into `inbox/lectures/` (or `inbox/exercises/`)
2. `./run.sh inbox/lectures/my.pdf` — single PDF
3. `./run-all.sh` — batch every PDF in `inbox/lectures/`
4. Published articles appear in `obsidian/wiki/`

## Config

`config.yaml` — models, MinerU backend, reasoning effort, soft caps.
`prompts/` — note writing and goal extraction system prompts.

## Caching

`done/mineru_raw/` and `done/mineru_polished/` cache intermediate outputs. Delete a cached file to force re-run of that stage.

## GPU

Auto-detects CUDA via `torch.cuda.is_available()` for `hybrid-auto-engine` MinerU backend. Falls back to `pipeline` (CPU) otherwise.
