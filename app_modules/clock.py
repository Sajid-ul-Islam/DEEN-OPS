import streamlit as st
from datetime import datetime, timedelta, timezone

def render_dynamic_clock():
    """Renders a premium, dynamic JavaScript clock tied to Bangladesh time (UTC+6)."""
    tz_bd = timezone(timedelta(hours=6))
    now_bd = datetime.now(tz_bd)
    
    st.markdown(f"""
        <div style="padding: 15px; background: rgba(29, 78, 216, 0.05); border-radius: 12px; border: 1px solid rgba(29, 78, 216, 0.1); margin-bottom: 20px;">
            <div id="global-sidebar-clock" style="font-size: 1.5rem; font-weight: 800; color: #1d4ed8; letter-spacing: -0.5px; line-height: 1;">
                {now_bd.strftime('%I:%M:%S %p')}
            </div>
            <div id="global-sidebar-date" style="font-size: 0.85rem; color: #64748b; font-weight: 500; margin-top: 4px;">
                {now_bd.strftime('%A, %B %d')}
            </div>
        </div>
        <script>
            (function() {{
                if (window.globalClockInterval) clearInterval(window.globalClockInterval);
                function updateClock() {{
                    const timeEl = document.getElementById('global-sidebar-clock');
                    const dateEl = document.getElementById('global-sidebar-date');
                    if (!timeEl) return;
                    
                    const now = new Date();
                    // Offset for Bangladesh (UTC+6)
                    const bdTime = new Date(now.getTime() + (now.getTimezoneOffset() * 60000) + (6 * 3600000));
                    
                    timeEl.innerHTML = bdTime.toLocaleTimeString('en-US', {{ 
                        hour: '2-digit', 
                        minute: '2-digit', 
                        second: '2-digit', 
                        hour12: true 
                    }});
                    
                    if (dateEl) {{
                        dateEl.innerHTML = bdTime.toLocaleDateString('en-US', {{ 
                            weekday: 'long', 
                            month: 'long', 
                            day: '2-digit' 
                        }});
                    }}
                }}
                updateClock();
                window.globalClockInterval = setInterval(updateClock, 1000);
            }})();
        </script>
    """, unsafe_allow_html=True)
