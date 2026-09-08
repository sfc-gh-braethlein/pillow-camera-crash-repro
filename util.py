from __future__ import annotations

import os
import subprocess
from pathlib import Path

from streamlit.runtime.runtime import Runtime


def current_rss_mib() -> float:
    statm = Path("/proc/self/statm")
    if statm.exists():
        pages = int(statm.read_text().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    out = subprocess.check_output(
        ["ps", "-o", "rss=", "-p", str(os.getpid())],
        text=True,
    )
    return int(out.strip()) / 1024


def upload_manager_totals() -> tuple[int, int, int]:
    runtime = Runtime.instance()
    manager = runtime.uploaded_file_mgr
    with manager._lock:
        sessions = len(manager.file_storage)
        return manager._file_count, manager._total_bytes, sessions
