import os
import base64
import streamlit as st

from src.config.constants import PROJECT_ROOT


def render_bike_animation():
    """
    Renders a full-screen right-to-left overlay animation of a delivery bike.
    This is extracted to a separate file to ensure it can be maintained easily.
    """
    # Load local bike image
    bike_uri = "https://cdn-icons-png.flaticon.com/512/2830/2830305.png"  # fallback

    bike_path = os.path.join(PROJECT_ROOT, "assets", "bike.png")

    if os.path.exists(bike_path):
        with open(bike_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
            bike_uri = f"data:image/png;base64,{encoded}"

    st.markdown(
        f"""
    <div class="full-screen-bike">
        <img src="{bike_uri}" class="bike-img">
        <div class="smoke-trail">
            <div class="smoke"></div>
            <div class="smoke"></div>
            <div class="smoke"></div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )
