import os
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from app_modules.ui_config import APP_TITLE, APP_VERSION


def inject_base_styles():
    st.markdown(
        f"""
        <style>
        :root {{
            --primary: var(--primary-color, #1d4ed8);
            --surface: var(--background-color, #f8fafc);
            --border: rgba(128, 128, 128, 0.2);
            --text-muted: var(--text-color, #64748b);
            --step-surface: var(--background-color, #ffffff);
            --step-text: var(--text-color, #0f172a);
            --step-active-bg: var(--secondary-background-color, rgba(29, 78, 216, 0.05));
            --action-surface: var(--secondary-background-color, rgba(255, 255, 255, 0.96));
            --card-shadow: rgba(0, 0, 0, 0.1);
        }}
        
        .hub-footer {{
            position: fixed;
            bottom: 0;
            left: 0;
            width: 100%;
            background: var(--background-color);
            color: var(--text-color);
            padding: 12px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            border-top: 1px solid rgba(128, 128, 128, 0.2);
            z-index: 999;
        }}
        .hub-footer a {{
            color: inherit;
            text-decoration: none;
            font-weight: 500;
        }}
        /* Extra padding for main content so it doesn't get hidden by fixed footer */
        .main .block-container {{
            padding-bottom: 80px !important;
        }}
        .deen-logo-small {{
            vertical-align: middle;
            margin-right: 6px;
            border-radius: 4px;
        }}
        .hub-title-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: linear-gradient(90deg, rgba(29, 78, 216, 0.03) 0%, rgba(29, 78, 216, 0) 100%);
            border-left: 4px solid #1d4ed8;
            border-bottom: 1px solid var(--border);
            padding: 8px 16px;
            margin-bottom: 0px;
            border-radius: 0 4px 4px 0;
        }}
        /* Remove the top gap without touching the sidebar toggle */
        .main .block-container {{
            padding-top: 0 !important;
            margin-top: -1.75rem !important;
            padding-bottom: 80px !important;
        }}
        .hub-title {{
            margin: 0;
            font-weight: 700;
        }}
        .hub-subtitle {{
            margin: 0;
            color: var(--text-muted);
            font-size: 0.95rem;
        }}
        .hub-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px 16px;
            margin-bottom: 4px;
            box-shadow: 0 4px 12px var(--card-shadow);
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        .hub-welcome-banner {{
            background-color: transparent;
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 15px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
        }}
        .hub-welcome-banner a, .hub-welcome-banner b {{
            color: inherit !important;
        }}
        .hub-welcome-status {{
            text-align: right;
            background: rgba(29, 78, 216, 0.04);
            padding: 12px 16px;
            border-radius: 8px;
            border: 1px solid rgba(29, 78, 216, 0.1);
        }}
        .hub-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 32px var(--card-shadow);
            border-color: var(--primary);
        }}
        
        /* 3. Action Glow for success/primary steps */
        @keyframes success-pulse {{
            0% {{ box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }}
            70% {{ box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }}
            100% {{ box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }}
        }}
        div[data-testid="stDownloadButton"] button {{
            animation: success-pulse 2s infinite;
            border: 1px solid #10b981 !important;
            transition: all 0.2s ease !important;
        }}
        div[data-testid="stDownloadButton"] button:hover {{
            transform: scale(1.02);
            background: #059669 !important;
            color: white !important;
        }}
        
        /* Global button hover scaling */
        button[kind="secondary"]:hover, button[kind="primary"]:hover {{
            transform: scale(1.01);
            transition: all 0.2s ease !important;
        }}
        
        /* Premium Tab Styling */
        div[data-testid="stTab"] button {{
            font-size: 0.9rem !important;
            font-weight: 600 !important;
            color: #64748b !important;
            transition: all 0.3s ease !important;
            border: none !important;
            background: transparent !important;
            padding: 10px 20px !important;
        }}
        div[data-testid="stTab"] button:hover {{
            color: #1d4ed8 !important;
            background: rgba(29, 78, 216, 0.04) !important;
            border-radius: 8px 8px 0 0 !important;
        }}
        div[data-testid="stTab"] button[aria-selected="true"] {{
            color: #1d4ed8 !important;
            border-bottom: 2px solid #1d4ed8 !important;
        }}
        
        @media (max-width: 900px) {{
            .hub-welcome-banner {{
                flex-direction: column;
                align-items: flex-start;
            }}
            .hub-welcome-status {{
                text-align: left;
                width: 100%;
                margin-top: 4px;
            }}
            .block-container {{
                padding-left: 0.5rem !important;
                padding-right: 0.5rem !important;
                margin-top: -2.5rem !important;
            }}
            .hub-title {{
                font-size: 1.2rem !important;
                line-height: 1.2;
            }}
            .hub-subtitle {{
                font-size: 0.8rem !important;
            }}
            .hub-card {{
                padding: 10px;
                border-radius: 8px;
            }}
            /* Metric Font Scaling for Small Screens */
            div[data-testid="stMetricValue"] {{
                font-size: 1.2rem !important;
            }}
            div[data-testid="stMetricLabel"] {{
                font-size: 0.75rem !important;
            }}
            /* Compact Tabs on Mobile */
            div[data-testid="stTab"] button {{
                padding: 8px 12px !important;
                font-size: 0.8rem !important;
            }}
        }}
        
        /* Hide Plotly legends on mobile and small screens */
        @media (max-width: 900px) {{
            .js-plotly-plot .legend, .js-plotly-plot .legendtoggle, .js-plotly-plot .legend-bg, .js-plotly-plot .legend-layer {{
                display: none !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_branding():
    """Elegant sidebar branding to save main screen space."""
    logo_src = "https://logo.clearbit.com/deencommerce.com"
    try:
        import base64
        import os

        logo_jpg = os.path.join("assets", "deen_logo.jpg")
        if os.path.exists(logo_jpg):
            with open(logo_jpg, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            logo_src = f"data:image/jpeg;base64,{b64}"
    except:
        pass

    # Sidebar branding now only shows the logo if requested, 
    # but the user requested removing the header text entirely.
    # We'll just leave this as a logo placeholder or remove the div.
    pass


def render_header(right_slot_callback=None):
    """Minimal header with flexible right-hand slots."""
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown(
            f'<h1 class="hub-title" style="margin:0;">{APP_TITLE} <span style="color:#1d4ed8;">{APP_VERSION}</span></h1>',
            unsafe_allow_html=True
        )
    with c2:
        if right_slot_callback:
            right_slot_callback()


def section_card(title: str, help_text: str = ""):
    st.markdown(
        f"""
        <div class="hub-card">
          <div style="font-weight:600;">{title}</div>
          <div style="color:var(--text-muted); margin-top:4px;">{help_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer():
    """Renders a robust and persistent branding footer."""
    logo_src = "https://logo.clearbit.com/deencommerce.com"
    try:
        import base64
        import os
        logo_jpg = os.path.join("assets", "deen_logo.jpg")
        if os.path.exists(logo_jpg):
            with open(logo_jpg, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            logo_src = f"data:image/jpeg;base64,{b64}"
    except:
        pass

    st.markdown(
        f"""
        <div class="hub-footer">
            <div style="width:100%; text-align:center;">
                <span style="margin-right:12px;">© 2026 <a href="https://github.com/saajiidi" target="_blank">Sajid Islam</a>. All rights reserved.</span>
                <span style="margin:0 12px; opacity:0.5;">|</span>
                <a href="https://deencommerce.com/" target="_blank" style="text-decoration:none;">
                    <img src="{logo_src}" width="20" class="deen-logo-small" onerror="this.style.display='none'">
                    Powered by <b>DEEN Commerce Ltd.</b>
                </a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_file_summary(
    uploaded_file, df: pd.DataFrame | None, required_columns: list[str]
):
    if not uploaded_file:
        st.info("No file uploaded yet.")
        return False

    st.caption(f"File: {uploaded_file.name}")
    if df is None:
        st.warning("Could not read this file.")
        return False

    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", len(df))
    c2.metric("Columns", len(df.columns))
    c3.metric("Required", len(required_columns))

    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        st.error(f"Missing required columns: {', '.join(missing)}")
        return False
    st.success("Required columns check passed.")
    return True


def render_action_bar(
    primary_label: str,
    primary_key: str,
    secondary_label: str | None = None,
    secondary_key: str | None = None,
):
    if secondary_label and secondary_key:
        c1, c2 = st.columns([2, 1])
        primary_clicked = c1.button(
            primary_label, type="primary", use_container_width=True, key=primary_key
        )
        secondary_clicked = c2.button(
            secondary_label, use_container_width=True, key=secondary_key
        )
    else:
        primary_clicked = st.button(
            primary_label, type="primary", use_container_width=True, key=primary_key
        )
        secondary_clicked = False
    return primary_clicked, secondary_clicked


def render_reset_confirm(label: str, state_key: str, reset_fn):
    """
    Registers a tool's reset function for the unified sidebar.
    Doesn't render anything in the sidebar immediately to avoid duplicates.
    """
    if "registered_resets" not in st.session_state:
        st.session_state.registered_resets = {}

    st.session_state.registered_resets[label] = {"fn": reset_fn, "key": state_key}


def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    output.seek(0)
    return output.read()


def show_last_updated(path: str):
    if not os.path.exists(path):
        return
    updated = datetime.fromtimestamp(os.path.getmtime(path)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    st.caption(f"Last updated: {updated}")


def render_status_toggle(label: str, status_type: str = "info", help_text: str = ""):
    """Renders a status indicator with a color-coded dot."""
    colors = {
        "success": "#15803d",
        "warning": "#b45309",
        "error": "#b91c1c",
        "info": "#1d4ed8",
    }
    color = colors.get(status_type, colors["info"])
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 8px; margin: 10px 0;">
            <div style="width: 10px; height: 10px; border-radius: 50%; background-color: {color};box-shadow: 0 0 6px {color}80;"></div>
            <div style="font-weight: 600; font-size: 0.9rem;">{label}</div>
            {f'<div style="font-size: 0.8rem; color: #64748b;">• {help_text}</div>' if help_text else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )
