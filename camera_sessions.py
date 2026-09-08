"""Camera-input-only page for multi-session browser tests.

Does not open the JPEG with Pillow. Reports process RSS and the in-memory
upload manager totals so we can isolate st.camera_input from the classroom
Pillow worker pool.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from util import current_rss_mib, upload_manager_totals

METRICS_PATH = Path(__file__).with_name("camera_session_metrics.json")
_WRITE_LOCK = threading.Lock()


def write_metrics(payload: dict) -> None:
    with _WRITE_LOCK:
        METRICS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


st.set_page_config(page_title="Camera session test", layout="centered")
st.title("st.camera_input session test")
st.caption(
    "720p capture only. The JPEG stays in Streamlit's MemoryUploadedFileManager; "
    "this page does not decode it with Pillow."
)

ctx = get_script_run_ctx()
session_id = ctx.session_id if ctx is not None else "unknown"

photo = st.camera_input("Classroom camera", resolution="720p", key="classroom_camera")

photo_bytes = 0 if photo is None else photo.size
file_count, total_bytes, upload_sessions = upload_manager_totals()
rss = current_rss_mib()

metrics = {
    "pid": os.getpid(),
    "python": sys.version.split()[0],
    "rss_mib": round(rss, 1),
    "session_id": session_id,
    "photo_bytes": photo_bytes,
    "upload_file_count": file_count,
    "upload_total_bytes": total_bytes,
    "upload_sessions": upload_sessions,
}
write_metrics(metrics)

columns = st.columns(4)
columns[0].metric("Process RSS MiB", f"{rss:.1f}")
columns[1].metric("This photo bytes", f"{photo_bytes:,}")
columns[2].metric("Upload files", file_count)
columns[3].metric("Upload total bytes", f"{total_bytes:,}")

st.markdown(f"Session id: `{session_id}`")
if photo is None:
    st.markdown("Photo captured: no")
else:
    st.markdown("Photo captured: yes")
    st.markdown(f"Filename: `{photo.name}`")
