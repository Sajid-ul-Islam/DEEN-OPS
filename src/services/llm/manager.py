# llm_manager.py - Dynamic Multi-Provider LLM Manager for Free Tiers
import streamlit as st
import requests
import json
import time
import asyncio
import aiohttp
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import threading

from src.config.settings import get_llm_provider_keys
from src.utils.logging import log_system_event

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
        rate_limit_per_minute=20,
        daily_limit=200,
        weight=3
    ),
    "gemini_free": ProviderConfig(
        name="gemini_free",
        api_url="https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        model_name="gemini-1.5-flash",
        auth_type="api_key",
        rate_limit_per_minute=15,
        daily_limit=1500,
        weight=2
    ),
    "groq_free": ProviderConfig(
        name="groq_free",
        api_url="https://api.groq.com/openai/v1/chat/completions",
        model_name="llama-3.3-70b-versatile",
        auth_type="bearer",
        rate_limit_per_minute=30,
        daily_limit=14400,
        weight=5
    ),
    "ollama": ProviderConfig(
        name="ollama",
        api_url="http://localhost:11434/v1/chat/completions",
        model_name="llama3.2",
        auth_type="none",
        rate_limit_per_minute=100,
        daily_limit=99999,
        weight=4,
        timeout=5
    ),
    "huggingface": ProviderConfig(
        name="huggingface",
        api_url="https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3",
        model_name="mistral-7b-v0.3",
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
    def __init__(self, is_cloud: bool = False):
        self.keys: Dict[str, List[Dict]] = defaultdict(list)
        self._last_reset_date = datetime.now().date()
        self.is_cloud = is_cloud
        self.load_keys_from_secrets()

    def load_keys_from_secrets(self):
        # Support the new [llm] section and legacy top-level secrets.
        for provider_id, keys in get_llm_provider_keys().items():
            for key in keys:
                self.add_key(provider_id, key)

        # Add Ollama if reachable and not on cloud
        if not self.is_cloud and self._check_ollama_alive():
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

        self.key_manager = APIKeyManager(is_cloud=self.is_cloud)

        # Caching & Token Tracking
        self.response_cache: Dict[str, str] = {}
        self.total_tokens_estimated: int = 0

    def _get_cache_key(self, messages: List[Dict[str, str]]) -> str:
        msg_str = json.dumps(messages, sort_keys=True)
        return hashlib.md5(msg_str.encode()).hexdigest()

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def transcribe_audio(self, audio_bytes: bytes) -> str:
        """Transcribe audio using Groq Whisper API (whisper-large-v3-turbo)."""
        key_res = self.key_manager.get_next_key("groq_free")
        if key_res:
            api_key, _ = key_res
            try:
                import requests
                url = "https://api.groq.com/openai/v1/audio/transcriptions"
                headers = {"Authorization": f"Bearer {api_key}"}
                files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
                data = {"model": "whisper-large-v3-turbo"}
                resp = requests.post(url, headers=headers, files=files, data=data, timeout=15)
                if resp.status_code == 200:
                    return resp.json().get("text", "").strip()
                else:
                    log_system_event("AUDIO_API_ERROR", f"Groq Whisper failed: {resp.status_code} - {resp.text}")
            except Exception as e:
                log_system_event("AUDIO_API_ERROR", f"Groq Whisper exception: {e}")
                
        return "*(Failed to transcribe audio. Ensure Groq API key is configured.)*"

    async def _call_provider_stream_async(self, provider: str, api_key: str, messages: List[Dict[str, str]]) -> Any:
        config = PROVIDERS[provider]

        if provider == "gemini_free":
            # Gemini v1beta expects specific role mapping: user/model
            gemini_messages = []
            system_instruction = ""
            
            for m in messages:
                if m["role"] == "system":
                    system_instruction += m["content"] + "\n"
                else:
                    role = "user" if m["role"] == "user" else "model"
                    gemini_messages.append({"role": role, "parts": [{"text": m["content"]}]})
            
            # If we have a system instruction, prepend it to the first user message for better compatibility
            if system_instruction and gemini_messages:
                gemini_messages[0]["parts"][0]["text"] = f"[SYSTEM INSTRUCTION]\n{system_instruction}\n\n[USER QUERY]\n" + gemini_messages[0]["parts"][0]["text"]

            payload = {"contents": gemini_messages}
            headers = {"Content-Type": "application/json"}
            full_url = f"{config.api_url}?key={api_key}"
            async with aiohttp.ClientSession() as session:
                async with session.post(full_url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        try:
                            # v1beta structure: candidates[0].content.parts[0].text
                            text = data["candidates"][0]["content"]["parts"][0]["text"]
                            yield text
                        except (KeyError, IndexError):
                            yield "Error: Unexpected Gemini API response format."
                    else:
                        yield f"Error: {response.status}"
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
            yield "No active LLM nodes found. Please configure API keys in secrets.toml."
            return

        cache_key = self._get_cache_key(messages)
        if cache_key in self.response_cache:
            log_system_event("LLM_CACHE_HIT", f"Returning cached response. Cache size: {len(self.response_cache)}")
            cached_text = self.response_cache[cache_key]
            chunk_size = max(1, len(cached_text) // 20)
            for i in range(0, len(cached_text), chunk_size):
                yield cached_text[i:i+chunk_size]
                await asyncio.sleep(0.01)
            return

        # Attempt up to 3 different providers on failure
        tried = set()
        for attempt in range(min(3, len(available_providers))):
            selected = self.load_balancer.select_provider([p for p in available_providers if p not in tried])
            tried.add(selected)
            
            key_res = self.key_manager.get_next_key(selected)
            if not key_res: continue
            
            api_key, meta = key_res
            start_time = time.time()
            success = False
            
            try:
                has_yielded = False
                full_response = ""
                async for chunk in self._call_provider_stream_async(selected, api_key, messages):
                    if isinstance(chunk, str) and chunk.startswith("Error:"):
                        # If it's a 4xx/5xx error string, don't yield yet, try next provider
                        log_system_event("LLM_API_ERROR", f"Provider '{selected}' returned status: {chunk}")
                        break
                    full_response += chunk
                    yield chunk
                    has_yielded = True
                
                if has_yielded:
                    success = True
                    self.load_balancer.record_result(selected, True, time.time() - start_time)
                    self.response_cache[cache_key] = full_response
                    input_chars = sum(len(m.get("content", "")) for m in messages)
                    self.total_tokens_estimated += self._estimate_tokens(full_response) + (input_chars // 4)
                    return
            except Exception as e:
                self.load_balancer.record_result(selected, False, time.time() - start_time)
                log_system_event("LLM_API_ERROR", f"Provider '{selected}' raised exception: {e}")
                continue
            
        yield "All available AI nodes returned an error or are busy. Please check your API keys or try again later."

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
                from streamlit.runtime.scriptrunner import add_script_run_ctx
                add_script_run_ctx(t)
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
            except Exception:
                return "Error: Async bridge failed."

def init_llm_controller():
    # Force re-init if old controller is detected
    if "llm_controller" in st.session_state:
        # Check for the latest method/signature change indicator
        if not hasattr(st.session_state.llm_controller, "is_cloud") or not hasattr(st.session_state.llm_controller, "transcribe_audio"):
            del st.session_state.llm_controller

    if "llm_controller" not in st.session_state:
        st.session_state.llm_controller = DynamicLLMController()
    return st.session_state.llm_controller
