import streamlit as st
import pandas as pd
import asyncio
import re
import io
import os
from datetime import datetime
import plotly.express as px
from typing import Dict, List

from src.components.empty_state import render_empty_state
from src.config.constants import DATA_DIR
from src.config.settings import load_secrets_schema
# Add direct WooCommerce sync imports
from src.services.woocommerce.client import load_live_source
from src.services.woocommerce.stock import fetch_woocommerce_stock

# Vectorization for RAG
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

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

class AgenticMemory:
    """Structured Key-Value memory for the AI Agent."""
    def __init__(self, filepath=None):
        if filepath is None:
            filepath = os.path.join(DATA_DIR, "pilot_memory.json")
        self.filepath = filepath
        self.memory = self._load()

    def _load(self) -> Dict[str, str]:
        if os.path.exists(self.filepath):
            try:
                import json
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except: return {}
        return {}

    def save(self):
        import json
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, indent=4)

    def set_memory(self, key: str, value: str):
        self.memory[key] = value
        self.save()

    def delete_memory(self, key: str):
        if key in self.memory:
            del self.memory[key]
            self.save()

    def get_formatted_knowledge(self) -> str:
        if not self.memory: return ""
        lines = [f"  * {k.upper()}: {v}" for k, v in self.memory.items()]
        return "KNOWLEDGE_TYPE: Learned Operational Rules\n" + "\n".join(lines)

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
        self.agent_memory = AgenticMemory()
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
        self.app_knowledge = self._load_app_knowledge()
        self.vectorizer = TfidfVectorizer(stop_words='english', lowercase=True)

    def _load_app_knowledge(self) -> List[str]:
        """Loads project blueprints, source code logic, and API schemas into the knowledge base."""
        knowledge = []
        # 1. Core Documentation & Blueprints
        docs = ["agent.md", "README.md", "data_pilot.md", "DEAD_CODE_REPORT.md", "ERROR_HANDLING_GUIDE.md", "DEVELOPMENT.md"]
        for doc in docs:
            if os.path.exists(doc):
                try:
                    with open(doc, "r", encoding="utf-8") as f:
                        knowledge.append(f"KNOWLEDGE_TYPE: Documentation | FILE: {doc}\n{f.read()[:4000]}")
                except: pass
        
        # 1.1 Persistent User-Taught Rules (Memory)
        mem_str = self.agent_memory.get_formatted_knowledge()
        if mem_str:
            knowledge.append(mem_str)
        
        # 2. REST API Schema & Contracts (Answers 'rest api data' context)
        try:
            schema = load_secrets_schema()
            if schema:
                knowledge.append(f"KNOWLEDGE_TYPE: REST API Definition & Secrets Schema\n{str(schema)}")
        except: pass
            
        # 3. Source Code Logic (Sampling key orchestration files)
        src_samples = [
            "src/config/constants.py",
            "src/config/settings.py",
            "src/processing/data_processing.py",
            "src/services/woocommerce/client.py",
            "src/services/pathao/client.py",
            "src/services/llm/manager.py",
            "app.py"
        ]
        for src in src_samples:
            if os.path.exists(src):
                try:
                    with open(src, "r", encoding="utf-8") as f:
                        knowledge.append(f"KNOWLEDGE_TYPE: Source Code Architecture | FILE: {src}\n{f.read()[:3000]}")
                except: pass
        return knowledge

    def _get_vector_context(self, query: str, top_k: int = 20) -> str:
        """
        Performs RAG retrieval by vectorizing dataframe rows and app-level knowledge,
        finding the most semantically relevant items to the query.
        """
        documents = []
        
        # 1. Include static App Knowledge (Docs/Source/API Schema)
        documents.extend(self.app_knowledge)
        
        # 2. Flatten DataFrames into searchable text documents
        for name, df in self.context_dfs.items():
            if df is not None and not df.empty:
                # Limit RAG context size for performance; focus on most recent if possible
                working_df = df.tail(500) if len(df) > 500 else df
                
                # Optimized Vectorized String Construction (10x+ faster than iterrows)
                str_df = working_df.astype(str).replace("nan", "")
                text_series = pd.Series([f"Source: {name} | "] * len(str_df), index=str_df.index)
                
                for col in str_df.columns:
                    text_series += f"{col}: " + str_df[col] + " | "
                documents.extend(text_series.tolist())
        
        if not documents:
            return ""

        try:
            # 2. Vectorize the knowledge base
            tfidf_matrix = self.vectorizer.fit_transform(documents)
            
            # 3. Vectorize the query
            query_vec = self.vectorizer.transform([query])
            
            # 4. Compute Similarity
            cosine_sim = cosine_similarity(query_vec, tfidf_matrix).flatten()
            
            # 5. Retrieve top K matches
            related_indices = cosine_sim.argsort()[-top_k:][::-1]
            
            relevant_chunks = []
            for idx in related_indices:
                if cosine_sim[idx] > 0.05: # Threshold to filter out irrelevant noise
                    relevant_chunks.append(documents[idx])
            
            if relevant_chunks:
                return "\nRELEVANT DATA RECORDS FOUND:\n" + "\n".join(relevant_chunks)
            return ""
        except Exception as e:
            return f"\n(RAG Retrieval Error: {str(e)})\n"

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

        # RAG Retrieval: Vectorized context injection
        rag_context = self._get_vector_context(query)
        if rag_context:
            insights.append(rag_context)

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
                "ALWAYS provide a direct, conversational explanation to the user before executing any actions or queries. Do not just output action tags silently.\n"
                "\n\nCRITICAL RULES:\n"
                "1. Order Logic: An `order_id` represents a single unique order. An order may contain multiple item lines. You must NEVER count item rows as a single order. When asked for 'total orders' or 'number of orders', you must use distinct counts of `order_id`.\n"
                "2. Continuous Learning Protocol: If a user corrects a mistake you make regarding this logic (or any other data relationship), you must immediately internalize this correction.\n"
                "3. Auto-Memorization: If the user corrects a mistake or provides a new rule, you MUST output the exact string `[MEMORY_SET: <topic_key> | <the new rule details>]` on a new line to permanently remember it. Use concise snake_case for the topic_key.\n"
                "4. SQL Analytics: To run complex aggregations on the full dataset, output exactly `[SQL_QUERY: <your DuckDB SQL here>]`. The table name is `sales_data`. Use double quotes for column names with spaces, e.g., `\"Total Amount\"`. I will execute it and display the results. Example: `[SQL_QUERY: SELECT Category, SUM(\"Total Amount\") FROM sales_data GROUP BY Category]`.\n"
                "5. Chart Generation: To visualize data, output exactly `[PLOTLY_CODE: <python code>]`. Assume `df` is the raw sales dataframe and `px` is imported. If you also run a `[SQL_QUERY: ...]` in the same response, the result will be available as `sql_df`. Create a figure variable named `fig`. Example: `[PLOTLY_CODE: fig = px.bar(sql_df, x='Category', y='Total Amount')]`.\n"
                "6. Data Transformation: To apply data cleaning to the live sales data, output `[DATA_TRANSFORM: <python code>]`. Assume `df` is the active dataframe. Example: `[DATA_TRANSFORM: df['Status'] = df['Status'].str.title()]`. This safely updates the in-memory data for the user.\n"
                "7. Data Export: To provide a download button for the current active sales dataset (especially after cleaning), output exactly `[DOWNLOAD_DATA]`.\n"
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
def _filter_action_tags(text: str) -> str:
    """Remove action tags (MEMORY_SET, SQL_QUERY, PLOTLY_CODE, etc.) from display text."""
    text = re.sub(r'\[MEMORY_SET:.*?\]', '', text)
    text = re.sub(r'\[SQL_QUERY:.*?\]', '', text, flags=re.DOTALL)
    text = re.sub(r'\[PLOTLY_CODE:.*?\]', '', text, flags=re.DOTALL)
    text = re.sub(r'\[DATA_TRANSFORM:.*?\]', '', text, flags=re.DOTALL)
    text = re.sub(r'\[DOWNLOAD_DATA\]', '', text, flags=re.IGNORECASE)
    return text


def _stream_agent_response(agent, prompt, response_placeholder):
    """Stream agent response via async queue and return the full response text."""
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

    full_response = ""
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

        display_text = _filter_action_tags(full_response)
        response_placeholder.markdown(display_text + "▌")
        if done_flag:
            break
        time.sleep(0.05)

    t.join()
    return _filter_action_tags(full_response).strip()


def _execute_action_tags(full_response: str, agent):
    """Execute SQL, Plotly, and Data Transform action tags from the AI response."""
    import numpy as np

    last_sql_df = None

    sql_queries = re.findall(r'\[SQL_QUERY:\s*(.*?)\s*\]', full_response, flags=re.DOTALL)
    if sql_queries:
        from src.processing.hybrid_data_loader import HybridDataLoader
        loader = HybridDataLoader()
        for sql in sql_queries:
            st.info(f"⚙️ **Executing DuckDB SQL:**\n```sql\n{sql.strip()}\n```")
            df_res = loader.query_sql(sql.strip())
            if df_res is not None and not df_res.empty:
                last_sql_df = df_res
                st.dataframe(df_res, use_container_width=True)
                st.session_state.agent_messages.append({
                    "role": "system",
                    "content": f"System executed your SQL query: {sql}\n\nResult:\n{df_res.head(50).to_csv(index=False)}"
                })
            else:
                st.warning("SQL query returned no results or encountered an error.")
                st.session_state.agent_messages.append({
                    "role": "system",
                    "content": f"System executed your SQL query: {sql}\n\nResult: Query Failed or Empty."
                })

    plotly_codes = re.findall(r'\[PLOTLY_CODE:\s*(.*?)\s*\]', full_response, flags=re.DOTALL)
    if plotly_codes:
        for code in plotly_codes:
            st.info(f"📊 **Rendering Auto-Generated Chart:**\n```python\n{code.strip()}\n```")
            try:
                local_vars = {"df": agent.context_dfs.get("sales", pd.DataFrame()), "px": px}
                if last_sql_df is not None:
                    local_vars["sql_df"] = last_sql_df
                exec(code.strip(), globals(), local_vars)
                if "fig" in local_vars:
                    st.plotly_chart(local_vars["fig"], use_container_width=True)
            except Exception as e:
                st.error(f"Chart Generation Error: {e}")

    transform_codes = re.findall(r'\[DATA_TRANSFORM:\s*(.*?)\s*\]', full_response, flags=re.DOTALL)
    if transform_codes:
        for code in transform_codes:
            st.info(f"🧹 **Applying Data Transformation:**\n```python\n{code.strip()}\n```")
            try:
                target_df = st.session_state.get("wc_curr_df")
                if target_df is not None:
                    local_vars = {"df": target_df.copy(), "pd": pd, "np": np}
                    exec(code.strip(), {"__builtins__": __builtins__}, local_vars)
                    st.session_state.wc_curr_df = local_vars["df"]
                    st.toast("✅ Data transformation applied successfully to the live session!")
                    agent.context_dfs["sales"] = local_vars["df"]
                else:
                    st.warning("No live data found to transform.")
            except Exception as e:
                st.error(f"Data Transformation Error: {e}")

    if re.search(r'\[DOWNLOAD_DATA\]', full_response, flags=re.IGNORECASE):
        target_df = st.session_state.get("wc_curr_df")
        if target_df is not None and not target_df.empty:
            csv_data = target_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Cleaned Dataset (CSV)",
                data=csv_data,
                file_name=f"DEEN_Data_Export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        else:
            st.warning("No live data available to download.")


def _handle_auto_sync(auto_sync: bool):
    """Perform smart auto-sync if enabled and data is stale."""
    if not auto_sync:
        return
    last_sync = st.session_state.get("live_sync_time")
    if last_sync and (datetime.now() - last_sync).total_seconds() <= 900:
        return

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


def _handle_audio_input():
    """Handle audio input transcription and return the transcribed prompt."""
    if not hasattr(st, "audio_input"):
        return None

    audio_bytes = st.audio_input("Speak to Data Pilot", label_visibility="collapsed")
    if not audio_bytes or audio_bytes == st.session_state.get("last_audio_bytes"):
        return None

    st.session_state.last_audio_bytes = audio_bytes
    with st.spinner("🎧 Transcribing audio command..."):
        from src.services.llm.manager import init_llm_controller
        controller = init_llm_controller()
        transcription = controller.transcribe_audio(audio_bytes.getvalue())

    if transcription and not transcription.startswith("*(Failed"):
        return transcription
    else:
        st.session_state.agent_messages.append({"role": "user", "content": "*(🎤 Voice Command Captured)*"})
        st.session_state.agent_messages.append({"role": "assistant", "content": transcription})
        return None


def _render_chat_tab(provider, api_key, model_name, auto_sync):
    """Render the Pilot Interface chat tab."""
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
        st.markdown("""<script>
document.addEventListener('keydown', function(e) {
    if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
        e.preventDefault();
        const inp = document.querySelector('[data-testid="stChatInput"] textarea');
        if (inp) inp.focus();
    }
});
</script>""", unsafe_allow_html=True)
        prompt = _handle_audio_input()
        if not prompt:
            prompt = st.chat_input("Ask Data Pilot about sales, stock, or request a report...")

        original_nav = st.session_state.get("_nav_override")

        if prompt:
            _handle_auto_sync(auto_sync)
            st.session_state.agent_messages.append({"role": "user", "content": prompt})

        chat_container = st.container(height=500)
        with chat_container:
            for msg in st.session_state.agent_messages:
                if msg["role"] == "system":
                    continue
                avatar = "🤖" if msg["role"] == "assistant" else "👤"
                with st.chat_message(msg["role"], avatar=avatar):
                    st.markdown(msg["content"])
                    if "audio" in msg and msg.get("audio"):
                        st.audio(msg["audio"])

            if prompt:
                with st.chat_message("assistant", avatar="🤖"):
                    response_placeholder = st.empty()

                    agent = AIDataAgent(provider, api_key, model_name)
                    intent_obj = agent.brain.semantic_query_intent(prompt)
                    st.session_state.pilot_last_intent = intent_obj["type"]

                    if "report" in prompt.lower() or "summary" in prompt.lower():
                        st.session_state.pilot_last_intent = "report_generation"

                    full_response = _stream_agent_response(agent, prompt, response_placeholder)
                    response_placeholder.markdown(full_response)

                    updates = re.findall(r'\[MEMORY_SET:\s*(.*?)\s*\|\s*(.*?)\]', full_response)
                    if updates:
                        for key, rule in updates:
                            agent.agent_memory.set_memory(key.strip(), rule.strip())
                        st.toast("🧠 Pilot internalized a new rule to long-term memory!", icon="✅")

                    st.session_state.agent_messages.append({"role": "assistant", "content": full_response})

                    _execute_action_tags(full_response, agent)

                st.markdown('<div id="pilot-chat-bottom"></div>', unsafe_allow_html=True)
                st.markdown(
                    """
                    <script>
                        setTimeout(function() {
                            var el = window.parent.document.getElementById('pilot-chat-bottom');
                            if (el) {
                                el.scrollIntoView({behavior: 'smooth', block: 'end'});
                            }
                        }, 100);
                    </script>
                    """,
                    unsafe_allow_html=True
                )

        if prompt:
            if original_nav and "_nav_override" not in st.session_state:
                st.session_state["_nav_override"] = original_nav

            if st.session_state.get("pilot_last_intent") == "report_generation":
                st.session_state.pilot_reports.append({
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "content": full_response
                })

            st.rerun()


def _sync_from_woocommerce():
    st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
    with st.status("Syncing live data...", expanded=True) as status:
        try:
            status.write("📡 Fetching live orders...")
            load_live_source()
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


def _sync_pathao_statuses():
    st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
    with st.status("Syncing Pathao statuses...", expanded=True) as status:
        try:
            status.write("Finding order data...")
            orders_df = st.session_state.get("wc_full_df")
            if orders_df is None or orders_df.empty:
                orders_df = st.session_state.get("wc_curr_df")

            if orders_df is None or orders_df.empty:
                st.error("No WooCommerce order data found. Please sync from WooCommerce first.")
                status.update(label="Sync Failed", state="error")
                st.stop()

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

            status.write(f"Fetching {len(unique_consignments)} statuses from Pathao...")
            results = []
            progress_bar = st.progress(0)
            for i, cid in enumerate(unique_consignments):
                res = get_pathao_order_status(cid)
                results.append(res)
                progress_bar.progress((i + 1) / len(unique_consignments))

            st.session_state.pilot_pathao_tracking_df = pd.DataFrame(results)
            status.update(label="Pathao Sync Complete!", state="complete", expanded=False)
            st.toast(f"✅ Synced {len(results)} Pathao statuses.")
            st.rerun()
        except Exception as e:
            status.update(label="Sync Failed", state="error")
            st.error(f"Failed to sync Pathao statuses: {e}")


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
            _sync_from_woocommerce()

        if st.button("🔄 Sync Pathao Statuses", use_container_width=True):
            _sync_pathao_statuses()

        if "pilot_uploader_key" not in st.session_state:
            st.session_state.pilot_uploader_key = 0
            
        up_file = st.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"], key=f"pilot_up_{st.session_state.pilot_uploader_key}")
        if up_file:
            try:
                df = pd.read_csv(up_file) if up_file.name.endswith('.csv') else pd.read_excel(up_file)
                st.session_state.pilot_uploaded_df = df
                st.toast(f"📥 Ingested {len(df)} records.")
            except Exception as e:
                st.error(f"Failed to parse file: {e}")

        uploaded_df = st.session_state.get("pilot_uploaded_df")
        pathao_track_df = st.session_state.get("pilot_pathao_tracking_df")
        if (uploaded_df is not None and not uploaded_df.empty) or (pathao_track_df is not None and not pathao_track_df.empty):
            if st.button("Clear Knowledge Base", use_container_width=True):
                st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
                st.session_state.pilot_uploaded_df = None
                st.session_state.pilot_pathao_tracking_df = None
                st.session_state.pilot_uploader_key += 1
                st.rerun()

    return provider, api_key, model_name, auto_sync

def _render_knowledge_base_tab():
    """Render the Knowledge Base tab with data context previews."""
    st.markdown("### 📂 Data Context")
    st.markdown("The AI currently has access to the following dataframes to ground its answers:")

    col1, col2 = st.columns(2)

    with col1:
        sales_df = st.session_state.get("wc_curr_df")
        if sales_df is not None and not sales_df.empty:
            st.caption(f"📈 **Live Sales** — {len(sales_df)} rows")
            st.dataframe(sales_df.head(3), use_container_width=True, hide_index=True)
        else:
            render_empty_state("📈", "Live Sales", "Sync data from WooCommerce to see live sales here.", "Sync Now", "kb_es_sales", lambda: setattr(st.session_state, "_sync_clicked", True))

        inv_df = st.session_state.get("inv_res_data")
        if inv_df is not None and not inv_df.empty:
            st.caption(f"📦 **Inventory Distribution** — {len(inv_df)} rows")
            st.dataframe(inv_df.head(3), use_container_width=True, hide_index=True)
        else:
            render_empty_state("📦", "Inventory Distribution", "Inventory data will appear after distribution analysis.", "", "kb_es_inv")

        pathao_df = st.session_state.get("pathao_res_df")
        if pathao_df is not None and not pathao_df.empty:
            st.caption(f"🚚 **Pathao Dispatch** — {len(pathao_df)} rows")
            st.dataframe(pathao_df.head(3), use_container_width=True, hide_index=True)
        else:
            render_empty_state("🚚", "Pathao Dispatch", "Process Pathao orders to see dispatch data here.", "", "kb_es_pathao")

    with col2:
        stock_df = st.session_state.get("wc_stock_df")
        if stock_df is not None and not stock_df.empty:
            st.caption(f"🏢 **Stock Levels** — {len(stock_df)} rows")
            st.dataframe(stock_df.head(3), use_container_width=True, hide_index=True)
        else:
            render_empty_state("🏢", "Stock Levels", "Stock data will appear after inventory sync.", "", "kb_es_stock")

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
            render_empty_state("📍", "Pathao Tracking", "Track Pathao consignments to see data here.", "", "kb_es_tracking")

        up_df = st.session_state.get("pilot_uploaded_df")
        if up_df is not None and not up_df.empty:
            st.caption(f"📁 **Uploaded Files** — {len(up_df)} rows")
            st.dataframe(up_df.head(3), use_container_width=True, hide_index=True)
        else:
            render_empty_state("📁", "Uploaded Files", "Upload files to see them here.", "", "kb_es_files")

    rag_analysis = st.session_state.get("pilot_latest_rag_analysis")
    if rag_analysis:
        st.divider()
        st.markdown("### 🔍 Semantic Match Map")
        st.caption("Visualizing retrieval scores from the last query.")
        df_rag = pd.DataFrame(rag_analysis).sort_values("Score", ascending=True)
        fig_rag = px.bar(
            df_rag, x="Score", y="Data Point", orientation='h',
            title="Top-K Retrieval Confidence", color="Score", color_continuous_scale="Viridis"
        )
        fig_rag.update_layout(margin=dict(l=0, r=20, t=40, b=0), height=300 + (len(df_rag) * 15), showlegend=False, coloraxis_showscale=False)
        st.plotly_chart(fig_rag, use_container_width=True)


def _render_reports_tab():
    """Render the AI Generated Reports tab."""
    st.markdown("### 📑 AI Generated Reports")
    col_rep1, col_rep2 = st.columns(2)
    with col_rep1:
        if st.button("✨ Auto-Generate Executive Report", type="primary", use_container_width=True):
            st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
            st.session_state.agent_messages.append({"role": "user", "content": "Generate a comprehensive executive summary report covering current sales, stock levels, and fulfillment. Use professional formatting."})
            st.rerun()
    with col_rep2:
        if st.button("👥 Customer Segmentation Analysis", type="secondary", use_container_width=True):
            st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
            prompt = (
                "Using the available sales data, segment customers into 'First-Time', "
                "'Repeat', and 'High-Value' buckets based on their order history and phone numbers. "
                "Provide counts and revenue contribution for each segment. Present the result as a detailed markdown report."
            )
            st.session_state.agent_messages.append({"role": "user", "content": prompt})
            st.rerun()

    if not st.session_state.pilot_reports:
        st.info("No reports generated yet. Ask the Pilot to generate a report in the chat, or use the button above.")
    else:
        for idx, report in enumerate(reversed(st.session_state.pilot_reports)):
            with st.expander(f"Report: {report['date']}", expanded=(idx == 0)):
                st.markdown(report['content'])
                st.download_button("📥 Download Markdown", report['content'], file_name=f"Report_{report['date'].replace(':', '-')}.md", key=f"dl_rep_{idx}")


def _render_memory_tab():
    """Render the Agentic Long-Term Memory tab."""
    st.markdown("### 🧠 Agentic Long-Term Memory")
    st.caption("These are the persistent rules and logic the Pilot has learned. You can view, edit, or remove them manually.")

    memory_obj = AgenticMemory()
    memory_dict = memory_obj.memory

    if not memory_dict:
        st.info("The AI Pilot hasn't learned any custom rules yet. Teach it during chat by correcting its assumptions!")
    else:
        for key, val in list(memory_dict.items()):
            with st.expander(f"Rule: {key}", expanded=False):
                new_val = st.text_area("Rule Details", value=val, key=f"mem_edit_{key}")
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("💾 Save Changes", key=f"mem_save_{key}"):
                        memory_obj.set_memory(key, new_val)
                        st.toast("✅ Rule updated!")
                        st.rerun()
                with col2:
                    if st.button("🗑️ Delete Rule", key=f"mem_del_{key}", type="secondary"):
                        memory_obj.delete_memory(key)
                        st.warning("Rule deleted!")
                        st.rerun()

    st.divider()
    st.markdown("#### ➕ Add New Rule Manually")
    with st.form("add_manual_rule_form", clear_on_submit=True):
        new_key = st.text_input("Topic Key (e.g., return_policy)", placeholder="return_policy")
        new_rule = st.text_area("Rule Details", placeholder="Returns are accepted within 7 days...")
        if st.form_submit_button("Add Rule"):
            if new_key and new_rule:
                memory_obj.set_memory(new_key.strip(), new_rule.strip())
                st.toast("✅ New rule added to Pilot's memory!")
                st.rerun()
            else:
                st.error("Both key and details are required.")


def render_ai_pilot_page():
    """Main entry point for the Data Pilot page."""
    st.markdown(
        """
        <div style='text-align: center; margin-bottom: 2rem;'>
            <h1 style='color: #6366f1; margin-bottom: 0;'>🚀 GLOBAL DATA PILOT</h1>
            <p style='opacity: 0.7; font-size: 1.1rem;'>Enhanced Knowledge Base & ML Intelligence Engine</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [{"role": "assistant", "content": "Welcome to the Pilot's Seat. Ask me about sales, generate reports, or track Pathao live statuses!"}]
    if "pilot_reports" not in st.session_state:
        st.session_state.pilot_reports = []

    if "_nav_override" in st.session_state and st.session_state["_nav_override"] != ":material/rocket_launch: Data Pilot":
        st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"

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

    provider, api_key, model_name, auto_sync = render_sidebar_controls()

    tab_chat, tab_kb, tab_reports, tab_memory = st.tabs([
        ":material/chat: Pilot Interface", ":material/psychology: Knowledge Base",
        ":material/description: Generated Reports", ":material/memory: Learned Rules"
    ])

    with tab_kb:
        _render_knowledge_base_tab()
    with tab_reports:
        _render_reports_tab()
    with tab_memory:
        _render_memory_tab()
    with tab_chat:
        _render_chat_tab(provider, api_key, model_name, auto_sync)
