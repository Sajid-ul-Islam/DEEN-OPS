import os
import streamlit as st

from src.config.constants import PROJECT_ROOT


@st.cache_data(show_spinner=False)
def _load_css_file(path: str, mtime: float) -> str:
    """Cache the CSS file content to prevent disk I/O on every Streamlit rerun."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def inject_base_styles():
    css_path = os.path.join(PROJECT_ROOT, "assets", "styles.css")
    
    if os.path.exists(css_path):
        # Get the file's last modified timestamp to act as a cache-buster
        file_version = os.path.getmtime(css_path)
        css_content = _load_css_file(css_path, file_version)
        
        # Injecting additional UI-UX refinements for the Terminal experience
        extra_styles = """
        /* Terminal Glow Effects */
        .critical-glow {
            box-shadow: 0 0 15px rgba(239, 68, 68, 0.4);
            animation: pulse-red 2s infinite;
        }
        @keyframes pulse-red {
            0% { box-shadow: 0 0 5px rgba(239, 68, 68, 0.4); }
            50% { box-shadow: 0 0 20px rgba(239, 68, 68, 0.6); }
            100% { box-shadow: 0 0 5px rgba(239, 68, 68, 0.4); }
        }
        
        /* Modern Scrollbars for Terminal Feel */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.05); }
        ::-webkit-scrollbar-thumb { background: rgba(99, 102, 241, 0.3); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(99, 102, 241, 0.5); }

        /* Glassmorphism Refinement */
        .stDataFrame {
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            overflow: hidden;
        }
        """
        st.markdown(f"<style data-version='{file_version}'>\n{css_content}\n{extra_styles}\n</style>", unsafe_allow_html=True)
