import streamlit as st
import pandas as pd
import asyncio
from datetime import datetime
from typing import Dict, List

from src.config.settings import get_setting
# Add direct WooCommerce sync imports
from src.services.woocommerce.client import load_live_source
from src.services.woocommerce.stock import fetch_woocommerce_stock

from src.services.llm.manager import init_llm_controller

from src.utils.ml_brain import NeuralBrain
from src.processing.forecasting import PredictiveIntelligence

@st.cache_resource
def get_cached_brain():
    return NeuralBrain()

class AIDataAgent:
    """
    Enhanced AI-BI Agent with NLP Intent Routing & ML Grounding.
    Uses NeuralBrain for intent detection and PredictiveIntelligence for forecasting.
    """
    def __init__(self, provider="🛡️ Smart Failover (Free Tiers)", api_key=None, model_name=None):
        self.provider = provider
        self.api_key = api_key
        self.model_name = model_name
        self.controller = init_llm_controller()
        self.brain = get_cached_brain()
        self.context_dfs = {
            "sales": st.session_state.get("wc_curr_df"),
            "inventory_distribution": st.session_state.get("inv_res_data"),
            "stock_levels": st.session_state.get("wc_stock_df"),
            "pathao_dispatch": st.session_state.get("pathao_res_df"),
            "uploaded": st.session_state.get("pilot_uploaded_df"),
        }

    def get_grounded_insights(self, query: str) -> str:
        intent = self.brain.semantic_query_intent(query)
        insights = []
        
        if intent["type"] == "ml_forecast":
            df = self.context_dfs["sales"]
            if df is not None and not df.empty:
                df_daily = df.copy()
                df_daily['Day'] = pd.to_datetime(df_daily['Date']).dt.date
                series = df_daily.groupby('Day')['Total Amount'].sum()
                forecasts, _ = PredictiveIntelligence.forecast(series)
                if forecasts:
                    best = forecasts[0]
                    insights.append(f"ML FORECAST: '{best['name']}' predicts next 7 days will total approx ৳{sum(best['forecast']):,.0f}.")
        
        elif intent["type"] == "ml_anomaly":
            df = self.context_dfs["sales"]
            anomalies = self.brain.detect_anomalies(df)
            if not anomalies.empty:
                top = anomalies.iloc[0]
                insights.append(f"ML ANOMALY: A '{top['type']}' spike was detected on {top['date']} with value ৳{top['value']:,.0f} (Z-Score: {top['score']:.2f}).")

        # General grounding
        for name, df in self.context_dfs.items():
            if df is not None and not df.empty:
                insights.append(f"CONTEXT {name.upper()}: {len(df)} rows available.")
            
        return " | ".join(insights) if insights else "Context: No data loaded. Please sync or upload data in other tabs."

    def build_messages(self, query: str, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        grounding = self.get_grounded_insights(query)
        
        system_msg = {
            "role": "system",
            "content": (
                "You are DEEN Intelligence Data Pilot. You are an expert e-commerce analyst. "
                "Use the provided ML Insights to back your claims. Be decisive and professional. "
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
        # Cloud/Local Detection
        is_cloud = init_llm_controller().is_cloud

        engines = ["🛡️ Smart Failover (Free Tiers)", "OpenAI", "Google Gemini"]
        if not is_cloud:
            engines.append("Ollama (Local)")

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
        if uploaded_df is not None and not uploaded_df.empty:
            if st.button("Clear Knowledge Base", use_container_width=True):
                st.session_state.pilot_uploaded_df = None
                st.session_state.pilot_uploader_key += 1
                st.rerun()

    return provider, api_key, model_name

def render_ai_pilot_page():
    st.markdown("<h1 style='text-align: center; color: #6366f1;'>🚀 DATA PILOT</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; opacity: 0.7;'>Real-time AI Business Intelligence & Prediction Engine</p>", unsafe_allow_html=True)

    # Init Messages
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [{"role": "assistant", "content": "Welcome to the Pilot's Seat. How can I analyze your operations today?"}]

    # Sidebar
    provider, api_key, model_name = render_sidebar_controls()

    # Two-column layout: Chat (left) + Context Panel (right)
    col_chat, col_context = st.columns([3, 2])

    with col_context:
        st.markdown("#### Data Context")

        # Live Sales preview
        sales_df = st.session_state.get("wc_curr_df")
        if sales_df is not None and not sales_df.empty:
            st.caption(f"Live Sales — {len(sales_df)} rows")
            st.dataframe(sales_df.head(5), use_container_width=True, hide_index=True)
        else:
            st.caption("Live Sales — No data")

        # Inventory preview
        inv_df = st.session_state.get("inv_res_data") # This is the distribution matrix
        if inv_df is not None and not inv_df.empty:
            st.caption(f"Inventory Distribution — {len(inv_df)} rows")
            st.dataframe(inv_df.head(5), use_container_width=True, hide_index=True)
        else:
            st.caption("Inventory Distribution — No data")

        # Stock Levels preview
        stock_df = st.session_state.get("wc_stock_df") # This is the raw stock levels
        if stock_df is not None and not stock_df.empty:
            st.caption(f"Stock Levels — {len(stock_df)} rows")
            st.dataframe(stock_df.head(5), use_container_width=True, hide_index=True)
        else:
            st.caption("Stock Levels — No data")

        # Pathao preview
        pathao_df = st.session_state.get("pathao_res_df")
        if pathao_df is not None and not pathao_df.empty:
            st.caption(f"Pathao Dispatch — {len(pathao_df)} rows")
            st.dataframe(pathao_df.head(5), use_container_width=True, hide_index=True)
        else:
            st.caption("Pathao Dispatch — No data")

        # Uploaded preview
        up_df = st.session_state.get("pilot_uploaded_df")
        if up_df is not None and not up_df.empty:
            st.caption(f"Uploaded — {len(up_df)} rows")
            st.dataframe(up_df.head(5), use_container_width=True, hide_index=True)
        else:
            st.caption("Uploaded — No data")

        # Last analysis intent
        last_intent = st.session_state.get("pilot_last_intent")
        if last_intent:
            st.divider()
            st.markdown(f"**Last Analysis Intent:** `{last_intent}`")

    with col_chat:
        # Chat Display
        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.agent_messages:
                avatar = "🤖" if msg["role"] == "assistant" else "👤"
                with st.chat_message(msg["role"], avatar=avatar):
                    st.markdown(msg["content"])

        # Input Area
        if prompt := st.chat_input("Ask about sales, stock, or your uploaded files..."):
            # 1. Add user message
            st.session_state.agent_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user", avatar="👤"):
                st.markdown(prompt)

            # 2. Get AI Response
            with st.chat_message("assistant", avatar="🤖"):
                response_placeholder = st.empty()
                full_response = ""

                agent = AIDataAgent(provider, api_key, model_name)
                intent_obj = agent.brain.semantic_query_intent(prompt)
                st.session_state.pilot_last_intent = intent_obj["type"]

                # Optimized Async Bridge for Streamlit
                async def run_streaming():
                    nonlocal full_response
                    try:
                        async for chunk in agent.get_response_stream(prompt, st.session_state.agent_messages[:-1]):
                            full_response += chunk
                            response_placeholder.markdown(full_response + "▌")
                        response_placeholder.markdown(full_response)
                    except Exception as e:
                        st.error(f"Streaming Error: {e}")

                # Safe Loop Execution
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import threading
                        def thread_run():
                            new_loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(new_loop)
                            new_loop.run_until_complete(run_streaming())

                        t = threading.Thread(target=thread_run)
                        t.start()
                        t.join()
                    else:
                        loop.run_until_complete(run_streaming())
                except Exception:
                    asyncio.run(run_streaming())

            # 3. Save assistant message
            st.session_state.agent_messages.append({"role": "assistant", "content": full_response})

            # 4. Optional: Insights Chip
            if len(full_response) > 50:
                with st.expander("🔍 Intelligence Layer: Brain Routing"):
                    st.caption(f"Engine: {provider} | Semantic Intent: {intent_obj['type'].upper()}")
                    st.info("Grounding: Utilizing Multi-Model Predictive Intelligence & Z-Score Anomaly detection for result grounding.")
