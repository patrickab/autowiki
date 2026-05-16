import logging
from pathlib import Path

from obsidian_llm_wiki.client_factory import build_client
from obsidian_llm_wiki.config import Config as OLWConfig
from obsidian_llm_wiki.pipeline.compile import approve_drafts, compile_concepts
from obsidian_llm_wiki.pipeline.ingest import ingest_note
from obsidian_llm_wiki.state import StateDB

log = logging.getLogger(__name__)


def _patch_ollama_generate_for_cloud(client):
    og = type(client)
    if og.__name__ != "OllamaClient":
        return

    _orig_generate = client.generate

    def _patched_generate(prompt, model, system="", format=None, num_ctx=8192, num_predict=-1):
        if num_predict <= 0:
            num_predict = num_ctx
        return _orig_generate(prompt, model, system=system, format=format, num_ctx=num_ctx, num_predict=num_predict)

    client.generate = _patched_generate


def process_note(
    md_path: str | Path,
    vault_path: str | Path,
    overrides: dict | None = None,
) -> list[Path]:
    md_path = Path(md_path)
    vault_path = Path(vault_path).resolve()

    raw_dir = vault_path / "raw"
    raw_dir.mkdir(exist_ok=True)
    dest = raw_dir / md_path.name
    dest.write_text(md_path.read_text())

    config = OLWConfig.from_vault(vault_path, overrides=overrides or {})
    client = build_client(config)
    _patch_ollama_generate_for_cloud(client)
    client.require_healthy()
    db = StateDB(config.state_db_path)

    result = ingest_note(dest, config, client, db)
    if result is None:
        log.info("Note already ingested or failed: %s", dest.name)
        return []

    draft_paths, _failed, _timings = compile_concepts(config, client, db)
    if not draft_paths:
        log.warning("No drafts generated for: %s", dest.name)
        return []

    published = approve_drafts(config, db, draft_paths)
    log.info("Published %d articles from: %s", len(published), dest.name)
    return published
