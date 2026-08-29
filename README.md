# autowiki

Turn lecture and exercise PDFs into a source-grounded Obsidian wiki.

```text
inbox PDF → MinerU/cache → preprocessing → obsidian/raw → Synto → obsidian/wiki
```

## Setup

```sh
uv sync
```

Configure PDF preprocessing in `config-preprocessing.yaml`. Configure Synto's
provider, models, context windows, and article limits in `obsidian/synto.toml`.
Final article style belongs in `obsidian/vault-schema.md`.

## Ingest

Drop PDFs into `inbox/lectures/` or `inbox/exercises/`, then run:

```sh
./ingest-pdf.sh
```

The command preprocesses every inbox PDF, writes canonical source notes to
`obsidian/raw/`, archives completed PDFs under `obsidian/done/original_pdfs/`,
and invokes Synto once for the batch. Pass one or more PDF paths to process only
those files:

```sh
./ingest-pdf.sh inbox/lectures/my-lecture.pdf
```

Running the command with an empty inbox still runs Synto, allowing pending raw
notes or failed compiles to resume.

## Caching

- Local MinerU Markdown: `obsidian/done/mineru_raw/`
- Local preprocessed Markdown: `obsidian/done/preprocessed/`
- Shared PDFs: `~/Nextcloud/linux/Documents/PDFs/`
- Shared MinerU Markdown and images: `~/Nextcloud/linux/Documents/Mineru/`

The shared cache is best-effort. If Nextcloud is unavailable, ingestion continues
using the local pipeline.

## Output

- Source notes: `obsidian/raw/`
- Published articles: `obsidian/wiki/`
- Extracted images: `obsidian/images/`
