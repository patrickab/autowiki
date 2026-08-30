# Module Map

```text
autowiki/
  __main__.py          discover/validate PDFs, run preprocessing batch, invoke Synto
  pipeline.py          MinerU/cache → preprocessing → canonical raw source
  mineru_wrapper.py    async MinerU local API wrapper
  cloud_cache.py       best-effort shared PDF, Markdown, and image cache
  synto_runner.py      tiny adapter around the installed `synto run` CLI

prompts/
  note_writing.md      source-faithful lecture preprocessing
  paper_writing.md     source-faithful scientific-paper preprocessing
  goal_extraction.md   exercise prerequisite extraction

bench/
  bench.py             run model matrices into dated, commit-stamped bundles
  app.py               browse stored benchmark results, specs, and wiki articles
  spec.yaml            configuration for the next benchmark run

tests/
  test_synto_runner.py standard-library smoke tests for the CLI boundary

config-preprocessing.yaml  preprocessing/MinerU settings
ingest-pdf.sh              only shell entry point
obsidian/synto.toml        Synto provider/model/pipeline settings
obsidian/vault-schema.md   final wiki article conventions
```

## Runtime directories

- `inbox/{lectures,exercises,papers}/` receives PDFs.
- `tmp/<stem>/` holds MinerU scratch data after failures and is removed on success.
- `obsidian/raw/` contains canonical Synto source notes.
- `obsidian/wiki/` contains Synto output.
- `obsidian/done/` contains local caches and archived PDFs.
- `obsidian/images/` contains extracted or cache-restored images.
- `bench/benchmarks/` contains isolated benchmark bundles with their copied spec,
  results, and per-model vaults.
