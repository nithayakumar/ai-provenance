import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}


class _ImageHandler(FileSystemEventHandler):
    def __init__(self, process_fn, csv_path: str):
        self.process_fn = process_fn
        self.csv_path = csv_path
        self._seen = set()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            return
        if path.name.startswith(".") or path.name.endswith(".provenance.json"):
            return
        if str(path) in self._seen:
            return
        self._seen.add(str(path))

        # Wait briefly for file to finish writing
        time.sleep(1.0)
        if not path.exists():
            return

        # Check for companion .url hint file: <stem>.url
        # Line 1 = direct image URL, Line 2 (optional) = source page URL
        url_file = path.with_suffix(".url")
        source_url = source_page = None
        if url_file.exists():
            lines = url_file.read_text(encoding="utf-8").strip().splitlines()
            source_url = lines[0].strip() if lines else None
            source_page = lines[1].strip() if len(lines) > 1 else None

        print(f"\n[watcher] New image detected: {path.name}")
        if source_url:
            print(f"          URL (from .url file): {source_url}")
        else:
            try:
                source_url = input("  Source URL (Enter to skip): ").strip() or None
                source_page = input("  Page where found (Enter to skip): ").strip() or None
            except EOFError:
                pass  # non-interactive environment

        self.process_fn(str(path), self.csv_path, source_url=source_url, source_page=source_page)


def watch_directory(watch_dir: str, csv_path: str, process_fn) -> None:
    handler = _ImageHandler(process_fn, csv_path)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    print(f"Watching: {watch_dir}")
    print(f"CSV log:  {csv_path}")
    print("Tip: drop a '<image_stem>.url' file alongside an image to skip the URL prompt.")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
