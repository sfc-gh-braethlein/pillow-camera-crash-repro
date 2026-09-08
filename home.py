import streamlit as st

st.set_page_config(page_title="Crash reproducer", page_icon="🔬")
st.title("Community Cloud camera / Pillow crash reproducer")
st.write(
    "Tests for the classroom-app crashes (native exits 139/134). "
    "**Camera input** holds 720p JPEGs without Pillow. "
    "**Pillow workers** runs the compress path in a child process. "
    "**Classroom submit** copies the historical in-process 3-thread "
    "DrivePhotoUploadPool plus sheet batcher from Journey-to-quantum-world-TA "
    "(Drive/Sheets HTTP stubbed)."
)
st.page_link("camera_sessions.py", label="Open camera input test")
st.page_link("pillow_stress.py", label="Open Pillow worker test")
st.page_link("classroom_submit.py", label="Open classroom submit test")
st.caption("Pinned to Streamlit 1.63.0, Pillow 12.3.0, Python 3.14 to match the affected app.")
