import streamlit as st
import pandas as pd
import requests
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from app_modules.sales_dashboard import get_setting
from app_modules.llm_manager import init_llm_controller

# ------------------------------
# 1. CORE AGENT LOGIC
# ------------------------------
class AIDataAgent:
    """
    Industry-Standard AI-BI Agent with Streaming & Data-Aware Context.
    Supports multi-provider failover, local data grounding, and agentic API calls.
    """
    def __init__(self, provider="Fallback", api_key=None, model_name=None):
        self.provider = provider
        self.api_key = api_key
        self.model_name = model_name
        self.controller = init_llm_controller()
        self.context_dfs = {
            "sales": st.session_state.get("wc_curr_df"),
            "inventory": st.session_state.get("inv_res_data"),
            "uploaded": st.session_state.get("pilot_uploaded_df"),
        }

    def detect_intent(self, query: str) -> str:
        q = query.lower()
        if any(word in q for word in ["sale", "revenue", "order", "conversion", "basket"]): return "sales"
        if any(word in q for word in ["inventory", "stock", "sku", "out of stock"]): return "inventory"
        if any(word in q for word in ["customer", "pull", "live", "recent", "api"]): return "agentic_api"
        if any(word in q for word in ["upload", "file", "csv", "excel", "this data"]): return "uploaded_file"
        return "general"

    def get_context_description(self, intent: str) -> str:
        base_desc = "System Overview: DEEN Intelligence Ops Terminal. "
        if intent == "sales":
            df = self.context_dfs["sales"]
            if df is not None and not df.empty:
                rev = df['total_amount'].sum() if 'total_amount' in df.columns else 0
                return base_desc + f"LIVE SALES CONTEXT: Total Revenue ৳{rev:,.0f}, Orders: {len(df)}."
        elif intent == "inventory":
            df = self.context_dfs["inventory"]
            if df is not None and not df.empty:
                low = len(df[df['Quantity'] < 10]) if 'Quantity' in df.columns else 0
                return base_desc + f"INVENTORY CONTEXT: {len(df)} unique SKUs, {low} items with critical low stock."
        elif intent == "uploaded_file":
            df = self.context_dfs["uploaded"]
            if df is not None and not df.empty:
                return base_desc + f"UPLOADED DATA CONTEXT: {len(df)} rows, Columns: {', '.join(df.columns[:8])}. Sample: {df.head(2).to_json()}"
        return base_desc + "Context: Operational general dashboard stats accessible."

    def build_messages(self, query: str, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        intent = self.detect_intent(query)
        context = self.get_context_description(intent)
        
        system_msg = {
            "role": "system", 
            "content": (
                "You are DEEN Intelligence Data Pilot, a premium business analyst. "
                "Provide sharp, data-driven insights. Be concise but professional. "
                f"Use this Context strictly: {context}"
            )
        }
        
        # Keep last 5 messages for sliding window context
        return [system_msg] + history[-5:] + [{"role": "user", "content": query}]

    async def get_response_stream(self, query: str, history: List[Dict[str, str]]):
        messages = self.build_messages(query, history)
        
        if self.provider == "🛡️ Smart Failover (Free Tiers)":
            async for chunk in self.controller.get_response_stream_async(messages):
                yield chunk
        else:
            # Fallback to sync controller for manual providers if stream not implemented
            # For industry standard, we'd implement full async for all, but for now we bridge
            yield self.controller.get_response_sync(messages)

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
            models = init_llm_controller().key_manager.get_local_models()
            if models:
                model_name = st.selectbox("Local Model", models)
            else:
                st.warning("Ollama unreachable. Run `ollama serve`.")
                model_name = st.text_input("Manual Model Name", value="llama3")

        if is_cloud:
            st.warning("☁️ **Cloud Mode**: Personal GPU engines (Ollama) restricted. Use Cloud Failover.")

        st.divider()
        st.markdown("### 📁 Knowledge Base")
        up_file = st.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"])
        if up_file:
            df = pd.read_csv(up_file) if up_file.name.endswith('.csv') else pd.read_excel(up_file)
            st.session_state.pilot_uploaded_df = df
            st.success(f"Ingested {len(df)} records.")
        
        if st.session_state.get("pilot_uploaded_df") is not None:
            if st.button("Clear Knowledge Base"):
                st.session_state.pilot_uploaded_df = None
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
                    # If loop is running, we need to bridge it. 
                    # Streamlit usually doesn't run the main script in the loop, but some components do.
                    # Best approach: Use a new thread or loop if nested doesn't work.
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
            with st.expander("🔍 Reasoning & Data Sources"):
                st.caption(f"Engine: {provider} | Intent: {agent.detect_intent(prompt)}")
                st.info("Grounding: Using operational context linked to WooCommerce and Inventory databases.")
