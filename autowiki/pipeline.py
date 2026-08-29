import logging
import shutil
from pathlib import Path
from typing import Any

from llm_baseclient.client import LLMClient
import yaml

from . import cloud_cache
from .mineru_wrapper import parse_pdf as mineru_parse_pdf

log = logging.getLogger(__name__)

client = LLMClient()


def _call_llm(
    system_prompt: str,
    user_content: str,
    model: str,
    max_tokens: int,
    reasoning_effort: str | None = None,
) -> str:
    kwargs: dict[str, Any] = {"max_tokens": max_tokens}
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    response = client.api_query(
        model=model,
        user_msg=user_content,
        system_prompt=system_prompt,
        **kwargs,
    )
    return response.choices[0].message.content


async def _extract_images(mineru_md_path: Path, vault_path: Path) -> None:
    images_dir = mineru_md_path.parent / "images"
    if not images_dir.is_dir():
        return
    vault_images = vault_path / "images"
    vault_images.mkdir(parents=True, exist_ok=True)
    copied = 0
    for image in images_dir.iterdir():
        if image.is_file() and not (vault_images / image.name).exists():
            shutil.copy2(image, vault_images / image.name)
            copied += 1
    if copied:
        log.info("Copied %d images to vault/images/", copied)


async def _extract_markdown(
    pdf_path: Path,
    stem: str,
    tmp_dir: Path,
    min_chars: int,
    vault_path: Path,
    backend: str,
) -> str:
    raw_dir = vault_path / "done" / "mineru_raw"
    cached = raw_dir / f"{stem}.md"

    # The shared cache owns both the source PDF and MinerU's reusable Markdown.
    cloud_cache.drop_pdf_for_mineru(pdf_path)

    if cached.exists():
        raw_markdown = cached.read_text(encoding="utf-8")
        log.info("[%s] Reusing local MinerU output (%d chars)", stem, len(raw_markdown))
    else:
        raw_markdown = cloud_cache.fetch_cached_markdown(stem)
        if raw_markdown is not None:
            log.info("[%s] Reusing shared MinerU cache", stem)
            raw_dir.mkdir(parents=True, exist_ok=True)
            cached.write_text(raw_markdown, encoding="utf-8")
            cloud_cache.fetch_cached_images(stem, vault_path / "images")
        else:
            log.info("[%s] MinerU parsing...", stem)
            mineru_md_path = await mineru_parse_pdf(pdf_path, tmp_dir, backend=backend)
            raw_markdown = mineru_md_path.read_text(encoding="utf-8")
            raw_dir.mkdir(parents=True, exist_ok=True)
            cached.write_text(raw_markdown, encoding="utf-8")
            await _extract_images(mineru_md_path, vault_path)
            cloud_cache.publish_to_cache(stem, mineru_md_path)

    if len(raw_markdown.strip()) < min_chars:
        raise RuntimeError(f"MinerU output too short ({len(raw_markdown)} chars < {min_chars})")
    return raw_markdown


def _preprocess_markdown(
    stem: str,
    raw_markdown: str,
    root_dir: Path,
    vault_path: Path,
    pdf_type: str,
    config: dict[str, Any],
) -> str:
    cached = vault_path / "done" / "preprocessed" / f"{stem}.md"
    if cached.exists():
        log.info("[%s] Reusing preprocessed Markdown", stem)
        return cached.read_text(encoding="utf-8")

    prompt_names = {"exercise": "goal_extraction.md", "paper": "paper_writing.md"}
    prompt_name = prompt_names.get(pdf_type, "note_writing.md")
    prompt = (root_dir / "prompts" / prompt_name).read_text(encoding="utf-8")
    preprocessing = config["preprocessing"]
    markdown = _call_llm(
        prompt,
        raw_markdown,
        preprocessing["model"],
        preprocessing.get("max_output_tokens", 16384),
        preprocessing.get("reasoning_effort"),
    )

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(markdown, encoding="utf-8")
    return markdown


def _write_synto_source(
    vault_path: Path,
    stem: str,
    pdf_name: str,
    pdf_type: str,
    markdown: str,
) -> Path:
    metadata = {
        "title": stem,
        "source_type": "textbook",
        "document_kind": pdf_type,
        "source_file": pdf_name,
    }
    frontmatter = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    raw_dir = vault_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / f"{stem}.md"
    destination.write_text(
        f"---\n{frontmatter}\n---\n\n{markdown.strip()}\n",
        encoding="utf-8",
    )
    return destination


def _pdf_type(pdf_path: Path) -> str:
    parent = pdf_path.parent.name.lower()
    if parent == "exercises":
        return "exercise"
    if parent == "papers":
        return "paper"
    return "lecture"


async def preprocess_pdf(
    pdf_path: Path,
    root_dir: Path,
    config: dict[str, Any],
) -> Path | None:
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Not a PDF file: {pdf_path}")

    stem = pdf_path.stem
    vault_path = Path(config["vault_path"])
    if not vault_path.is_absolute():
        vault_path = root_dir / vault_path
    vault_path.mkdir(parents=True, exist_ok=True)

    archive_dir = vault_path / "done" / "original_pdfs"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_pdf = archive_dir / pdf_path.name
    if archived_pdf.exists():
        log.info("[%s] Already archived; skipping preprocessing", stem)
        return None

    tmp_dir = root_dir / "tmp" / stem
    tmp_dir.mkdir(parents=True, exist_ok=True)
    preprocessing = config["preprocessing"]
    mineru = config.get("mineru", {})
    pdf_type = _pdf_type(pdf_path)

    try:
        raw_markdown = await _extract_markdown(
            pdf_path,
            stem,
            tmp_dir,
            preprocessing.get("min_chars", 200),
            vault_path,
            mineru.get("backend", "auto"),
        )
        markdown = _preprocess_markdown(
            stem,
            raw_markdown,
            root_dir,
            vault_path,
            pdf_type,
            config,
        )
        source_path = _write_synto_source(
            vault_path,
            stem,
            pdf_path.name,
            pdf_type,
            markdown,
        )
        shutil.move(str(pdf_path), archived_pdf)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log.info("[%s] Prepared %s", stem, source_path)
        return source_path
    except Exception:
        log.exception("[%s] Preprocessing failed", stem)
        raise
