from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml

from .pipeline import preprocess_pdf
from .synto_runner import run_synto

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def _inbox_pdfs(root: Path) -> list[Path]:
    inbox = root / "inbox"
    directories = [inbox / "lectures", inbox / "exercises"]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return sorted(
        path for directory in directories for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess inbox PDFs into an Obsidian vault, then run Synto")
    parser.add_argument(
        "pdfs",
        nargs="*",
        type=Path,
        help="Optional inbox PDFs; defaults to every PDF in inbox/lectures and inbox/exercises",
    )
    args = parser.parse_args()

    root = Path(__file__).parent.parent.resolve()
    config = _load_config(root / "config-preprocessing.yaml")
    pdfs = [path.resolve() for path in args.pdfs] if args.pdfs else _inbox_pdfs(root)

    failures: list[Path] = []
    for pdf_path in pdfs:
        try:
            asyncio.run(preprocess_pdf(pdf_path, root, config))
        except Exception:
            failures.append(pdf_path)

    vault_path = Path(config["vault_path"])
    if not vault_path.is_absolute():
        vault_path = root / vault_path
    run_synto(vault_path)

    if failures:
        names = ", ".join(path.name for path in failures)
        raise SystemExit(f"Preprocessing failed for {len(failures)} PDF(s): {names}")


if __name__ == "__main__":
    main()
