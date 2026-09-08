# Camera / Pillow crash reproducer

Reproduces the Community Cloud classroom-app failure mode from
[forum 122345](https://discuss.streamlit.io/t/community-cloud-app-crashes-with-9-simultaneous-submissions-need-to-support-62-students/122345):
native process exits 139 (SIGSEGV) and 134 (SIGABRT) during concurrent camera
submissions.

## Deploy

1. Open [share.streamlit.io](https://share.streamlit.io) and deploy this repo.
2. Main file: `streamlit_app.py`
3. Python version comes from `runtime.txt` (`python-3.14`).

## What to test

- **Camera input:** open many browser tabs of that page and capture 720p photos together. The page does not decode JPEGs with Pillow.
- **Pillow workers:** start with Historical shape (3 workers, 9 submissions). Optionally feed a camera JPEG. A native crash of the child process is reported in the UI without taking down the script runner immediately.

Pins: Streamlit 1.63.0, Pillow 12.3.0.
