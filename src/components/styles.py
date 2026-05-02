import streamlit as st

from src.config.ui_config import APP_TITLE, APP_VERSION


def inject_base_styles():
    st.markdown(
        f"""
        <style>
        :root {{
            --primary: var(--primary-color, #1d4ed8);
            --primary-glow: rgba(29, 78, 216, 0.1);
            --surface: var(--background-color, #f8fafc);
            --border: rgba(128, 128, 128, 0.15);
            --text-main: var(--text-color, #0f172a);
            --text-muted: #64748b;
            --card-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            --step-surface: var(--background-color, #f8fafc);
            --step-text: var(--text-color, #0f172a);
            --step-active-bg: var(--secondary-background-color, rgba(29, 78, 216, 0.05));
            --action-surface: var(--secondary-background-color, rgba(255, 255, 255, 0.96));
        }}

        /* --- GLOBAL FADE-IN ANIMATION --- */
        @keyframes fadeInScale {{
            0% {{ opacity: 0; transform: translateY(10px) scale(0.995); }}
            100% {{ opacity: 1; transform: translateY(0) scale(1); }}
        }}
        div[role="tabpanel"],
        .main .block-container {{
            animation: fadeInScale 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards;
        }}

        /* Modern Scrollbar */
        ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: #94a3b8; }}

        .stApp {{
            background: var(--background-color);
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
            background: rgba(29, 78, 216, 0.02);
            border-left: 4px solid var(--primary);
            border-bottom: 1px solid var(--border);
            padding: 12px 20px;
            margin-bottom: 24px;
            border-radius: 0 12px 12px 0;
        }}

        /* Remove the top gap without touching the sidebar toggle */
        .main .block-container {{
            padding-top: 0 !important;
            margin-top: -1.75rem !important;
            padding-bottom: 80px !important;
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
            padding: 18px;
            margin-bottom: 16px;
            box-shadow: var(--card-shadow);
            transition: all 0.2s ease;
        }}
        .hub-card:hover {{
            transform: translateY(-2px);
            border-color: var(--primary);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        }}




        /* Hub Title Style (Premium) */
        .hub-title {{
            font-size: 2.2rem !important;
            font-weight: 800 !important;
            letter-spacing: -0.04em !important;
            color: var(--text-main) !important;
            margin: 0px !important;
        }}

        /* Notification Popover Styling */
        div[data-testid="stPopover"] button {{
            background: var(--surface) !important;
            border: 1px solid var(--border) !important;
            border-radius: 20px !important;
            padding: 4px 16px !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
            transition: all 0.3s ease !important;
        }}
        div[data-testid="stPopover"] button:hover {{
            border-color: var(--primary) !important;
            box-shadow: 0 4px 12px var(--primary-glow) !important;
            transform: translateY(-1px);
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

        /* --- RADIO BUTTON TOGGLE ENHANCEMENT --- */
        div[data-testid="stRadio"] > div[role="radiogroup"] {{
            background: rgba(59, 130, 246, 0.08);
            padding: 8px 16px;
            border-radius: 12px;
            border: 1px solid rgba(59, 130, 246, 0.2);
        }}

        /* Chat UI Enhancements (Terminal Theme) */
        .stChatMessage {{
            background-color: rgba(15, 23, 42, 0.85) !important;
            border: 1px solid rgba(59, 130, 246, 0.3) !important;
            border-radius: 8px !important;
            padding: 1.2rem !important;
            margin-bottom: 1rem !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05) !important;
            transition: all 0.3s ease !important;
            color: #e2e8f0 !important;
        }}
        .stChatMessage:hover {{
            transform: translateX(4px);
            border-color: rgba(16, 185, 129, 0.5) !important;
            box-shadow: 0 0 12px rgba(16, 185, 129, 0.1) !important;
        }}
        .stChatMessage [data-testid="stChatMessageContent"],
        .stChatMessage [data-testid="stChatMessageContent"] p,
        .stChatMessage [data-testid="stChatMessageContent"] code {{
            font-family: 'Courier New', Courier, monospace !important;
            font-size: 1rem !important;
            line-height: 1.6 !important;
            color: #e2e8f0 !important;
        }}
        /* Assistant Message Terminal Glow */
        .stChatMessage[data-testid="stChatMessageAssistant"] {{
            border-left: 4px solid #10b981 !important;
            background: linear-gradient(90deg, rgba(16, 185, 129, 0.08) 0%, rgba(15, 23, 42, 0.85) 100%) !important;
        }}
        /* User Message Terminal Style */
        .stChatMessage[data-testid="stChatMessageUser"] {{
            border-left: 4px solid #3b82f6 !important;
            background: linear-gradient(90deg, rgba(59, 130, 246, 0.05) 0%, rgba(15, 23, 42, 0.85) 100%) !important;
        }}

        /* --- MODERN METRIC CARDS --- */
        .metric-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin: 15px 0 25px 0;
            width: 100%;
        }}
        .metric-card {{
            background: linear-gradient(145deg, var(--background-secondary, rgba(255, 255, 255, 0.05)) 0%, rgba(255, 255, 255, 0.01) 100%);
            backdrop-filter: blur(12px);
            border-radius: 16px;
            padding: 22px;
            border: 1px solid rgba(128, 128, 128, 0.15);
            display: flex;
            align-items: center;
            justify-content: space-between;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05);
        }}
        .metric-card::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 2px;
            background: linear-gradient(90deg, transparent, var(--primary, #3b82f6), transparent);
            opacity: 0;
            transition: opacity 0.4s ease;
        }}
        .metric-card:hover {{ 
            transform: translateY(-5px) scale(1.01); 
            border-color: rgba(59, 130, 246, 0.3); 
            box-shadow: 0 12px 30px -5px rgba(59, 130, 246, 0.15); 
        }}
        .metric-card:hover::before {{ opacity: 1; }}
        .metric-content {{ flex: 1; min-width: 0; z-index: 1; }}
        .metric-icon {{
            font-size: 26px; width: 50px; height: 50px;
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.15) 0%, rgba(59, 130, 246, 0.05) 100%);
            border-radius: 14px;
            display: flex; align-items: center; justify-content: center;
            color: #3b82f6; margin-left: 15px; flex-shrink: 0;
            z-index: 1;
            border: 1px solid rgba(59, 130, 246, 0.1);
            transition: all 0.3s ease;
        }}
        .metric-card:hover .metric-icon {{
            transform: rotate(5deg) scale(1.1);
        }}
        .metric-label {{
            color: var(--text-muted, #888); font-size: 0.75rem;
            font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.08em; margin-bottom: 4px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .metric-value {{
            color: var(--text-color, #31333F); font-size: 1.8rem;
            font-weight: 800; letter-spacing: -0.03em;
            line-height: 1.2;
        }}
        .metric-delta {{
            display: inline-flex; align-items: center;
            padding: 3px 8px; border-radius: 6px;
            font-size: 0.7rem; font-weight: 700; margin-top: 10px;
            backdrop-filter: blur(4px);
        }}
        .delta-up {{ background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.2); }}
        .delta-down {{ background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.2); }}
        
        @media (max-width: 1200px) {{ .metric-container {{ grid-template-columns: repeat(2, 1fr); }} }}
        @media (max-width: 600px) {{ .metric-container {{ grid-template-columns: 1fr; }} .metric-value {{ font-size: 1.4rem; }} }}

        /* --- TABLES & CHARTS GLOW EFFECT --- */
        div[data-testid="stPlotlyChart"],
        div[data-testid="stDataFrame"] {{
            background: linear-gradient(145deg, var(--background-secondary, rgba(255, 255, 255, 0.05)) 0%, rgba(255, 255, 255, 0.01) 100%);
            backdrop-filter: blur(12px);
            border-radius: 16px;
            border: 1px solid rgba(128, 128, 128, 0.15);
            padding: 16px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05);
        }}
        div[data-testid="stPlotlyChart"]::before,
        div[data-testid="stDataFrame"]::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 2px;
            background: linear-gradient(90deg, transparent, var(--primary, #3b82f6), transparent);
            opacity: 0;
            transition: opacity 0.4s ease;
        }}
        div[data-testid="stPlotlyChart"]:hover,
        div[data-testid="stDataFrame"]:hover {{ 
            border-color: rgba(59, 130, 246, 0.3); 
            box-shadow: 0 12px 30px -5px rgba(59, 130, 246, 0.15); 
        }}
        div[data-testid="stPlotlyChart"]:hover::before,
        div[data-testid="stDataFrame"]:hover::before {{ opacity: 1; }}

        /* --- COMPONENT STYLES (Header, Banner & Calendar) --- */
        @keyframes pulse {{
            0% {{ transform: scale(1); opacity: 0.9; }}
            50% {{ transform: scale(1.02); opacity: 1; }}
            100% {{ transform: scale(1); opacity: 0.9; }}
        }}
        .app-banner-wrapper {{ position: relative; width: 100%; height: 220px; border-radius: 12px; overflow: hidden; margin-bottom: 24px; box-shadow: var(--card-shadow); }}
        .app-banner-overlay {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: linear-gradient(90deg, rgba(15, 23, 42, 0.8) 0%, rgba(15, 23, 42, 0.1) 100%); display: flex; align-items: center; justify-content: space-between; padding: 0 40px; z-index: 2; }}
        .app-banner-title-area {{ width: auto; z-index: 5; margin-right: 20px; }}
        .app-banner-title {{ color: white; font-size: 1.8rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 4px; }}
        .app-banner-subtitle {{ color: rgba(255, 255, 255, 0.7); font-size: 0.95rem; }}
        .app-banner-clock-area {{ background: rgba(15, 23, 42, 0.4); backdrop-filter: blur(8px); padding: 10px 18px; border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.15); z-index: 10; text-align: right; min-width: max-content; }}
        .banner-controls-shelf {{ margin-top: -85px; margin-bottom: 45px; margin-left: 35px; z-index: 100; position: relative; display: flex; justify-content: flex-start; align-items: center; pointer-events: none; }}
        .banner-controls-shelf > div {{ pointer-events: auto; background: rgba(15, 23, 42, 0.5); backdrop-filter: blur(12px); padding: 4px 12px; border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.1); display: flex; align-items: center; }}
        .banner-controls-shelf label p {{ color: white !important; font-size: 0.8rem !important; font-weight: 700 !important; text-transform: uppercase; letter-spacing: 0.05em; }}
        .banner-controls-shelf [data-testid="stRadio"] {{ margin-bottom: -15px; }}

        .stDateInput > div {{ border-radius: 10px !important; }}
        .holiday-list-item {{ display: flex; justify-content: space-between; align-items: center; background: rgba(239, 68, 68, 0.05); padding: 4px 10px; border-radius: 6px; margin-bottom: 4px; border-left: 3px solid #ef4444; font-size: 0.8rem; }}
        .holiday-date {{ font-weight: 600; color: #1e293b; }}

        @media (max-width: 800px) {{
            .app-banner-wrapper {{ height: auto; min-height: 180px; }}
            .app-banner-overlay {{ flex-direction: column; align-items: flex-start; justify-content: center; padding: 25px 20px; gap: 15px; position: static; background: linear-gradient(135deg, rgba(15, 23, 42, 0.9) 0%, rgba(15, 23, 42, 0.5) 100%); }}
            .app-banner-title {{ font-size: 1.4rem; }}
            .app-banner-subtitle {{ font-size: 0.85rem; }}
            .app-banner-clock-area {{ text-align: left; background: rgba(0,0,0,0.2); padding: 12px !important; margin-top: 5px; width: 100%; box-sizing: border-box; }}
            .banner-controls-shelf {{ margin-top: 10px; margin-bottom: 25px; margin-left: 0; justify-content: center; }}
        }}
        
        @media (max-width: 600px) {{
            .footer-inner {{ display: flex; flex-direction: column; align-items: center; gap: 8px; }}
            .footer-separator {{ display: none; }}
        }}

        /* --- BIKE ANIMATION STYLES --- */
        @keyframes moveFullScreen {{
            0%   {{ transform: translateX(250px) scale(1); opacity: 0; }}
            10%  {{ opacity: 1; }}
            90%  {{ opacity: 1; }}
            100% {{ transform: translateX(-115vw) scale(1); opacity: 0; }}
        }}
        @keyframes smoke-puff {{
            0% {{ transform: scale(0.4); opacity: 0.8; }}
            100% {{ transform: scale(2) translate(15px, -10px); opacity: 0; }}
        }}
        .full-screen-bike {{
            position: fixed;
            top: 80px;
            right: 0;
            z-index: 9999;
            pointer-events: none;
            display: flex;
            align-items: center;
            flex-direction: row;
            animation: moveFullScreen 18s linear infinite;
            filter: drop-shadow(0 5px 15px rgba(0,0,0,0.1));
        }}
        .bike-img {{ width: 60px; z-index: 10000; display: block; }}
        .smoke-trail {{ display: flex; margin-left: -10px; }}
        .smoke {{ width: 12px; height: 12px; background: #cbd5e1; border-radius: 50%; animation: smoke-puff 0.8s ease-out infinite; margin-left: -6px; }}
        .smoke:nth-child(2) {{ animation-delay: 0.2s; }}
        .smoke:nth-child(3) {{ animation-delay: 0.4s; }}

        /* General dark mode enforcement for custom HTML text */
        @media (prefers-color-scheme: dark) {{
            .hub-title, .hub-subtitle, .metric-value {{ color: #ffffff !important; }}
            .hub-card, .metric-card {{ background: rgba(255, 255, 255, 0.05) !important; border-color: rgba(255, 255, 255, 0.1) !important; }}
            .metric-label {{ color: #cbd5e1 !important; }}
            .hub-footer {{ background: #0e1117 !important; color: #cbd5e1 !important; border-top-color: rgba(255, 255, 255, 0.1) !important; }}
            .hub-title-row {{ background: rgba(29, 78, 216, 0.1) !important; border-bottom-color: rgba(255, 255, 255, 0.1) !important; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
