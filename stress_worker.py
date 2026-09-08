from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import queue
import resource
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps


@dataclass
class Result:
    completed: int = 0
    failures: int = 0
    input_bytes: int = 0
    output_bytes: int = 0


def max_rss_mib() -> float:
    # macOS reports bytes; Linux reports KiB.
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return rss / divisor


def current_rss_mib() -> float:
    """Live RSS, unlike ru_maxrss which only records the high-water mark."""
    if sys.platform == "darwin":
        import subprocess

        output = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(os.getpid())], text=True
        )
        return int(output.strip() or "0") / 1024
    with open(f"/proc/{os.getpid()}/status", encoding="utf-8") as status:
        for line in status:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def make_synthetic_jpeg(width: int, height: int) -> bytes:
    raw = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 3
            raw[offset] = (x * 13 + y * 3) % 256
            raw[offset + 1] = (x * 5 + y * 17) % 256
            raw[offset + 2] = (x * 7 + y * 11) % 256

    with Image.frombytes("RGB", (width, height), bytes(raw)) as image:
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=92)
        return output.getvalue()


def compress_camera_image_bytes(
    original: bytes,
    *,
    target_bytes: int = 450_000,
    max_dimension: int = 1280,
) -> bytes:
    """Copy of the affected app's Pillow compression path."""
    try:
        with Image.open(io.BytesIO(original)) as image:
            image = ImageOps.exif_transpose(image)

            if image.mode != "RGB":
                image = image.convert("RGB")

            if max(image.size) > max_dimension:
                scale = max_dimension / max(image.size)
                new_size = (
                    max(1, int(image.width * scale)),
                    max(1, int(image.height * scale)),
                )
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            for quality in (72, 60):
                output = io.BytesIO()
                image.save(
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
        # Preserve the original app's fallback behavior.
        return original


def emit(event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "monotonic_seconds": round(time.monotonic(), 3),
                "pid": os.getpid(),
                "max_rss_mib": round(max_rss_mib(), 1),
                "current_rss_mib": round(current_rss_mib(), 1),
                **fields,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def run(args: argparse.Namespace) -> int:
    if args.input:
        source = Path(args.input).read_bytes()
        source_name = str(Path(args.input))
    else:
        source = make_synthetic_jpeg(args.width, args.height)
        source_name = f"synthetic-{args.width}x{args.height}"

    work_queue: queue.Queue[tuple[int, int, bytes] | None] = queue.Queue(
        maxsize=args.queue_size
    )
    result = Result()
    result_lock = threading.Lock()
    producers_ready = threading.Barrier(args.submissions)
    started = time.monotonic()

    emit(
        "start",
        pillow_version=Image.__version__,
        python_version=sys.version,
        source=source_name,
        source_bytes=len(source),
        workers=args.workers,
        submissions=args.submissions,
        rounds=args.rounds,
        queue_size=args.queue_size,
    )

    def worker() -> None:
        while True:
            item = work_queue.get()
            try:
                if item is None:
                    return
                submission, round_number, photo = item
                compressed = compress_camera_image_bytes(photo)
                # Simulate consuming the upload body without external API traffic.
                hashlib.sha256(compressed).digest()
                with result_lock:
                    result.completed += 1
                    result.input_bytes += len(photo)
                    result.output_bytes += len(compressed)
            except BaseException as exc:
                with result_lock:
                    result.failures += 1
                emit(
                    "task_failure",
                    submission=submission,
                    round=round_number,
                    error=repr(exc),
                )
            finally:
                work_queue.task_done()

    workers = [
        threading.Thread(target=worker, name=f"pillow-worker-{index + 1}", daemon=True)
        for index in range(args.workers)
    ]
    for thread in workers:
        thread.start()

    def producer(submission: int) -> None:
        producers_ready.wait()
        for round_number in range(args.rounds):
            # Each camera_input payload is a distinct buffer. bytes(existing_bytes)
            # is identity-preserving in CPython, so copy through bytearray.
            work_queue.put((submission, round_number, bytes(bytearray(source))))

    producers = [
        threading.Thread(
            target=producer,
            args=(index + 1,),
            name=f"submission-{index + 1}",
            daemon=True,
        )
        for index in range(args.submissions)
    ]
    for thread in producers:
        thread.start()

    last_report = 0
    total = args.submissions * args.rounds
    while any(thread.is_alive() for thread in producers) or result.completed + result.failures < total:
        for thread in producers:
            thread.join(timeout=0.05)
        current = result.completed + result.failures
        if current - last_report >= args.report_every:
            emit("progress", completed=result.completed, failures=result.failures, total=total)
            last_report = current

    work_queue.join()
    for _ in workers:
        work_queue.put(None)
    for thread in workers:
        thread.join()

    elapsed = time.monotonic() - started
    emit(
        "complete",
        **asdict(result),
        total=total,
        elapsed_seconds=round(elapsed, 3),
        tasks_per_second=round(total / elapsed, 2),
    )
    import gc

    gc.collect()
    emit("after_gc", completed=result.completed, failures=result.failures, total=total)
    return 1 if result.failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--submissions", type=int, default=9)
    parser.add_argument("--rounds", type=int, default=100)
    parser.add_argument("--queue-size", type=int, default=200)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--input", type=str)
    parser.add_argument("--report-every", type=int, default=25)
    args = parser.parse_args()

    for name in ("workers", "submissions", "rounds", "queue_size", "width", "height"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
