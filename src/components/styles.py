import os
import streamlit as st


def inject_base_styles():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    css_path = os.path.join(base_dir, "assets", "styles.css")
    
    if os.path.exists(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        st.markdown(f"<style>\n{css_content}\n</style>", unsafe_allow_html=True)
