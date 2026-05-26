import streamlit as st
import pandas as pd
import asyncio
import re
import io
from datetime import datetime
from typing import Dict, List

from src.config.settings import get_setting
# Add direct WooCommerce sync imports
from src.services.woocommerce.client import load_live_source
from src.services.woocommerce.stock import fetch_woocommerce_stock

from src.services.llm.manager import init_llm_controller

# Import Pathao tracking
from src.services.pathao.status import get_pathao_order_status

from src.utils.ml_brain import NeuralBrain
from src.processing.forecasting import PredictiveIntelligence

@st.cache_resource
def get_cached_brain():
    return NeuralBrain()

# --- ML Caching Helpers to Speed Up AI Queries ---
@st.cache_data(ttl=1800, show_spinner=False)
def _get_cached_forecast(df: pd.DataFrame):
    if df is None or df.empty or "Date" not in df.columns or "Total Amount" not in df.columns:
        return None
    df_daily = df.copy()
    df_daily['Day'] = pd.to_datetime(df_daily['Date'], errors='coerce').dt.date
    series = df_daily.groupby('Day')['Total Amount'].sum()
    if len(series) >= 3:
        forecasts, _ = PredictiveIntelligence.forecast(series)
        return forecasts
    return None

@st.cache_data(ttl=1800, show_spinner=False)
def _get_cached_anomalies(df: pd.DataFrame):
    if df is None or df.empty:
        return pd.DataFrame()
    return get_cached_brain().detect_anomalies(df)

class AIDataAgent:
    """
    Enhanced AI-BI Agent with NLP Intent Routing & ML Grounding.
    Uses NeuralBrain for intent detection and PredictiveIntelligence for forecasting.
    """
    def __init__(self, provider="🛡️ Smart Failover (Free Tiers)", api_key=None, model_name=None, context_dfs: Dict[str, pd.DataFrame] = None):
        self.provider = provider
        self.api_key = api_key
        self.model_name = model_name
        self.controller = init_llm_controller()
        self.brain = get_cached_brain()
        if context_dfs is not None:
            self.context_dfs = context_dfs
        else:
            # Fallback to session state for interactive use
            self.context_dfs = {
                "sales": st.session_state.get("wc_curr_df"),
                "inventory_distribution": st.session_state.get("inv_res_data"),
                "stock_levels": st.session_state.get("wc_stock_df"),
                "pathao_dispatch": st.session_state.get("pathao_res_df"),
                "pathao_tracking": st.session_state.get("pilot_pathao_tracking_df"),
                "uploaded": st.session_state.get("pilot_uploaded_df"),
            }

    def get_grounded_insights(self, query: str) -> str:
        intent = self.brain.semantic_query_intent(query)
        insights = []
        
        if intent["type"] == "ml_forecast" or "forecast" in query.lower() or "predict" in query.lower():
            df = self.context_dfs["sales"]
            forecasts = _get_cached_forecast(df)
            if forecasts:
                best = forecasts[0]
                insights.append(f"ML FORECAST: '{best['name']}' predicts next 7 days will total approx ৳{sum(best['forecast']):,.0f}.")
        
        if intent["type"] == "ml_anomaly" or "anomaly" in query.lower() or "unusual" in query.lower():
            df = self.context_dfs["sales"]
            anomalies = _get_cached_anomalies(df)
            if not anomalies.empty:
                top = anomalies.iloc[0]
                insights.append(f"ML ANOMALY: A '{top['type']}' spike was detected on {top['date']} with value ৳{top['value']:,.0f} (Z-Score: {top['score']:.2f}).")
                
        # Pathao Live Tracking Intent (Regex extraction for Consignment IDs)
        pathao_match = re.search(r'(?i)(?:DD|D-|M-)\w+', query)
        if pathao_match:
            consignment_id = pathao_match.group(0).upper().strip()
            status_res = get_pathao_order_status(consignment_id)
            if "error" not in status_res:
                data = status_res.get("data", {})
                live_status = data.get("order_status", "Unknown")
                insights.append(f"PATHAO LIVE STATUS: Consignment {consignment_id} is currently '{live_status}'. Payment status: {data.get('payment_status')}.")

        # Report Generation Intent
        if "report" in query.lower() or "summary" in query.lower():
             insights.append("ACTION: The user is requesting a comprehensive report or summary. Please format the response as a detailed, structured markdown report covering sales, inventory, and fulfillment performance based on the available data context.")

        # General grounding
        for name, df in self.context_dfs.items():
            if df is not None and not df.empty:
                summary = f"{len(df)} rows."
                if name == "sales" and "Total Amount" in df.columns:
                    summary += f" Total Revenue: ৳{df['Total Amount'].sum():,.0f}."
                if name == "stock_levels" and "Stock" in df.columns:
                    summary += f" Total Stock: {df['Stock'].sum():,.0f} units."
                insights.append(f"CONTEXT {name.upper()}: {summary}")
            
        return " | ".join(insights) if insights else "Context: No data loaded. Please sync or upload data in other tabs."

    def build_messages(self, query: str, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        grounding = self.get_grounded_insights(query)
        
        system_msg = {
            "role": "system",
            "content": (
                "You are DEEN Intelligence Data Pilot. You are an expert e-commerce analyst. "
                "Use the provided ML Insights to back your claims. Be decisive and professional. "
                "If the user asks for a report, provide a well-structured markdown report with headings, bullet points, and actionable insights. "
                "\n\nCRITICAL RULES:\n"
                "1. Order Logic: An `order_id` represents a single unique order. An order may contain multiple item lines. You must NEVER count item rows as a single order. When asked for 'total orders' or 'number of orders', you must use distinct counts of `order_id`.\n"
                "2. Continuous Learning Protocol: If a user corrects a mistake you make regarding this logic (or any other data relationship), you must immediately internalize this correction.\n"
                "3. Auto-Memorization: If the user corrects a mistake or provides a new persistent rule, you MUST output the exact string `[KNOWLEDGE_UPDATE: <the new rule>]` on a new line.\n"
                f"CURRENT ML INSIGHTS: {grounding}"
            )
        }
        return [system_msg] + history[-5:] + [{"role": "user", "content": query}]

    async def get_response_stream(self, query: str, history: List[Dict[str, str]]):
        messages = self.build_messages(query, history)
        
        # Use simple router for provider execution
        try:
            async for chunk in self.controller.get_response_stream_async(messages):
                yield chunk
        except Exception as e:
            # Fallback to synchronous call if async streaming fails
            try:
                yield self.controller.get_response_sync(messages)
            except Exception as fallback_err:
                if "ollama" in self.provider.lower():
                    yield f"\n\n⚠️ **Connection Error:** Ollama is unreachable. Please ensure it is running locally via `ollama serve`.\n\n`Details: {fallback_err}`"
                else:
                    yield f"\n\n⚠️ **Error:** Failed to get response from {self.provider}. Please verify your API key and connection.\n\n`Details: {fallback_err}`"

# ------------------------------
# 2. UI COMPONENTS
# ------------------------------
def render_sidebar_controls():
    with st.sidebar:
        st.markdown(
            """
            <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid rgba(128,128,128,0.2);">
                <h2 style="margin: 0; font-size: 1.4rem; background: -webkit-linear-gradient(45deg, #3b82f6, #10b981); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: -0.02em;">⚙️ Control Panel</h2>
                <p style="font-size: 0.8rem; color: #64748b; margin-top: 4px; margin-bottom: 0;">Intelligence Engine Configuration</p>
            </div>
            """,
            unsafe_allow_html=True
        )
        # Cloud/Local Detection
        is_cloud = init_llm_controller().is_cloud

        engines = ["🛡️ Smart Failover (Free Tiers)", "OpenAI", "Google Gemini"]
        if not is_cloud:
            engines.append("Ollama (Local)")

        if hasattr(st, "pills"):
            provider = st.pills(
                "Intelligence Engine",
                engines,
                default=engines[0],
                selection_mode="single"
            )
            if not provider: provider = engines[0]
        else:
            provider = st.selectbox(
                "Intelligence Engine",
                engines,
                index=0
            )

        api_key, model_name = None, None
        if provider == "🛡️ Smart Failover (Free Tiers)":
            active_nodes = [p.capitalize() for p in init_llm_controller().key_manager.keys if len(init_llm_controller().key_manager.keys[p])>0]
            st.caption("Active Nodes: " + (", ".join(active_nodes) if active_nodes else "None"))
        elif provider in ["OpenAI", "Google Gemini"]:
            api_key = st.text_input(f"{provider} Key", type="password")
            model_name = "gpt-4o" if provider == "OpenAI" else "gemini-1.5-flash"
        elif provider == "Ollama (Local)":
            controller = init_llm_controller()
            models = controller.key_manager.get_local_models()
            if models:
                model_name = st.selectbox("Local Model", models)
            else:
                st.warning("Ollama unreachable. Run `ollama serve`.")
                model_name = st.text_input("Manual Model Name", value="llama3")

        if is_cloud:
            st.warning("☁️ **Cloud Mode**: Personal GPU engines (Ollama) restricted. Use Cloud Failover.")

        if hasattr(st, "pills"):
            sync_opts = ["Manual Sync", "Smart Auto-Sync"]
            sync_choice = st.pills(
                "Data Sync Mode", 
                sync_opts, 
                default="Manual Sync", 
                selection_mode="single", 
                help="Smart Auto-Sync fetches fresh data before answering if the knowledge base is empty or older than 15 mins."
            )
            if not sync_choice: sync_choice = "Manual Sync"
            auto_sync = (sync_choice == "Smart Auto-Sync")
        else:
            auto_sync = st.toggle("🔄 Smart Auto-Sync", value=False, help="Automatically fetches fresh data before answering if the knowledge base is empty or older than 15 minutes.")

        st.divider()
        st.markdown("### 📁 Knowledge Base")
        
        if st.button("🔄 Sync from WooCommerce", use_container_width=True, type="primary"):
            with st.status("Syncing live data...", expanded=True) as status:
                try:
                    status.write("📡 Fetching live orders...")
                    load_live_source()  # This function automatically updates session state
                    status.write("📦 Fetching stock levels...")
                    stock_df = fetch_woocommerce_stock()
                    if stock_df is not None:
                        st.session_state.wc_stock_df = stock_df
                    status.update(label="Sync Complete!", state="complete", expanded=False)
                    st.toast("✅ Live data synced from WooCommerce.")
                    st.rerun()
                except Exception as e:
                    status.update(label="Sync Failed", state="error")
                    st.error(f"Failed to sync from WooCommerce: {e}")

        if st.button("🔄 Sync Pathao Statuses", use_container_width=True):
            with st.status("Syncing Pathao statuses...", expanded=True) as status:
                try:
                    # 1. Get source dataframe
                    status.write("Finding order data...")
                    orders_df = st.session_state.get("wc_full_df")
                    if orders_df is None or orders_df.empty:
                        orders_df = st.session_state.get("wc_curr_df")

                    if orders_df is None or orders_df.empty:
                        st.error("No WooCommerce order data found. Please sync from WooCommerce first.")
                        status.update(label="Sync Failed", state="error")
                        st.stop()

                    # 2. Identify columns
                    status.write("Identifying columns...")
                    cols = list(orders_df.columns)
                    consignment_col = next((c for c in cols if any(kw in str(c).lower() for kw in ["tracking", "consignment", "pathao id"])), None)
                    if not consignment_col:
                        st.error("Could not auto-detect a 'Tracking' or 'Consignment' column in the order data.")
                        status.update(label="Sync Failed", state="error")
                        st.stop()

                    status_col = next((c for c in cols if "status" in str(c).lower()), None)
                    if not status_col:
                        st.error("Could not auto-detect an 'Order Status' column.")
                        status.update(label="Sync Failed", state="error")
                        st.stop()

                    # 3. Filter for pending orders
                    status.write("Filtering for pending shipments...")
                    terminal_statuses = ['completed', 'cancelled', 'refunded', 'failed', 'trash']
                    pending_df = orders_df[~orders_df[status_col].astype(str).str.lower().isin(terminal_statuses)].copy()
                    pending_df.dropna(subset=[consignment_col], inplace=True)
                    pending_df = pending_df[pending_df[consignment_col].astype(str).str.strip().replace('nan', '') != ""]
                    unique_consignments = pending_df[consignment_col].astype(str).str.strip().unique()

                    if len(unique_consignments) == 0:
                        st.info("No pending orders with consignment IDs found to track.")
                        status.update(label="Sync Complete (No Orders)", state="complete", expanded=False)
                        st.stop()

                    # 4. Fetch statuses
                    status.write(f"Fetching {len(unique_consignments)} statuses from Pathao...")
                    results = []
                    progress_bar = st.progress(0)
                    for i, cid in enumerate(unique_consignments):
                        res = get_pathao_order_status(cid)
                        results.append(res)
                        progress_bar.progress((i + 1) / len(unique_consignments))

                    # 5. Create and store DataFrame
                    st.session_state.pilot_pathao_tracking_df = pd.DataFrame(results)
                    status.update(label="Pathao Sync Complete!", state="complete", expanded=False)
                    st.toast(f"✅ Synced {len(results)} Pathao statuses.")
                    st.rerun()
                except Exception as e:
                    status.update(label="Sync Failed", state="error")
                    st.error(f"Failed to sync Pathao statuses: {e}")

        if "pilot_uploader_key" not in st.session_state:
            st.session_state.pilot_uploader_key = 0
            
        up_file = st.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"], key=f"pilot_up_{st.session_state.pilot_uploader_key}")
        if up_file:
            try:
                df = pd.read_csv(up_file) if up_file.name.endswith('.csv') else pd.read_excel(up_file)
                st.session_state.pilot_uploaded_df = df
                st.success(f"Ingested {len(df)} records.")
            except Exception as e:
                st.error(f"Failed to parse file: {e}")

        uploaded_df = st.session_state.get("pilot_uploaded_df")
        pathao_track_df = st.session_state.get("pilot_pathao_tracking_df")
        if (uploaded_df is not None and not uploaded_df.empty) or (pathao_track_df is not None and not pathao_track_df.empty):
            if st.button("Clear Knowledge Base", use_container_width=True):
                st.session_state.pilot_uploaded_df = None
                st.session_state.pilot_pathao_tracking_df = None
                st.session_state.pilot_uploader_key += 1
                st.rerun()

    return provider, api_key, model_name, auto_sync

def render_ai_pilot_page():
    st.markdown(
        """
        <div style='text-align: center; margin-bottom: 2rem;'>
            <h1 style='color: #6366f1; margin-bottom: 0;'>🚀 GLOBAL DATA PILOT</h1>
            <p style='opacity: 0.7; font-size: 1.1rem;'>Enhanced Knowledge Base & ML Intelligence Engine</p>
        </div>
        """, 
        unsafe_allow_html=True
    )

    # ⚡ Instant Boot: Load Offline Snapshot
    if "snapshot_loaded" not in st.session_state:
        try:
            from src.processing.hybrid_data_loader import HybridDataLoader
            loader = HybridDataLoader()
            snapshot_df = loader.load_fast()
            if snapshot_df is not None and not snapshot_df.empty:
                if "wc_curr_df" not in st.session_state or st.session_state.wc_curr_df is None:
                    st.session_state.wc_curr_df = snapshot_df
                    st.session_state.wc_full_df = snapshot_df
                    st.toast("⚡ Offline Data Snapshot Loaded Instantly!")
        except Exception as e:
            st.warning(f"Failed to load offline snapshot: {e}")
        st.session_state.snapshot_loaded = True

    # Init Messages
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [{"role": "assistant", "content": "Welcome to the Pilot's Seat. Ask me about sales, generate reports, or track Pathao live statuses!"}]
    
    if "pilot_reports" not in st.session_state:
        st.session_state.pilot_reports = []

    # Sidebar
    provider, api_key, model_name, auto_sync = render_sidebar_controls()

    # Modern Tabs Layout
    tab_chat, tab_kb, tab_reports = st.tabs([":material/chat: Pilot Interface", ":material/psychology: Knowledge Base", ":material/description: Generated Reports"])

    with tab_kb:
        st.markdown("### 📂 Data Context")
        st.markdown("The AI currently has access to the following dataframes to ground its answers:")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Live Sales preview
            sales_df = st.session_state.get("wc_curr_df")
            if sales_df is not None and not sales_df.empty:
                st.caption(f"📈 **Live Sales** — {len(sales_df)} rows")
                st.dataframe(sales_df.head(3), use_container_width=True, hide_index=True)
            else:
                st.caption("📈 **Live Sales** — No data")

            # Inventory preview
            inv_df = st.session_state.get("inv_res_data")
            if inv_df is not None and not inv_df.empty:
                st.caption(f"📦 **Inventory Distribution** — {len(inv_df)} rows")
                st.dataframe(inv_df.head(3), use_container_width=True, hide_index=True)
            else:
                st.caption("📦 **Inventory Distribution** — No data")
                
            # Pathao preview
            pathao_df = st.session_state.get("pathao_res_df")
            if pathao_df is not None and not pathao_df.empty:
                st.caption(f"🚚 **Pathao Dispatch** — {len(pathao_df)} rows")
                st.dataframe(pathao_df.head(3), use_container_width=True, hide_index=True)
            else:
                st.caption("🚚 **Pathao Dispatch** — No data")

        with col2:
            # Stock Levels preview
            stock_df = st.session_state.get("wc_stock_df") 
            if stock_df is not None and not stock_df.empty:
                st.caption(f"🏢 **Stock Levels** — {len(stock_df)} rows")
                st.dataframe(stock_df.head(3), use_container_width=True, hide_index=True)
            else:
                st.caption("🏢 **Stock Levels** — No data")

            # Pathao Tracking preview
            pathao_track_df = st.session_state.get("pilot_pathao_tracking_df")
            if pathao_track_df is not None and not pathao_track_df.empty:
                st.caption(f"📍 **Pathao Tracking** — {len(pathao_track_df)} rows")
                st.dataframe(pathao_track_df.head(3), use_container_width=True, hide_index=True)
                
                output_buffer = io.BytesIO()
                with pd.ExcelWriter(output_buffer, engine="xlsxwriter") as writer:
                    pathao_track_df.to_excel(writer, index=False, sheet_name="Pathao_Tracking")
                st.download_button(
                    label="📥 Export Tracking Data",
                    data=output_buffer.getvalue(),
                    file_name=f"Pathao_Tracking_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                st.caption("📍 **Pathao Tracking** — No data")

            # Uploaded preview
            up_df = st.session_state.get("pilot_uploaded_df")
            if up_df is not None and not up_df.empty:
                st.caption(f"📁 **Uploaded Files** — {len(up_df)} rows")
                st.dataframe(up_df.head(3), use_container_width=True, hide_index=True)
            else:
                st.caption("📁 **Uploaded Files** — No data")

    with tab_reports:
        st.markdown("### 📑 AI Generated Reports")
        
        if st.button("✨ Auto-Generate Executive Report", type="primary", use_container_width=True):
            prompt = "Generate a comprehensive executive summary report covering current sales, stock levels, and fulfillment. Use professional formatting."
            st.session_state.agent_messages.append({"role": "user", "content": prompt})
            st.rerun()
            
        if not st.session_state.pilot_reports:
            st.info("No reports generated yet. Ask the Pilot to generate a report in the chat, or use the button above.")
        else:
            for idx, report in enumerate(reversed(st.session_state.pilot_reports)):
                with st.expander(f"Report: {report['date']}", expanded=(idx==0)):
                    st.markdown(report['content'])
                    st.download_button("📥 Download Markdown", report['content'], file_name=f"Report_{report['date'].replace(':', '-')}.md", key=f"dl_rep_{idx}")

    with tab_chat:
        col_chat, col_info = st.columns([3, 1])
        
        with col_info:
            st.info(
                "**💡 Pro Tips**\n\n"
                "- **Forecasts:** *'What is the sales forecast for next week?'*\n"
                "- **Reports:** *'Generate an executive summary report for today.'*\n"
                "- **Tracking:** *'Track Pathao ID DD123456.'*\n"
                "- **Anomalies:** *'Are there any anomalies in sales?'*"
            )
            last_intent = st.session_state.get("pilot_last_intent")
            if last_intent:
                st.caption(f"**Last Intent Detected:** `{last_intent}`")

        with col_chat:
            # Chat Display
            chat_container = st.container(height=500)
            with chat_container:
                for msg in st.session_state.agent_messages:
                    avatar = "🤖" if msg["role"] == "assistant" else "👤"
                    with st.chat_message(msg["role"], avatar=avatar):
                        st.markdown(msg["content"])

            # Input Area
            audio_bytes = None
            if hasattr(st, "audio_input"):
                audio_bytes = st.audio_input("Speak to Data Pilot", label_visibility="collapsed")
                
            prompt = st.chat_input("Ask Data Pilot about sales, stock, or request a report...")
            
            if audio_bytes and audio_bytes != st.session_state.get("last_audio_bytes"):
                st.session_state.last_audio_bytes = audio_bytes
                
                st.session_state.agent_messages.append({"role": "user", "content": "*(🎤 Voice Command Captured)*"})
                with st.chat_message("user", avatar="👤"):
                    st.markdown("*(🎤 Voice Command Captured)*")
                    st.audio(audio_bytes)
                
                with st.chat_message("assistant", avatar="🤖"):
                    msg = "I received your voice message! 🎙️\n\nTo process spoken commands, please integrate a Speech-to-Text model (like OpenAI Whisper or Gemini Audio) into my `DynamicLLMController`."
                    st.markdown(msg)
                    st.session_state.agent_messages.append({"role": "assistant", "content": msg})
                
            elif prompt:
                # Handle Smart Auto-Sync
                if auto_sync:
                    last_sync = st.session_state.get("live_sync_time")
                    if not last_sync or (datetime.now() - last_sync).total_seconds() > 900:
                        with st.status("🔄 Smart Auto-Sync (Data is stale)...", expanded=True) as status:
                            try:
                                status.write("📡 Fetching live orders...")
                                load_live_source()
                                status.write("📦 Fetching stock levels...")
                                stock_df = fetch_woocommerce_stock()
                                if stock_df is not None:
                                    st.session_state.wc_stock_df = stock_df
                                status.update(label="Knowledge Base Updated!", state="complete", expanded=False)
                            except Exception as e:
                                status.update(label="Sync Failed", state="error")
                                st.error(f"Auto-sync failed: {e}")

                st.session_state.agent_messages.append({"role": "user", "content": prompt})
                with st.chat_message("user", avatar="👤"):
                    st.markdown(prompt)

                with st.chat_message("assistant", avatar="🤖"):
                    response_placeholder = st.empty()
                    full_response = ""

                    agent = AIDataAgent(provider, api_key, model_name)
                    intent_obj = agent.brain.semantic_query_intent(prompt)
                    st.session_state.pilot_last_intent = intent_obj["type"]
                    
                    if "report" in prompt.lower() or "summary" in prompt.lower():
                        st.session_state.pilot_last_intent = "report_generation"

                    import queue
                    import threading
                    import time
                    
                    q = queue.Queue()
                    chat_history = st.session_state.agent_messages[:-1]
                    
                    async def fetch_stream():
                        try:
                            async for chunk in agent.get_response_stream(prompt, chat_history):
                                q.put({"chunk": chunk})
                        except Exception as e:
                            q.put({"error": e})
                        finally:
                            q.put({"done": True})

                    def thread_run():
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        new_loop.run_until_complete(fetch_stream())
                        new_loop.close()

                    t = threading.Thread(target=thread_run)
                    t.start()
                    
                    while True:
                        try:
                            msg = q.get(timeout=0.1)
                        except queue.Empty:
                            if not t.is_alive():
                                break
                            continue
                            
                        if "done" in msg:
                            break
                        if "error" in msg:
                            st.error(f"Streaming Error: {msg['error']}")
                            break
                            
                        full_response += msg["chunk"]
                        
                        # Drain the queue to batch updates and prevent WebSocket flooding
                        done_flag = False
                        while not q.empty():
                            try:
                                next_msg = q.get_nowait()
                                if "done" in next_msg:
                                    done_flag = True
                                    break
                                if "error" in next_msg:
                                    st.error(f"Streaming Error: {next_msg['error']}")
                                    done_flag = True
                                    break
                                full_response += next_msg["chunk"]
                            except queue.Empty:
                                break
                                
                        display_text = re.sub(r'\[KNOWLEDGE_UPDATE:.*?\]', '', full_response)
                        response_placeholder.markdown(display_text + "▌")
                        
                        if done_flag:
                            break
                            
                        # Throttle UI updates to ~20 FPS to prevent mobile WebSocket flooding
                        time.sleep(0.05)
                    t.join()
                    
                    display_text = re.sub(r'\[KNOWLEDGE_UPDATE:.*?\]', '', full_response)
                    response_placeholder.markdown(display_text)
                    
                    updates = re.findall(r'\[KNOWLEDGE_UPDATE:\s*(.*?)\]', full_response)
                    if updates:
                        from pathlib import Path
                        knowledge_file = Path("data/pilot_knowledge.txt")
                        knowledge_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(knowledge_file, "a", encoding="utf-8") as f:
                            for update in updates:
                                f.write(f"- {update.strip()}\n")
                        st.toast("🧠 Pilot internalized a new rule!", icon="✅")
                        
                    full_response = display_text.strip()

                st.session_state.agent_messages.append({"role": "assistant", "content": full_response})
                
                # If report was requested, save it to reports tab
                if st.session_state.pilot_last_intent == "report_generation":
                    st.session_state.pilot_reports.append({
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "content": full_response
                    })

                if len(full_response) > 50:
                    with st.expander("🔍 Intelligence Layer: Brain Routing"):
                        st.caption(f"Engine: {provider} | Semantic Intent: {st.session_state.pilot_last_intent.upper()}")
                        st.info("Grounding: Utilizing Multi-Model Predictive Intelligence & Knowledge Base context.")
