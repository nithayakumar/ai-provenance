import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from lib.constants import IMAGE_EXTENSIONS


def _wait_until_stable(path: Path, stable_ms: int = 500, timeout_s: int = 30) -> bool:
    """Wait until file size stops changing. Returns True when stable, False on timeout."""
    deadline = time.time() + timeout_s
    last_size = -1
    stable_since = None
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last_size:
            if stable_since is None:
                stable_since = time.time()
            elif (time.time() - stable_since) * 1000 >= stable_ms:
                return True
        else:
            last_size = size
            stable_since = None
        time.sleep(0.1)
    return False


class _ImageHandler(FileSystemEventHandler):
    def __init__(self, process_fn: Callable, csv_path: str):
        self.process_fn = process_fn
        self.csv_path = csv_path
        self._seen: set[str] = set()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            return
        if path.name.startswith(".") or path.name.endswith(".provenance.json"):
            return
        key = str(path.resolve())
        if key in self._seen:
            return
        self._seen.add(key)

        if not _wait_until_stable(path):
            self._seen.discard(key)
            return

        # Companion .url file: line 1 = image URL, line 2 = source page
        url_file = path.with_suffix(".url")
        source_url = source_page = None
        if url_file.exists():
            lines = url_file.read_text(encoding="utf-8").strip().splitlines()
            source_url = lines[0].strip() if lines else None
            source_page = lines[1].strip() if len(lines) > 1 else None

        print(f"\n[watch] {path.name}")
        if not source_url:
            try:
                source_url  = input("  Source URL (Enter to skip): ").strip() or None
                source_page = input("  Source page (Enter to skip): ").strip() or None
            except EOFError:
                pass

        self.process_fn(str(path), self.csv_path, source_url=source_url, source_page=source_page)


def watch_directories(dirs: list[str], csv_path: str, process_fn: Callable) -> None:
    observer = Observer()
    for d in dirs:
        observer.schedule(_ImageHandler(process_fn, csv_path), d, recursive=False)
        print(f"Watching: {d}")
    print(f"CSV log:  {csv_path}")
    print("Tip: <image>.url companion file skips the URL prompt.")
    print("Ctrl+C to stop.\n")
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()


def watch_directory(watch_dir: str, csv_path: str, process_fn: Callable) -> None:
    watch_directories([watch_dir], csv_path, process_fn)
