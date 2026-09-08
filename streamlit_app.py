import streamlit as st

home = st.Page("home.py", title="Overview", default=True)
camera = st.Page("camera_sessions.py", title="Camera input")
pillow = st.Page("pillow_stress.py", title="Pillow workers")

st.navigation([home, camera, pillow]).run()
