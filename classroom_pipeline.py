"""In-process attendance photo pipeline copied from Journey-to-quantum-world-TA.

Drive and Sheets HTTP calls are stubbed so this can run without secrets. The
thread topology, queue, blocking waits, and Pillow compress path match the
historical classroom app (commit ef42697).
"""

from __future__ import annotations

import hashlib
import io
import queue
import threading
import time as time_module

from PIL import Image, ImageOps

PHOTO_UPLOAD_WORKERS = 3
PHOTO_UPLOAD_TIMEOUT_SECONDS = 120
DRIVE_STUB_SECONDS = 0.15
SHEET_STUB_SECONDS = 0.05


def compress_camera_image_bytes(
    original: bytes,
    *,
    target_bytes: int = 450_000,
    max_dimension: int = 1280,
) -> bytes:
    """Recompress a 720p classroom photo with bounded CPU/RAM usage."""
    try:
        with Image.open(io.BytesIO(original)) as img:
            img = ImageOps.exif_transpose(img)

            if img.mode != "RGB":
                img = img.convert("RGB")

            if max(img.size) > max_dimension:
                scale = max_dimension / max(img.size)
                new_size = (
                    max(1, int(img.width * scale)),
                    max(1, int(img.height * scale)),
                )
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            # Two passes instead of five: less CPU during a submission burst.
            for quality in (72, 60):
                output = io.BytesIO()
                img.save(
                    output,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                    subsampling="4:2:0",
                )
                compressed = output.getvalue()
                if len(compressed) <= target_bytes:
                    return compressed

            return compressed

    except Exception:
        # 720p input is already reasonably small, so fallback is safe.
        return original


def stub_drive_upload(compressed_photo: bytes, filename: str) -> str:
    time_module.sleep(DRIVE_STUB_SECONDS)
    digest = hashlib.sha256(compressed_photo).hexdigest()[:12]
    return f"https://example.invalid/file/{digest}/{filename}"


class DrivePhotoUploadPool:
    """Serialize a large burst into a small, fixed number of Drive workers."""

    def __init__(self, workers: int = PHOTO_UPLOAD_WORKERS) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=200)
        self._threads: list[threading.Thread] = []
        self.completed = 0
        self.failures = 0
        self.lock = threading.Lock()

        for index in range(workers):
            thread = threading.Thread(
                target=self._worker,
                name=f"drive-photo-uploader-{index + 1}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def submit(self, *, photo_bytes: bytes, folder_id: str, filename: str) -> str:
        item = {
            "photo_bytes": photo_bytes,
            "folder_id": folder_id,
            "filename": filename,
            "done": threading.Event(),
            "result": None,
            "error": None,
        }

        try:
            self._queue.put(item, timeout=5)
        except queue.Full as exc:
            raise TimeoutError(
                "The photo upload queue is full. Please try submitting again."
            ) from exc

        if not item["done"].wait(timeout=PHOTO_UPLOAD_TIMEOUT_SECONDS):
            raise TimeoutError(
                "Photo upload is taking too long. Please try again in a moment."
            )

        if item["error"] is not None:
            raise item["error"]

        return str(item["result"])

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                compressed_photo = compress_camera_image_bytes(item["photo_bytes"])
                item["result"] = stub_drive_upload(
                    compressed_photo, item["filename"]
                )
                with self.lock:
                    self.completed += 1
            except Exception as exc:
                item["error"] = exc
                with self.lock:
                    self.failures += 1
            finally:
                item["done"].set()
                self._queue.task_done()


def submission_state() -> dict:
    return {
        "lock": threading.Lock(),
        "attendance": set(),
        "reflections": set(),
        "rows": [],
    }


class SheetWriteBatcher:
    """Batch near-simultaneous submissions into a small number of Sheets writes."""

    def __init__(self, state: dict) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._state = state
        self._thread = threading.Thread(
            target=self._worker,
            name="google-sheet-batch-writer",
            daemon=True,
        )
        self._thread.start()

    def submit(self, kind: str, sheet_name: str, row: list, state_key: tuple) -> None:
        item = {
            "kind": kind,
            "sheet_name": sheet_name,
            "row": row,
            "state_key": state_key,
            "done": threading.Event(),
            "error": None,
        }
        bucket = "attendance" if kind == "attendance" else "reflections"

        with self._state["lock"]:
            if state_key in self._state[bucket]:
                raise ValueError(
                    "Attendance has already been submitted for today's class."
                    if kind == "attendance"
                    else "You have already submitted today's class reflection."
                )
            self._state[bucket].add(state_key)

        self._queue.put(item)

        if not item["done"].wait(timeout=45):
            with self._state["lock"]:
                self._state[bucket].discard(state_key)
            raise TimeoutError("Saving took too long. Please try again in a moment.")

        if item["error"] is not None:
            raise item["error"]

    def _worker(self) -> None:
        while True:
            first = self._queue.get()
            batch = [first]
            deadline = time_module.monotonic() + 1.0

            while len(batch) < 100:
                remaining = deadline - time_module.monotonic()
                if remaining <= 0:
                    break
                try:
                    batch.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break

            groups: dict[tuple, list] = {}
            for item in batch:
                groups.setdefault((item["kind"], item["sheet_name"]), []).append(item)

            for (_kind, _sheet_name), items in groups.items():
                try:
                    time_module.sleep(SHEET_STUB_SECONDS)
                    with self._state["lock"]:
                        for item in items:
                            self._state["rows"].append(item["row"])
                except Exception as exc:
                    with self._state["lock"]:
                        for item in items:
                            bucket = (
                                "attendance"
                                if item["kind"] == "attendance"
                                else "reflections"
                            )
                            self._state[bucket].discard(item["state_key"])
                    for item in items:
                        item["error"] = exc
                        item["done"].set()
                else:
                    for item in items:
                        item["done"].set()
