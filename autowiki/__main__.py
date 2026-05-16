from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import yaml
from obsidian_llm_wiki.config import default_wiki_toml

from .pipeline import process_pdf
from .watchdog import start_watchdog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("autowiki")


def _ensure_vault_config(root: Path, config: dict[str, Any]) -> None:
    vault_path = Path(config["vault_path"])
    if not vault_path.is_absolute():
        vault_path = root / vault_path
    vault_path.mkdir(parents=True, exist_ok=True)
    toml_path = vault_path / "wiki.toml"
    if toml_path.exists():
        return
    models = config.get("models", {})
    fast = models.get("fast", "").removeprefix("ollama/")
    heavy = models.get("heavy", "").removeprefix("ollama/")
    toml_path.write_text(default_wiki_toml(fast_model=fast, heavy_model=heavy))
    log.info("Wrote %s", toml_path)


def _load_config(config_path: str | Path) -> dict[str, Any]:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _run_async(coro: "asyncio.Future | Any") -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            import threading

            future: concurrent.futures.Future[Any] = concurrent.futures.Future()

            def _runner() -> None:
                try:
                    result = asyncio.run(coro)
                    future.set_result(result)
                except Exception as e:
                    future.set_exception(e)

            threading.Thread(target=_runner, daemon=True).start()
            future.result()
        else:
            asyncio.run(coro)
    except RuntimeError:
        asyncio.run(coro)


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF to Obsidian Learning Pipeline")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("watch", help="Watch inbox/ for new PDFs and process them")

    proc = sub.add_parser("process", help="Process a single PDF")
    proc.add_argument("pdf", help="Path to PDF file")
    proc.add_argument(
        "--type",
        choices=["auto", "lecture", "exercise"],
        default="auto",
        help="PDF type (default: auto-detect from path)",
    )

    args = parser.parse_args()
    root = Path(__file__).parent.parent.resolve()
    config = _load_config(root / "config.yaml")
    _ensure_vault_config(root, config)

    if args.command == "watch":
        inbox = root / "inbox"
        log.info("Watching %s/lectures + %s/exercises ...", inbox, inbox)

        def _on_pdf(path: Path) -> None:
            log.info("New PDF: %s", path)
            _run_async(process_pdf(path, root, config))

        observer = start_watchdog(inbox, _on_pdf)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    elif args.command == "process":
        pdf_path = Path(args.pdf).resolve()
        _run_async(process_pdf(pdf_path, root, config))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
