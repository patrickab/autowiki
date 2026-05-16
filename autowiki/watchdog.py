import logging
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)


class _InboxHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[Path], None]) -> None:
        self._callback = callback

    def on_created(self, event: object) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".pdf":
            return
        if path.name.startswith(".") or path.name.startswith("~$"):
            return
        self._callback(path)


def start_watchdog(inbox_dir: Path, callback: Callable[[Path], None]) -> Observer:
    observer = Observer()
    handler = _InboxHandler(callback)
    for subdir in ["lectures", "exercises"]:
        p = inbox_dir / subdir
        p.mkdir(parents=True, exist_ok=True)
        observer.schedule(handler, str(p), recursive=False)
    observer.start()
    return observer
