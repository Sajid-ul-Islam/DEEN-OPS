import os
import base64
import streamlit as st


def render_footer():
    """Renders a robust and persistent branding footer."""
    logo_src = "https://logo.clearbit.com/deencommerce.com"
    try:
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
                <div class="footer-inner" style="width:100%; text-align:center;">
                    <span style="margin-right:0px;">&copy; 2026 <a href="https://github.com/saajiidi" target="_blank">Sajid Islam</a>. All rights reserved.</span>
                    <span class="footer-separator" style="margin:0 12px; opacity:0.5;">|</span>
                    <a href="https://deencommerce.com/" target="_blank" style="text-decoration:none;">
                        <b>Powered by </b>
                        <img src="{logo_src}" width="20" class="deen-logo-small" onerror="this.style.display='none'" style="margin:0 4px;">
                        <b>DEEN Commerce Ltd.</b>
                    </a>
                </div>
            </div>
        """,
        unsafe_allow_html=True,
    )
