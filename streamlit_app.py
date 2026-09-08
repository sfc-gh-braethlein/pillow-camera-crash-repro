import streamlit as st

home = st.Page("home.py", title="Overview", default=True)
camera = st.Page("camera_sessions.py", title="Camera input")
pillow = st.Page("pillow_stress.py", title="Pillow workers")
classroom = st.Page("classroom_submit.py", title="Classroom submit")

st.navigation([home, camera, pillow, classroom]).run()
