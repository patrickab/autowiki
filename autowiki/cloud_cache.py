"""Shared MinerU cache with gigachad-bot (~/git/gigachad-bot), so a PDF parsed by
either project is never re-OCR'd by the other. Mirrors gigachad-bot's
src/config.py (DIRECTORY_OUTPUT_MINERU / DIRECTORY_OUTPUT_PDF) and its
src/backend/routes/mineru.py cache-lookup/renaming scheme byte-for-byte, so
markdown produced by one side is directly readable by the other.

All operations here are best-effort: a missing/unmounted Nextcloud share must
never break the local pipeline, only skip the acceleration.
"""

import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

DIRECTORY_CLOUD = Path("~/Nextcloud/linux").expanduser()
CLOUD_MINERU_DIR = DIRECTORY_CLOUD / "Documents" / "Mineru"
CLOUD_PDF_DIR = DIRECTORY_CLOUD / "Documents" / "PDFs"

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}


def fetch_cached_markdown(stem: str) -> str | None:
    """Return already-parsed markdown for *stem* from the shared cache, if any."""
    try:
        cloud_md = CLOUD_MINERU_DIR / f"{stem}.md"
        if cloud_md.is_file():
            return cloud_md.read_text(encoding="utf-8")
    except OSError:
        log.exception("Shared MinerU cache lookup failed for %s", stem)
    return None


def fetch_cached_images(stem: str, dest_dir: Path) -> None:
    """Copy this PDF's renamed images (<stem>-<idx>.<ext>) from the shared cache into *dest_dir*."""
    try:
        cloud_images = CLOUD_MINERU_DIR / "images"
        if not cloud_images.is_dir():
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{stem}-"
        for img in cloud_images.iterdir():
            if img.is_file() and img.name.startswith(prefix) and not (dest_dir / img.name).exists():
                shutil.copy2(img, dest_dir / img.name)
    except OSError:
        log.exception("Shared MinerU image fetch failed for %s", stem)


def drop_pdf_for_mineru(pdf_path: Path) -> None:
    """Mirror *pdf_path* into gigachad-bot's shared PDF inbox so it can pick it up too."""
    try:
        CLOUD_PDF_DIR.mkdir(parents=True, exist_ok=True)
        dest = CLOUD_PDF_DIR / pdf_path.name
        if not dest.exists():
            shutil.copy2(pdf_path, dest)
    except OSError:
        log.exception("Failed to mirror %s into shared PDF inbox", pdf_path.name)


def publish_to_cache(stem: str, md_path: Path) -> None:
    """Publish a freshly-parsed MinerU result to the shared cache.

    Images are renamed ``<stem>-<idx>.<ext>`` and the markdown rewritten to
    match, identical to gigachad-bot's own cache-write path, so its cache
    reader (keyed only on filename prefix) can find them.
    """
    try:
        global_md = CLOUD_MINERU_DIR / f"{stem}.md"
        if global_md.exists():
            return

        md_content = md_path.read_text(encoding="utf-8")
        images_dir = md_path.parent / "images"
        images = sorted(
            (p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS),
            key=lambda p: p.name,
        ) if images_dir.is_dir() else []

        count = len(images)
        width = len(str(count)) if count else 1
        cloud_images_dir = CLOUD_MINERU_DIR / "images"
        cloud_images_dir.mkdir(parents=True, exist_ok=True)

        for idx, img_path in enumerate(images, start=1):
            new_name = f"{stem}-{idx:0{width}d}{img_path.suffix.lower()}"
            md_content = re.sub(
                r"\]\([^)]*" + re.escape(img_path.name) + r"\)",
                r"](images/" + new_name + r")",
                md_content,
            )
            shutil.copy2(img_path, cloud_images_dir / new_name)

        CLOUD_MINERU_DIR.mkdir(parents=True, exist_ok=True)
        global_md.write_text(md_content, encoding="utf-8")
        log.info("[%s] Published MinerU output to shared cache", stem)
    except OSError:
        log.exception("Failed to publish %s to shared MinerU cache", stem)
