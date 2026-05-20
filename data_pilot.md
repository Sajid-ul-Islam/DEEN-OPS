# 🚀 Data Pilot Agent Guide

**Data Pilot** is the conversational AI assistant built into DEEN-OPS Terminal. It allows operators to query live e-commerce data, generate insights, and automate routine communications using natural language.

## 🧠 Core Architecture

Data Pilot is powered by the `DynamicLLMController` (`src/services/llm/manager.py`), which features:
- **Multi-Provider Failover**: Automatically routes requests between OpenRouter, Gemini, Groq, and local Ollama nodes based on availability.
- **Adaptive Load Balancing**: Scores providers by success rate and latency to optimize response times.
- **Session Caching**: Caches identical queries to prevent redundant API calls and save tokens.
- **Token Estimation**: Tracks approximate token usage across sessions for cost monitoring.

## 🛠️ Key Capabilities

### 1. WhatsApp Message Generation
Data Pilot uses contextual prompts to generate gender-aware, polite WhatsApp messages in Bengali/English for order confirmations, delays, and address verification.

### 2. Inventory Distribution Intelligence
By analyzing the `inventory_matrix`, Data Pilot can recommend optimal dispatch locations (e.g., "Ecom-Mirpur" vs "Wari") to minimize split shipments and stockouts.

### 3. Sales & Revenue Explanations
Instead of just visualizing data, Data Pilot explains anomalies in the `live_dashboard` (e.g., sudden drops in AOV or spikes in specific product categories).

## 📝 Example Prompts

- *"Draft a polite WhatsApp message to this customer asking for their exact Thana and District. The order is pre-paid via bKash."*
- *"Why did our gross revenue drop yesterday compared to the previous operational slot?"*
- *"Which warehouse should we dispatch order #199151 from to avoid splitting the parcel?"*

## ⚙️ Adding Custom Tools
To extend Data Pilot's capabilities:
1. Add the data extraction logic in `src/processing/`.
2. Pass the sanitized data context as a system prompt prefix in `src/pages/data_pilot.py`.
3. Ensure the context fits within typical LLM token limits (recommended < 4000 tokens for free-tier compatibility).