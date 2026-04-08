import streamlit as st
from datetime import datetime, timedelta, timezone

def render_dynamic_clock(sync_time=None):
    """Renders a compact, high-fidelity JavaScript clock + sync status for the header."""
    tz_bd = timezone(timedelta(hours=6))
    now_bd = datetime.now(tz_bd)
    
    sync_html = ""
    if sync_time:
        diff = datetime.now() - sync_time
        mins = int(diff.total_seconds() / 60)
        sync_label = "Just now" if mins < 1 else f"{mins}m ago"
        sync_html = f'<div id="header-sync-status" style="font-size: 0.75rem; color: #64748b; font-weight: 500; margin-top: 2px;">🔄 Last Synced: {sync_label}</div>'

    st.markdown(f"""
        <div style="text-align: right; line-height: 1.1;">
            <div id="header-clock-time" style="font-size: 1.1rem; font-weight: 700; color: #1e293b; letter-spacing: -0.3px;">
                {now_bd.strftime('%I:%M:%S %p')}
            </div>
            <div id="header-clock-date" style="font-size: 0.8rem; color: #64748b; font-weight: 500;">
                {now_bd.strftime('%A, %B %d')}
            </div>
            {sync_html}
        </div>
        <script>
            (function() {{
                if (window.headerClockInterval) clearInterval(window.headerClockInterval);
                function updateClock() {{
                    const timeEl = document.getElementById('header-clock-time');
                    const dateEl = document.getElementById('header-clock-date');
                    if (!timeEl) return;
                    
                    const now = new Date();
                    const bdTime = new Date(now.getTime() + (now.getTimezoneOffset() * 60000) + (6 * 3600000));
                    
                    timeEl.innerHTML = bdTime.toLocaleTimeString('en-US', {{ 
                        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true 
                    }});
                    
                    if (dateEl) {{
                        dateEl.innerHTML = bdTime.toLocaleDateString('en-US', {{ 
                            weekday: 'long', month: 'long', day: '2-digit' 
                        }});
                    }}
                }}
                updateClock();
                window.headerClockInterval = setInterval(updateClock, 1000);
            }})();
        </script>
    """, unsafe_allow_html=True)
