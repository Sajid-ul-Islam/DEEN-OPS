# llm_manager.py - Dynamic Multi-Provider LLM Manager for Free Tiers
import streamlit as st
import requests
import json
import time
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import threading

# ============================================
# 1. PROVIDER CONFIGURATIONS (All Free Tiers)
# ============================================

@dataclass
class ProviderConfig:
    name: str
    api_url: str
    model_name: str
    auth_type: str  # "bearer", "api_key", "x-api-key"
    rate_limit_per_minute: int
    daily_limit: int
    weight: int = 1  # For load balancing (higher = more requests)
    timeout: int = 30

PROVIDERS = {
    "openrouter": ProviderConfig(
        name="openrouter",
        api_url="https://openrouter.ai/api/v1/chat/completions",
        model_name="google/gemini-2.0-flash-exp:free",
        auth_type="bearer",
        rate_limit_per_minute=60,
        daily_limit=1500,
        weight=3
    ),
    "gemini_free": ProviderConfig(
        name="gemini_free",
        api_url="https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
        model_name="gemini-pro",
        auth_type="api_key",
        rate_limit_per_minute=60,
        daily_limit=1500,
        weight=2
    ),
    "groq_free": ProviderConfig(
        name="groq_free",
        api_url="https://api.groq.com/openai/v1/chat/completions",
        model_name="mixtral-8x7b-32768",
        auth_type="bearer",
        rate_limit_per_minute=30,
        daily_limit=1000,
        weight=1
    ),
    "ollama": ProviderConfig(
        name="ollama",
        api_url="http://localhost:11434/v1/chat/completions",
        model_name="llama3",
        auth_type="none",
        rate_limit_per_minute=100,  # High as it's local
        daily_limit=99999,
        weight=4,
        timeout=5  # Low timeout for local to fail fast
    ),
    "huggingface": ProviderConfig(
        name="huggingface",
        api_url="https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2",
        model_name="mistral-7b",
        auth_type="bearer",
        rate_limit_per_minute=10,
        daily_limit=1000,
        weight=1
    )
}

# ============================================
# 2. KEY & LOAD BALANCING LOGIC
# ============================================

class APIKeyManager:
    def __init__(self):
        self.keys: Dict[str, List[Dict]] = defaultdict(list)
        self._last_reset_date = datetime.now().date()
        self.load_keys_from_secrets()
    
    def load_keys_from_secrets(self):
        # Dynamically load from st.secrets if they exist
        for provider_key in ["OPENROUTER_KEYS", "GEMINI_KEYS", "GROQ_KEYS", "HF_KEYS"]:
            provider_id = provider_key.replace("_KEYS", "").lower()
            if "gemini" in provider_id: provider_id = "gemini_free"
            elif "groq" in provider_id: provider_id = "groq_free"
            elif "hf" in provider_id: provider_id = "huggingface"
            
            keys = st.secrets.get(provider_key, [])
            if isinstance(keys, str):
                keys = [keys]
            for key in keys:
                self.add_key(provider_id, key)
        
        # Add Ollama if reachable
        if self._check_ollama_alive():
            self.add_key("ollama", "local_no_key")

    def _check_ollama_alive(self) -> bool:
        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=1)
            return resp.status_code == 200
        except:
            return False

    def get_local_models(self) -> List[str]:
        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=2)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return [m["name"] for m in models]
        except:
            pass
        return []

    def add_key(self, provider: str, api_key: str):
        self.keys[provider].append({
            "key": api_key,
            "usage_today": 0,
            "rate_limit_reset": time.time(),
            "requests_this_minute": 0,
            "healthy": True
        })
    
    def get_next_key(self, provider: str) -> Optional[Tuple[str, Dict]]:
        if provider not in self.keys: return None
        now = time.time()
        for key in self.keys[provider]:
            if key["healthy"] and key["requests_this_minute"] < PROVIDERS[provider].rate_limit_per_minute:
                key["requests_this_minute"] += 1
                key["usage_today"] += 1
                return key["key"], key
        return None

class AdaptiveLoadBalancer:
    def __init__(self):
        self.provider_stats = defaultdict(lambda: {"success_rate": 1.0, "avg_latency": 1.0})
    
    def select_provider(self, available_providers: List[str]) -> str:
        if not available_providers: return "openrouter"
        scores = {p: PROVIDERS[p].weight * self.provider_stats[p]["success_rate"] for p in available_providers}
        return max(scores, key=scores.get)

    def record_result(self, provider: str, success: bool, latency: float):
        stats = self.provider_stats[provider]
        alpha = 0.1
        stats["success_rate"] = alpha * (1.0 if success else 0.0) + (1 - alpha) * stats["success_rate"]
        stats["avg_latency"] = alpha * latency + (1 - alpha) * stats["avg_latency"]

# ============================================
# 3. CONTROLLER
# ============================================

class DynamicLLMController:
    def __init__(self):
        self.key_manager = APIKeyManager()
        self.load_balancer = AdaptiveLoadBalancer()
        # Robust Cloud Detection
        try:
            # Check for Streamlit Cloud specific secrets or environment markers
            is_on_cloud = st.secrets.get("is_cloud", False)
            if not is_on_cloud:
                # Check for platform-specific env vars
                import os
                is_on_cloud = os.getenv("STREAMLIT_CLOUD_ID") is not None or \
                              os.getenv("HOSTNAME") == "streamlit"
            self.is_cloud = is_on_cloud
        except:
             self.is_cloud = False

    async def _call_provider_stream_async(self, provider: str, api_key: str, messages: List[Dict[str, str]]) -> Any:
        config = PROVIDERS[provider]
        
        if provider == "gemini_free":
            # Gemini non-streaming for now in this manager, but we'll adapt
            payload = {"contents": [{"parts": [{"text": m["content"]}]} for m in messages]}
            headers = {"x-goog-api-key": api_key}
            full_url = f"{config.api_url}?key={api_key}"
            async with aiohttp.ClientSession() as session:
                async with session.post(full_url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        yield data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            payload = {
                "model": config.model_name,
                "messages": messages,
                "stream": True
            }
            headers = {"Authorization": f"Bearer {api_key}"} if config.auth_type == "bearer" else {"x-api-key": api_key}
            full_url = config.api_url

            async with aiohttp.ClientSession() as session:
                async with session.post(full_url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        async for line in response.content:
                            line = line.decode('utf-8').strip()
                            if line.startswith("data: "):
                                if line == "data: [DONE]": break
                                try:
                                    content = json.loads(line[6:])
                                    delta = content["choices"][0]["delta"].get("content", "")
                                    if delta: yield delta
                                except: continue
                    else:
                        yield f"Error: {response.status}"

    async def get_response_stream_async(self, messages: List[Dict[str, str]]) -> Any:
        available_providers = [p for p in PROVIDERS.keys() if p in self.key_manager.keys]
        if not available_providers: 
            yield "No active LLM providers. Check settings."
            return
        
        selected = self.load_balancer.select_provider(available_providers)
        key_res = self.key_manager.get_next_key(selected)
        if not key_res: 
            yield "All keys exhausted."
            return
            
        api_key, _ = key_res
        async for chunk in self._call_provider_stream_async(selected, api_key, messages):
            yield chunk

    def get_response_sync(self, messages: List[Dict[str, str]]) -> str:
        async def _run():
            full_text = ""
            async for chunk in self.get_response_stream_async(messages):
                full_text += chunk
            return full_text
            
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import threading
                result = []
                def thread_run():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    result.append(new_loop.run_until_complete(_run()))
                
                t = threading.Thread(target=thread_run)
                t.start()
                t.join()
                return result[0] if result else ""
            else:
                return loop.run_until_complete(_run())
        except Exception:
            # Last resort
            try:
                loop = asyncio.new_event_loop()
                return loop.run_until_complete(_run())
            except:
                return "Error: Async bridge failed."

def init_llm_controller():
    # Force re-init if old controller is detected
    if "llm_controller" in st.session_state:
        # Check for the latest method/signature change indicator
        if not hasattr(st.session_state.llm_controller, "is_cloud"):
            del st.session_state.llm_controller
            
    if "llm_controller" not in st.session_state:
        st.session_state.llm_controller = DynamicLLMController()
    return st.session_state.llm_controller
