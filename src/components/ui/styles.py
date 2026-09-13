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
        st.markdown(
            f"<style data-version='{file_version}'>\n{css_content}\n{extra_styles}\n</style>",
            unsafe_allow_html=True,
        )

        # Inject dynamic theme synchronization script into main DOM
        theme_sync_script = """
        <script>
        (function() {
          function detectIsDark() {
            // 1. Inspect Streamlit header (Emotion styles this; never overridden by custom CSS)
            var header = document.querySelector('header[data-testid="stHeader"]') || document.querySelector('header');
            if (header) {
              var hStyle = window.getComputedStyle(header);
              if (hStyle.colorScheme === 'dark') return true;
              if (hStyle.colorScheme === 'light') return false;
              var hBg = hStyle.backgroundColor;
              if (hBg && hBg !== 'transparent' && hBg !== 'rgba(0, 0, 0, 0)') {
                var hRgb = hBg.match(/\\d+/g);
                if (hRgb && hRgb.length >= 3) {
                  var hLum = 0.299 * parseInt(hRgb[0], 10) + 0.587 * parseInt(hRgb[1], 10) + 0.114 * parseInt(hRgb[2], 10);
                  return hLum < 128;
                }
              }
            }

            // 2. Inspect Streamlit sidebar (Emotion styles this: #262730 in dark, #f0f2f6 in light)
            var sidebar = document.querySelector('section[data-testid="stSidebar"]');
            if (sidebar) {
              var sStyle = window.getComputedStyle(sidebar);
              if (sStyle.colorScheme === 'dark') return true;
              if (sStyle.colorScheme === 'light') return false;
              var sBg = sStyle.backgroundColor;
              if (sBg && sBg !== 'transparent' && sBg !== 'rgba(0, 0, 0, 0)') {
                var sRgb = sBg.match(/\\d+/g);
                if (sRgb && sRgb.length >= 3) {
                  var sLum = 0.299 * parseInt(sRgb[0], 10) + 0.587 * parseInt(sRgb[1], 10) + 0.114 * parseInt(sRgb[2], 10);
                  return sLum < 128;
                }
              }
            }

            // 3. Fallback to OS/browser preference
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
              return true;
            }

            // Default: DEEN-OPS is a dark cyberpunk operational terminal
            return true;
          }

          function syncDeenTheme() {
            var isDark = detectIsDark();
            var theme = isDark ? 'dark' : 'light';
            var doc = document.documentElement;
            if (doc.getAttribute('data-theme') !== theme) {
              doc.setAttribute('data-theme', theme);
              doc.classList.toggle('dark', isDark);
              doc.classList.toggle('light', !isDark);
            }
            if (document.body && document.body.getAttribute('data-theme') !== theme) {
              document.body.setAttribute('data-theme', theme);
              document.body.classList.toggle('dark', isDark);
              document.body.classList.toggle('light', !isDark);
            }
            var app = document.querySelector('.stApp');
            if (app && app.getAttribute('data-theme') !== theme) {
              app.setAttribute('data-theme', theme);
              app.classList.toggle('dark', isDark);
              app.classList.toggle('light', !isDark);
            }
          }

          syncDeenTheme();
          requestAnimationFrame(syncDeenTheme);
          setTimeout(syncDeenTheme, 100);
          setTimeout(syncDeenTheme, 400);

          if (!window.__deen_theme_observer_installed) {
            window.__deen_theme_observer_installed = true;
            var observer = new MutationObserver(function() {
              syncDeenTheme();
            });
            observer.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'class'] });
            var appEl = document.querySelector('.stApp');
            if (appEl) {
              observer.observe(appEl, { attributes: true, attributeFilter: ['style', 'class'] });
            }
            var headerEl = document.querySelector('header[data-testid="stHeader"]');
            if (headerEl) {
              observer.observe(headerEl, { attributes: true, attributeFilter: ['style', 'class'] });
            }
            var sidebarEl = document.querySelector('section[data-testid="stSidebar"]');
            if (sidebarEl) {
              observer.observe(sidebarEl, { attributes: true, attributeFilter: ['style', 'class'] });
            }
            if (window.matchMedia) {
              window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
                syncDeenTheme();
              });
            }
          }
        })();
        </script>
        """
        if hasattr(st, "html"):
            st.html(theme_sync_script, unsafe_allow_javascript=True)
