import logging
import shutil
from pathlib import Path
from typing import Any

from llm_baseclient.client import LLMClient

from .mineru_wrapper import parse_pdf as mineru_parse_pdf
from .olw_integration import process_note

log = logging.getLogger(__name__)

client = LLMClient()


def _call_llm(system_prompt: str, user_content: str, model: str, max_tokens: int, reasoning_effort: str | None = None) -> str:
    kwargs = {"max_tokens": max_tokens}
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    resp = client.api_query(model=model, user_msg=user_content, system_prompt=system_prompt, **kwargs)
    return resp.choices[0].message.content


async def _extract_imgs(mineru_md_path: Path, vault_path: Path) -> None:
    images_dir = mineru_md_path.parent / "images"
    if not images_dir.is_dir():
        return
    vault_images = vault_path / "images"
    vault_images.mkdir(parents=True, exist_ok=True)
    count = 0
    for img in images_dir.iterdir():
        if img.is_file() and not (vault_images / img.name).exists():
            shutil.copy2(str(img), str(vault_images / img.name))
            count += 1
    if count:
        log.info("Copied %d images to vault/images/", count)


async def _extract_markdown(pdf_path: Path, stem: str, root_dir: Path, tmp_base: Path, min_chars: int, vault_path: Path, backend: str = "pipeline") -> str:
    """Parse the PDF to markdown via MinerU. Cache result in done/mineru_raw/ and reuse on subsequent runs."""
    done_dir = root_dir / "done"
    raw_dir = done_dir / "mineru_raw"
    cached = raw_dir / f"{stem}.md"

    if cached.exists():
        raw_md = cached.read_text()
        log.info("[%s] Reusing cached MinerU output (%d chars)", stem, len(raw_md))
    else:
        log.info("[%s] MinerU parsing...", stem)
        mineru_md_path = await mineru_parse_pdf(pdf_path, tmp_base, backend=backend)
        raw_md = mineru_md_path.read_text()
        raw_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(raw_md)
        await _extract_imgs(mineru_md_path, vault_path)

    if len(raw_md.strip()) < min_chars:
        raise RuntimeError(f"MinerU output too short ({len(raw_md)} chars < {min_chars})")

    return raw_md


def _restructure_note(
    stem: str, raw_md: str, root_dir: Path, models: dict[str, str], pdf_type: str, reasoning_effort: str | None, llm_max_tokens: int = 16384
) -> str:
    """Reformat raw MinerU markdown into polished Obsidian notes via LLM. Cache result in done/mineru_polished/ and reuse on subsequent runs."""
    done_dir = root_dir / "done"
    polished_dir = done_dir / "mineru_polished"
    cached = polished_dir / f"{stem}.md"

    if cached.exists():
        log.info("[%s] Reusing cached polished output", stem)
        return cached.read_text()

    prompts_dir = root_dir / "prompts"
    note_prompt = (prompts_dir / "note_writing.md").read_text()
    llm_kwargs = {"max_tokens": llm_max_tokens}
    if reasoning_effort:
        llm_kwargs["reasoning_effort"] = reasoning_effort

    if pdf_type == "exercise":
        log.info("[%s] Extracting learning goals...", stem)
        goal_prompt = (prompts_dir / "goal_extraction.md").read_text()
        goals = _call_llm(goal_prompt, raw_md, models["fast"], **llm_kwargs)
        combined = f"# Source Material\n\n{raw_md}\n\n# Learning Goals\n\n{goals}"
        polished = _call_llm(note_prompt, combined, models["heavy"], **llm_kwargs)
    else:
        polished = _call_llm(note_prompt, raw_md, models["heavy"], **llm_kwargs)

    polished_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(polished)
    return polished


async def process_pdf(pdf_path: Path, root_dir: Path, config: dict[str, Any]) -> list[Path]:
    stem = pdf_path.stem
    inbox_rel = pdf_path.relative_to(root_dir / "inbox")
    pdf_type = "exercise" if "exercises" in str(inbox_rel) else "lecture"

    done_dir = root_dir / "done"
    done_dir.mkdir(exist_ok=True)
    orig_pdfs_dir = done_dir / "original_pdfs"
    orig_pdfs_dir.mkdir(exist_ok=True)
    if (orig_pdfs_dir / pdf_path.name).exists():
        log.info("[%s] Already in done/original_pdfs, skipping", stem)
        return []

    tmp_base = root_dir / "tmp" / stem
    tmp_base.mkdir(parents=True, exist_ok=True)

    vault_path = Path(config["vault_path"])
    models = config["models"]
    mineru_backend = config.get("mineru", {}).get("backend", "pipeline")
    reasoning_effort = models.get("reasoning_effort")
    min_chars = config.get("pipeline", {}).get("min_chars", 200)
    article_max_tokens = config.get("pipeline", {}).get("article_max_tokens", 16384)
    concept_draft_soft_cap = config.get("pipeline", {}).get("per_concept_tokens", 8192)
    ollama_cfg = config.get("ollama", {})

    olw_overrides: dict[str, Any] = {
        "pipeline": {
            "article_max_tokens": article_max_tokens,
            "concept_draft_soft_cap": concept_draft_soft_cap,
        },
        "ollama": {
            "fast_ctx": ollama_cfg.get("fast_ctx", 16384),
            "heavy_ctx": ollama_cfg.get("heavy_ctx", 32768),
        },
    }
    max_output_tokens = ollama_cfg.get("max_output_tokens", 65536)

    try:
        raw_md = await _extract_markdown(pdf_path, stem, root_dir, tmp_base, min_chars, vault_path, backend=mineru_backend)
        polished = _restructure_note(stem, raw_md, root_dir, models, pdf_type, reasoning_effort, article_max_tokens)

        polished_path = tmp_base / f"{stem}_polished.md"
        polished_path.write_text(polished)

        log.info("[%s] Feeding to obsidian-llm-wiki...", stem)
        published = process_note(polished_path, vault_path, overrides=olw_overrides, max_output_tokens=max_output_tokens)

        shutil.move(str(pdf_path), str(orig_pdfs_dir / pdf_path.name))

        shutil.rmtree(tmp_base, ignore_errors=True)
        log.info("[%s] Done — %d articles published", stem, len(published))
        return published

    except Exception:
        log.exception("[%s] Pipeline failed", stem)
        raise
