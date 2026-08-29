# Conventions

## Language / runtime
- Python >= 3.12, packaged with `hatchling` (`pyproject.toml`).
- MinerU extraction is async and is invoked with `asyncio.run()` by the batch CLI.
- `ingest-pdf.sh` is POSIX `sh` (`#!/bin/sh`, `set -eu`) and delegates immediately
  to `uv run python -m autowiki`.

## Dependencies
- Declared in `pyproject.toml`; `uv.lock` is the lockfile (uv-managed venv).
- Notable git dependency: `llm-baseclient` pulled directly from
  `github.com/patrickab/llm-baseclient@main` (not a PyPI package).
- `synto` is invoked through its public CLI; Autowiki does not depend on Synto's
  Python pipeline internals.
- Dependabot (`.github/dependabot.yml`) runs weekly on the `pip` ecosystem,
  reviewer `patrickab`, groups `streamlit*`/`st-copy` updates together.

## Lint / format
- Ruff, configured in `pyproject.toml`:
  - `target-version = "py312"`, `line-length = 135`, `respect-gitignore = true`.
  - Lint select: `E`, `F`, `B`, `SIM`; ignore: `RUF100`, `B904`.
  - isort: force-sort-within-sections, `standard-library, third-party,
    first-party, local-folder`, first-party = `autowiki`, no
    split-on-trailing-comma.
  - Formatter: Ruff's default (Black-compatible).

## Naming
- Modules and functions: `snake_case`. Private/internal helpers prefixed with
  `_` (e.g. `_extract_markdown`, `_call_llm`, `_detect_backend`).
- Each module opens with `log = logging.getLogger(__name__)` (or
  `"autowiki"` in `__main__.py`) — standard `logging`, no print-based
  debugging in library code.

## Testing
- Tests use the standard-library `unittest` runner:
  `python -m unittest discover -s tests`.

## Commit style
- Recent history is a mix of terse lowercase summaries (`add useful stuff`,
  `clean trash`) and Dependabot's conventional-commit style
  (`build(deps): update torch requirement from >=2.12.0 to >=2.13.0`).
  Merge commits from PRs are kept (not squashed).
