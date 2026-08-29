This file is a merged representation of the entire codebase, combined into a single document by Repomix.
The content has been processed where content has been compressed (code blocks are separated by ⋮---- delimiter).

# File Summary

## Purpose
This file contains a packed representation of the entire repository's contents.
It is designed to be easily consumable by AI systems for analysis, code review,
or other automated processes.

## File Format
The content is organized as follows:
1. This summary section
2. Repository information
3. Directory structure
4. Repository files (if enabled)
5. Multiple file entries, each consisting of:
  a. A header with the file path (## File: path/to/file)
  b. The full contents of the file in a code block

## Usage Guidelines
- This file should be treated as read-only. Any changes should be made to the
  original repository files, not this packed version.
- When processing this file, use the file path to distinguish
  between different files in the repository.
- Be aware that this file may contain sensitive information. Handle it with
  the same level of security as you would the original repository.

## Notes
- Some files may have been excluded based on .gitignore rules and Repomix's configuration
- Binary files are not included in this packed representation. Please refer to the Repository Structure section for a complete list of file paths, including binary files
- Files matching patterns in .gitignore are excluded
- Files matching default ignore patterns are excluded
- Content has been compressed - code blocks are separated by ⋮---- delimiter
- Files are sorted by Git change count (files with more changes are at the bottom)

# Directory Structure
```
.github/
  dependabot.yml
autowiki/
  __init__.py
  __main__.py
  cloud_cache.py
  mineru_wrapper.py
  olw_integration.py
  pipeline.py
  watchdog.py
prompts/
  goal_extraction.md
  note_writing.md
.gitignore
.gitmodules
config.yaml
ingest-all-pdfs.sh
ingest-single-pdf.sh
pyproject.toml
README.md
```

# Files

## File: .github/dependabot.yml
```yaml
# .github/dependabot.yml

version: 2
updates:

  # Main rule for your Python dependencies
  - package-ecosystem: "pip"
    directory: "/" # Look for pyproject.toml in the root directory
    schedule:
      interval: "weekly"

    reviewers:
      - "patrickab"

    # Group related updates to reduce PR noise
    groups:
      streamlit-plugins:
        patterns:
          - "streamlit*"
          - "st-copy"
```

## File: autowiki/cloud_cache.py
```python
"""Shared MinerU cache with gigachad-bot (~/git/gigachad-bot), so a PDF parsed by
either project is never re-OCR'd by the other. Mirrors gigachad-bot's
src/config.py (DIRECTORY_OUTPUT_MINERU / DIRECTORY_OUTPUT_PDF) and its
src/backend/routes/mineru.py cache-lookup/renaming scheme byte-for-byte, so
markdown produced by one side is directly readable by the other.

All operations here are best-effort: a missing/unmounted Nextcloud share must
never break the local pipeline, only skip the acceleration.
"""
⋮----
log = logging.getLogger(__name__)
⋮----
DIRECTORY_CLOUD = Path("~/Nextcloud/linux").expanduser()
CLOUD_MINERU_DIR = DIRECTORY_CLOUD / "Documents" / "Mineru"
CLOUD_PDF_DIR = DIRECTORY_CLOUD / "Documents" / "PDFs"
⋮----
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}
⋮----
def fetch_cached_markdown(stem: str) -> str | None
⋮----
"""Return already-parsed markdown for *stem* from the shared cache, if any."""
⋮----
cloud_md = CLOUD_MINERU_DIR / f"{stem}.md"
⋮----
def fetch_cached_images(stem: str, dest_dir: Path) -> None
⋮----
"""Copy this PDF's renamed images (<stem>-<idx>.<ext>) from the shared cache into *dest_dir*."""
⋮----
cloud_images = CLOUD_MINERU_DIR / "images"
⋮----
prefix = f"{stem}-"
⋮----
def drop_pdf_for_mineru(pdf_path: Path) -> None
⋮----
"""Mirror *pdf_path* into gigachad-bot's shared PDF inbox so it can pick it up too."""
⋮----
dest = CLOUD_PDF_DIR / pdf_path.name
⋮----
def publish_to_cache(stem: str, md_path: Path) -> None
⋮----
"""Publish a freshly-parsed MinerU result to the shared cache.

    Images are renamed ``<stem>-<idx>.<ext>`` and the markdown rewritten to
    match, identical to gigachad-bot's own cache-write path, so its cache
    reader (keyed only on filename prefix) can find them.
    """
⋮----
global_md = CLOUD_MINERU_DIR / f"{stem}.md"
⋮----
md_content = md_path.read_text(encoding="utf-8")
images_dir = md_path.parent / "images"
images = sorted(
⋮----
count = len(images)
width = len(str(count)) if count else 1
cloud_images_dir = CLOUD_MINERU_DIR / "images"
⋮----
new_name = f"{stem}-{idx:0{width}d}{img_path.suffix.lower()}"
md_content = re.sub(
```

## File: prompts/note_writing.md
```markdown
# Role
You are a Didactic Synthesizer. Your function is to transform unstructured lecture material into a logically-structured, factually-accurate, high-fidelity knowledge base in Obsidian markdown.

# Core Directive
Transform and restructure the source material, but preserve EVERY definition,
formula, theorem, example, and factual claim. You are a refiner and reorganizer,
not a summarizer — do not condense or omit information. The final output must
serve as a self-contained reference from which a reader could reconstruct every
detail present in the original. Success is measured by accuracy, clarity,
completeness, and pedagogical structure.

# Style Requirements
- Write in crisp, concise prose suitable for advanced undergraduate / graduate study
- Use ## section headings for major topics, ### for subtopics
- Use [[wikilinks]] when referencing other concepts or topics
- Include inline definitions for key terms on first use
- Add concrete examples where helpful for understanding
- Keep each note self-contained but reference related topics via wikilinks
- Use LaTeX math notation ($...$ for inline, $$...$$ for blocks) where appropriate
- Do NOT include a ## Sources or ## See Also section (those are auto-generated)
```

## File: .gitignore
```
__pycache__/
*.pyc
*.jpg

# Ignore contents of these dirs but not .gitkeep
done/*
inbox/*
obsidian/*
tmp/*

!**/.gitkeep
```

## File: ingest-all-pdfs.sh
```bash
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
```

## File: ingest-single-pdf.sh
```bash
#!/bin/sh
cd "$(dirname "$0")"
.venv/bin/python -m autowiki "$@"
```

## File: README.md
```markdown
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
```

## File: prompts/goal_extraction.md
```markdown
You are a math tutor preparing background material for a student.

Given the following exercise set, produce a structured list of **prerequisite concepts** the student needs to understand *before* attempting these exercises.

Rules:
- Start with a structured markdown checklist "Learning Goals" of topics/concepts the student needs to learn/understand first in order to solve the exercise sheet
- Provide **only background knowledge** — definitions, theorems, techniques, and conceptual foundations
- Do **NOT** provide solutions, hints, partial proofs, or answer outlines for any exercise
- For each concept, include a one-sentence justification explaining why it is relevant to the exercises
- Output structured markdown with concept names as ## headings and justifications as paragraph text
- Include relevant formulas, definitions, or notation where appropriate for reference
```

## File: .gitmodules
```

```

## File: autowiki/__init__.py
```python
"""autowiki — PDF to Obsidian learning pipeline."""
```

## File: autowiki/mineru_wrapper.py
```python
log = logging.getLogger(__name__)
⋮----
async def parse_pdf(pdf_path: str | Path, out_dir: str | Path, backend: str = "pipeline") -> Path
⋮----
pdf_path = Path(pdf_path)
out_dir = Path(out_dir).resolve()
⋮----
backend = _detect_backend()
⋮----
form_data = api_client.build_parse_request_form_data(
assets = [api_client.UploadAsset(path=pdf_path, upload_name=pdf_path.name)]
⋮----
local = api_client.LocalAPIServer()
base_url = local.start()
⋮----
sub = await api_client.submit_parse_task(base_url, assets, form_data)
⋮----
zp = await api_client.download_result_zip(cli, sub, task_label=pdf_path.name)
⋮----
md_files = sorted(out_dir.glob("**/*.md"), key=lambda p: len(p.name))
⋮----
def _detect_backend() -> str
```

## File: autowiki/watchdog.py
```python
log = logging.getLogger(__name__)
⋮----
class _InboxHandler(FileSystemEventHandler)
⋮----
def __init__(self, callback: Callable[[Path], None]) -> None
⋮----
def on_created(self, event: object) -> None
⋮----
path = Path(event.src_path)
⋮----
def start_watchdog(inbox_dir: Path, callback: Callable[[Path], None]) -> Observer
⋮----
observer = Observer()
handler = _InboxHandler(callback)
⋮----
p = inbox_dir / subdir
```

## File: autowiki/__main__.py
```python
log = logging.getLogger("autowiki")
⋮----
def _ensure_vault_config(root: Path, config: dict[str, Any]) -> None
⋮----
vault_path = Path(config["vault_path"])
⋮----
vault_path = root / vault_path
⋮----
toml_path = vault_path / "wiki.toml"
⋮----
models = config.get("models", {})
fast = models.get("fast", "").removeprefix("ollama/")
heavy = models.get("heavy", "").removeprefix("ollama/")
⋮----
def _load_config(config_path: str | Path) -> dict[str, Any]
⋮----
def _run_async(coro: "asyncio.Future | Any") -> None
⋮----
loop = asyncio.get_event_loop()
⋮----
future: concurrent.futures.Future[Any] = concurrent.futures.Future()
⋮----
def _runner() -> None
⋮----
result = asyncio.run(coro)
⋮----
def main() -> None
⋮----
parser = argparse.ArgumentParser(description="PDF to Obsidian Learning Pipeline")
sub = parser.add_subparsers(dest="command")
⋮----
proc = sub.add_parser("process", help="Process a single PDF")
⋮----
args = parser.parse_args()
root = Path(__file__).parent.parent.resolve()
config = _load_config(root / "config.yaml")
⋮----
inbox = root / "inbox"
⋮----
def _on_pdf(path: Path) -> None
⋮----
observer = start_watchdog(inbox, _on_pdf)
⋮----
pdf_path = Path(args.pdf).resolve()
```

## File: config.yaml
```yaml
vault_path: "./obsidian"

models:
  fast: "ollama/deepseek-v4-pro:cloud"
  heavy: "ollama/deepseek-v4-pro:cloud"
  reasoning_effort: "high"

ollama:
  fast_ctx: 500000
  heavy_ctx: 500000
  max_output_tokens: 65536

mineru:
  backend: "auto"

pipeline:
  min_chars: 50
  article_max_tokens: 16384
  per_concept_tokens: 16384
```

## File: autowiki/olw_integration.py
```python
log = logging.getLogger(__name__)
⋮----
def _patch_ollama_generate_for_cloud(client, max_output_tokens: int = 65536)
⋮----
og = type(client)
⋮----
_orig_generate = client.generate
⋮----
def _patched_generate(prompt, model, system="", format=None, num_ctx=8192, num_predict=-1, **kwargs)
⋮----
num_predict = max_output_tokens
⋮----
md_path = Path(md_path)
vault_path = Path(vault_path).resolve()
⋮----
raw_dir = vault_path / "raw"
⋮----
dest = raw_dir / md_path.name
⋮----
config = SyntoConfig.from_vault(vault_path, **(overrides or {}))
client = build_client(config)
⋮----
db = StateDB(config.state_db_path)
⋮----
result = ingest_note(dest, config, client, db)
skip_compile = result is None and db.concepts_needing_compile() == []
⋮----
published = approve_drafts(config, db, draft_paths)
```

## File: autowiki/pipeline.py
```python
log = logging.getLogger(__name__)
⋮----
client = LLMClient()
⋮----
def _call_llm(system_prompt: str, user_content: str, model: str, max_tokens: int, reasoning_effort: str | None = None) -> str
⋮----
kwargs = {"max_tokens": max_tokens}
⋮----
resp = client.api_query(model=model, user_msg=user_content, system_prompt=system_prompt, **kwargs)
⋮----
async def _extract_imgs(mineru_md_path: Path, vault_path: Path) -> None
⋮----
images_dir = mineru_md_path.parent / "images"
⋮----
vault_images = vault_path / "images"
⋮----
count = 0
⋮----
"""Parse the PDF to markdown via MinerU. Cache result in done/mineru_raw/ and reuse on subsequent runs."""
done_dir = vault_path / "done"
raw_dir = done_dir / "mineru_raw"
cached = raw_dir / f"{stem}.md"
⋮----
raw_md = cached.read_text()
⋮----
cloud_md = cloud_cache.fetch_cached_markdown(stem)
⋮----
raw_md = cloud_md
⋮----
mineru_md_path = await mineru_parse_pdf(pdf_path, tmp_base, backend=backend)
raw_md = mineru_md_path.read_text()
⋮----
"""Reformat raw MinerU markdown into polished Obsidian notes via LLM. Cache result in done/mineru_polished/ and reuse on subsequent runs."""
polished_dir = done_dir / "mineru_polished"
cached = polished_dir / f"{stem}.md"
⋮----
prompts_dir = root_dir / "prompts"
note_prompt = (prompts_dir / "note_writing.md").read_text()
llm_kwargs = {"max_tokens": llm_max_tokens}
⋮----
goal_prompt = (prompts_dir / "goal_extraction.md").read_text()
polished = _call_llm(goal_prompt, raw_md, models["heavy"], **llm_kwargs)
⋮----
polished = _call_llm(note_prompt, raw_md, models["heavy"], **llm_kwargs)
⋮----
async def process_pdf(pdf_path: Path, root_dir: Path, config: dict[str, Any]) -> list[Path]
⋮----
stem = pdf_path.stem
inbox_rel = pdf_path.relative_to(root_dir / "inbox")
pdf_type = "exercise" if "exercises" in str(inbox_rel) else "lecture"
⋮----
vault_path = Path(config["vault_path"])
⋮----
vault_path = root_dir / vault_path
⋮----
orig_pdfs_dir = done_dir / "original_pdfs"
⋮----
tmp_base = root_dir / "tmp" / stem
⋮----
models = config["models"]
mineru_backend = config.get("mineru", {}).get("backend", "pipeline")
reasoning_effort = models.get("reasoning_effort")
min_chars = config.get("pipeline", {}).get("min_chars", 200)
article_max_tokens = config.get("pipeline", {}).get("article_max_tokens", 16384)
concept_draft_soft_cap = config.get("pipeline", {}).get("per_concept_tokens", 8192)
ollama_cfg = config.get("ollama", {})
⋮----
olw_overrides: dict[str, Any] = {
max_output_tokens = ollama_cfg.get("max_output_tokens", 65536)
⋮----
raw_md = await _extract_markdown(pdf_path, stem, root_dir, tmp_base, min_chars, vault_path, backend=mineru_backend)
polished = _restructure_note(stem, raw_md, root_dir, done_dir, models, pdf_type, reasoning_effort, article_max_tokens)
⋮----
polished_path = tmp_base / f"{stem}_polished.md"
⋮----
published = process_note(polished_path, vault_path, overrides=olw_overrides, max_output_tokens=max_output_tokens)
```

## File: pyproject.toml
```toml
[project]
name = "autowiki"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "llm-baseclient @ git+https://github.com/patrickab/llm-baseclient.git@main",
    "synto>=0.7.0",
    "mineru[all]",
    "pyyaml",
    "watchdog",
    "torch>=2.13.0",
    "torchvision>=0.28.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["autowiki"]

[tool.hatch.metadata]
allow-direct-references = true

[tool.ruff]
target-version = "py312"
respect-gitignore = true
line-length = 135

[tool.ruff.lint]
select = [
  "E",   # pycodestyle errors
  "F",   # pyflakes
  "B",   # bugbear
  "SIM", # simplify
]
ignore = [
  "RUF100",
  "B904"
]

[tool.ruff.lint.isort]
force-sort-within-sections = true
section-order = ["standard-library", "third-party", "first-party", "local-folder"]
known-first-party = ["autowiki"]
split-on-trailing-comma = false

# Enables Ruff formatter with default options (Black-compatible)
[tool.ruff.format]
```
