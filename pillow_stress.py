from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import streamlit as st
from PIL import Image


class StressProcess:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.log_path: Path | None = None
        self.log_file = None
        self.lock = threading.Lock()

    def start(self, command: list[str]) -> None:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError("A stress process is already running.")

            fd, raw_path = tempfile.mkstemp(prefix="pillow-stress-", suffix=".jsonl")
            os.close(fd)
            self.log_path = Path(raw_path)
            self.log_file = self.log_path.open("w", encoding="utf-8")
            self.process = subprocess.Popen(
                command,
                stdout=self.log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )

    def stop(self) -> None:
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                return
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self._close_log()

    def status(self) -> tuple[str, int | None]:
        with self.lock:
            if self.process is None:
                return "not started", None
            returncode = self.process.poll()
            if returncode is None:
                return "running", None
            self._close_log()
            if returncode == 0:
                return "completed", returncode
            if returncode < 0:
                return f"crashed with signal {-returncode}", returncode
            return f"failed with exit code {returncode}", returncode

    def logs(self) -> str:
        with self.lock:
            if self.log_file is not None:
                self.log_file.flush()
            if self.log_path is None or not self.log_path.exists():
                return ""
            return self.log_path.read_text(encoding="utf-8", errors="replace")

    def _close_log(self) -> None:
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None


@st.cache_resource
def stress_process() -> StressProcess:
    return StressProcess()


def parse_events(logs: str) -> list[dict]:
    events = []
    for line in logs.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"event": "raw", "message": line})
    return events


st.set_page_config(page_title="Pillow crash reproducer", page_icon="🔬", layout="wide")
st.title("Pillow concurrent JPEG crash reproducer")
st.caption(
    "Recreates the image pipeline used by the affected classroom app: "
    "Pillow 12.3.0, three worker threads, EXIF transpose, LANCZOS resize, "
    "and optimized progressive JPEG output."
)

with st.expander("Why the test runs in a child process", expanded=False):
    st.write(
        "The production failures were native exits 139 (SIGSEGV) and 134 "
        "(SIGABRT), not Python exceptions. A child process preserves those "
        "signals while keeping this UI available to report the result. It runs "
        "the same Pillow operations and thread/queue topology."
    )

left, right = st.columns([1, 1])
with left:
    st.subheader("Workload")
    preset = st.selectbox(
        "Preset",
        ("Historical shape", "Sustained", "High pressure", "Custom"),
    )
    presets = {
        "Historical shape": (3, 9, 25),
        "Sustained": (3, 9, 250),
        "High pressure": (6, 32, 250),
    }
    default_workers, default_submissions, default_rounds = presets.get(
        preset, (3, 9, 100)
    )
    workers = st.number_input(
        "Pillow worker threads", 1, 32, default_workers, disabled=preset != "Custom"
    )
    submissions = st.number_input(
        "Simultaneous submissions",
        1,
        128,
        default_submissions,
        disabled=preset != "Custom",
    )
    rounds = st.number_input(
        "Compression rounds per submission",
        1,
        10_000,
        default_rounds,
        disabled=preset != "Custom",
    )

with right:
    st.subheader("Input")
    source = st.radio(
        "JPEG source",
        ("Synthetic 1280×720", "Camera", "Upload"),
        horizontal=True,
    )
    uploaded = None
    if source == "Camera":
        uploaded = st.camera_input("Take a test photo", resolution="720p")
    elif source == "Upload":
        uploaded = st.file_uploader("Upload JPEG", type=("jpg", "jpeg"))

    if uploaded is not None:
        try:
            with Image.open(uploaded) as image:
                st.write(
                    f"Input: {image.width}×{image.height}, {uploaded.size:,} bytes"
                )
        except Exception as exc:
            st.error(f"Invalid image: {exc}")

controller = stress_process()
start_column, stop_column, refresh_column = st.columns(3)

with start_column:
    start = st.button("Start stress test", type="primary", use_container_width=True)
with stop_column:
    stop = st.button("Stop", use_container_width=True)
with refresh_column:
    st.button("Refresh status", use_container_width=True)

if start:
    input_path = None
    if uploaded is not None:
        suffix = Path(uploaded.name).suffix or ".jpg"
        with tempfile.NamedTemporaryFile(
            prefix="pillow-input-", suffix=suffix, delete=False
        ) as image_file:
            image_file.write(uploaded.getvalue())
            input_path = image_file.name

    command = [
        sys.executable,
        str(Path(__file__).with_name("stress_worker.py")),
        "--workers",
        str(workers),
        "--submissions",
        str(submissions),
        "--rounds",
        str(rounds),
    ]
    if input_path is not None:
        command.extend(("--input", input_path))

    try:
        controller.start(command)
        st.success("Stress process started. Use Refresh status to monitor it.")
    except RuntimeError as exc:
        st.warning(str(exc))

if stop:
    controller.stop()

status, returncode = controller.status()
events = parse_events(controller.logs())

st.subheader("Result")
status_columns = st.columns(4)
status_columns[0].metric("Status", status)
status_columns[1].metric("Child return code", "—" if returncode is None else returncode)
status_columns[2].metric("Pillow", Image.__version__)
status_columns[3].metric("Python", sys.version.split()[0])

if returncode in (-signal.SIGSEGV, 139):
    st.error("Reproduced SIGSEGV (production exit status 139).")
elif returncode in (-signal.SIGABRT, 134):
    st.error("Reproduced SIGABRT (production exit status 134).")
elif returncode == 0:
    st.success("Run completed without a native crash.")

if events:
    latest = events[-1]
    progress = latest.get("completed")
    total = latest.get("total")
    if isinstance(progress, int) and isinstance(total, int) and total:
        st.progress(min(progress / total, 1.0), text=f"{progress:,} / {total:,} tasks")

    rows = [
        {
            "event": event.get("event"),
            "completed": event.get("completed"),
            "failures": event.get("failures"),
            "current_rss_mib": event.get("current_rss_mib"),
            "max_rss_mib": event.get("max_rss_mib"),
            "elapsed_seconds": event.get("elapsed_seconds"),
        }
        for event in events
        if event.get("event") != "raw"
    ]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)

with st.expander("Raw child-process log"):
    st.code(controller.logs() or "No output yet.", language="json")

st.warning(
    "Run one test at a time. The High pressure preset is intentionally CPU- and "
    "memory-intensive. Start with Historical shape."
)
