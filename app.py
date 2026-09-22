import streamlit as st

st.set_page_config(
    page_title="DEEN OPS Terminal",
    page_icon="AH",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.app_bootstrap import run_app  # noqa: E402
from src.utils.version_check import build_streamlit_version_warning  # noqa: E402

# Advisory runtime check: warn once per session when the active Streamlit
# version drifts from requirements.lock (e.g. launching via the wrong Python).
if not st.session_state.get("_streamlit_version_warned"):
    st.session_state["_streamlit_version_warned"] = True
    _version_warning = build_streamlit_version_warning()
    if _version_warning:
        st.warning(_version_warning)

try:
    run_app()
except Exception as exc:
    from src.utils.logging import log_error

    log_error(exc, context="App Bootstrap")
    st.error(
        "Application failed to render. Check 'More Tools -> System Logs' for details."
    )
    st.code(str(exc))
