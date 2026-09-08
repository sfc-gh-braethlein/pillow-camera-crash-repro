"""Classroom submit page: in-process copy of Journey-to-quantum-world-TA.

Pillow runs on the Streamlit process's three Drive worker threads, matching
the historical app. Google Drive/Sheets I/O is stubbed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from classroom_pipeline import (
    DrivePhotoUploadPool,
    SheetWriteBatcher,
    submission_state,
)
from util import current_rss_mib, upload_manager_totals

RESPONSE_MIN_CHARS = 20


@st.cache_resource(show_spinner=False)
def drive_photo_upload_pool() -> DrivePhotoUploadPool:
    return DrivePhotoUploadPool()


@st.cache_resource(show_spinner=False)
def shared_submission_state() -> dict:
    return submission_state()


@st.cache_resource(show_spinner=False)
def sheet_write_batcher() -> SheetWriteBatcher:
    return SheetWriteBatcher(shared_submission_state())


def upload_attendance_photo(camera_file, student_id: str, submitted_at: datetime) -> str:
    filename = f"{student_id}_{submitted_at.strftime('%H%M%S')}.jpg"
    return drive_photo_upload_pool().submit(
        photo_bytes=camera_file.getvalue(),
        folder_id="stub-folder",
        filename=filename,
    )


st.set_page_config(page_title="Classroom submit", layout="centered")
st.title("Classroom submit (in-process copy)")
st.caption(
    "Copied from olr-or/Journey-to-quantum-world-TA: 720p camera_input, "
    "getvalue() into a 3-thread DrivePhotoUploadPool, Pillow compress in those "
    "threads, then a batched sheet writer. Drive/Sheets HTTP is stubbed; the "
    "thread waits and in-process Pillow path are the same."
)

ctx = get_script_run_ctx()
student_id = ctx.session_id[:8] if ctx is not None else "unknown"

if st.session_state.get("attendance_submitted"):
    st.success("Attendance submitted")
    st.markdown("Photo captured: submitted")
    rss = current_rss_mib()
    file_count, total_bytes, _ = upload_manager_totals()
    pool = drive_photo_upload_pool()
    cols = st.columns(4)
    cols[0].metric("Process RSS MiB", f"{rss:.1f}")
    cols[1].metric("Pool completed", pool.completed)
    cols[2].metric("Upload files", file_count)
    cols[3].metric("Upload total bytes", f"{total_bytes:,}")
    st.stop()

photo = st.camera_input(
    "Take a photo of the ongoing lecture",
    resolution="720p",
    key=f"camera_{student_id}",
)

class_response = st.text_area(
    "Class response",
    placeholder="Briefly describe what you expect to learn.",
    height=140,
    max_chars=1000,
    key=f"response_{student_id}",
)
st.caption(f"Please write at least {RESPONSE_MIN_CHARS} characters.")

if st.button("Submit Attendance", type="primary", use_container_width=True):
    if photo is None:
        st.error("Please take a class photo before submitting.")
        st.stop()
    if len(class_response.strip()) < RESPONSE_MIN_CHARS:
        st.error(
            f"Please write at least {RESPONSE_MIN_CHARS} characters "
            "in the Class Response field."
        )
        st.stop()

    submitted_at = datetime.now(timezone.utc)
    try:
        with st.spinner("Saving your attendance record..."):
            photo_url = upload_attendance_photo(photo, student_id, submitted_at)
            sheet_write_batcher().submit(
                kind="attendance",
                sheet_name=submitted_at.date().isoformat(),
                row=[student_id, submitted_at.isoformat(), photo_url],
                state_key=(student_id, submitted_at.date().isoformat()),
            )
    except Exception as exc:
        st.error("An error occurred while saving your attendance.")
        st.exception(exc)
        st.stop()

    st.session_state.attendance_submitted = True
    st.rerun()

rss = current_rss_mib()
file_count, total_bytes, _ = upload_manager_totals()
pool = drive_photo_upload_pool()
cols = st.columns(4)
cols[0].metric("Process RSS MiB", f"{rss:.1f}")
cols[1].metric("This photo bytes", f"{0 if photo is None else photo.size:,}")
cols[2].metric("Pool completed", pool.completed)
cols[3].metric("Upload total bytes", f"{total_bytes:,}")
st.markdown(f"Session id: `{student_id}`")
st.markdown("Photo captured: yes" if photo is not None else "Photo captured: no")
st.markdown(f"Pool queue: {pool._queue.qsize()}")
