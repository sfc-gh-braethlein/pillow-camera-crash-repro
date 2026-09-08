import streamlit as st

st.set_page_config(page_title="Crash reproducer", page_icon="🔬")
st.title("Community Cloud camera / Pillow crash reproducer")
st.write(
    "Two isolated tests for the classroom-app crashes (native exits 139/134). "
    "Use **Camera input** to hold 720p JPEGs in Streamlit's upload manager "
    "without Pillow. Use **Pillow workers** to run the historical compress "
    "path (EXIF transpose, LANCZOS, progressive JPEG) in a child process."
)
st.page_link("camera_sessions.py", label="Open camera input test")
st.page_link("pillow_stress.py", label="Open Pillow worker test")
st.caption("Pinned to Streamlit 1.63.0, Pillow 12.3.0, Python 3.14 to match the affected app.")
