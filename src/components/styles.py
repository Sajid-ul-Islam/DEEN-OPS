import os
import streamlit as st

from src.config.constants import PROJECT_ROOT


def _inject_theme_override():
    """Inject CSS override based on manual theme selection."""
    theme = st.session_state.get("manual_theme", "system")
    if theme == "system":
        return
    if theme == "dark":
        st.markdown(
            "<style>html{--text-color:#f8fafc;--background-color:#0f172a;--secondary-background-color:#1e293b;}"
            "[data-testid='stSidebar']{background:linear-gradient(180deg,#090f1f 0%,#050811 100%)!important; border-right: 1px solid rgba(255,255,255,0.08)!important;}</style>",
            unsafe_allow_html=True,
        )
    elif theme == "light":
        st.markdown(
            "<style>html{--text-color:#0f172a;--background-color:#f8fafc;--secondary-background-color:#ffffff;}"
            "[data-testid='stSidebar']{background:linear-gradient(180deg,#ffffff 0%,#f1f5f9 100%)!important; border-right: 1px solid rgba(0,0,0,0.08)!important;}"
            "[data-testid='stSidebar'] *{color:#0f172a!important;}"
            "[data-testid='stSidebar'] button{color:#1e293b!important;background:rgba(0,0,0,0.03)!important;border-color:rgba(0,0,0,0.1)!important;}"
            "[data-testid='stSidebar'] button:hover{background:rgba(0,0,0,0.06)!important;border-color:rgba(0,0,0,0.2)!important;color:#000!important;}"
            "[data-testid='stSidebar'] button[kind='primary']{color:#fff!important;}"
            ".sidebar-logo-text{-webkit-text-fill-color:#0f172a!important;color:#0f172a!important;}</style>",
            unsafe_allow_html=True,
        )


def inject_base_styles():
    css_path = os.path.join(PROJECT_ROOT, "assets", "styles.css")
    _inject_theme_override()
    
    if os.path.exists(css_path):
        # Get the file's last modified timestamp to act as a cache-buster
        file_version = int(os.path.getmtime(css_path))
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        
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
