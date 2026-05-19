# DEEN OPS Terminal

AI-assisted operations workspace for WooCommerce, Pathao, inventory, and reporting workflows.

## Highlights

- Streamlit dashboard with live operational views, inventory analysis, and courier tooling
- WooCommerce and Pathao integrations with local snapshot fallbacks
- Multi-provider LLM routing for Data Pilot workflows
- Runtime configuration validation backed by [src/config/secrets_schema.json](src/config/secrets_schema.json)
- Shared HTTP backoff for WooCommerce, Pathao, and URL ingestion calls
- Container healthcheck support via [scripts/healthcheck.py](scripts/healthcheck.py)

## Tech Stack

- Frontend: Streamlit, custom CSS, Plotly
- Data: pandas, polars, numpy
- Integrations: WooCommerce REST API, Pathao Courier API
- AI: OpenRouter, Gemini, Groq, Ollama, Hugging Face
- Tooling: pytest, pre-commit, black, isort, flake8

## Quick Start

```bash
git clone https://github.com/saajiidi/DEEN-BI.git
cd DEEN-OPS
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements_dev.txt
pre-commit install
streamlit run app.py
```

## Configuration

The app supports `.streamlit/secrets.toml` and environment variable fallbacks for WooCommerce, Pathao, and LLM providers. The contract is documented in [src/config/secrets_schema.json](src/config/secrets_schema.json).

Example `.streamlit/secrets.toml`:

```toml
[woocommerce]
store_url = "https://your-store.com"
consumer_key = "ck_..."
consumer_secret = "cs_..."

[pathao]
base_url = "https://courier-api.pathao.com"
client_id = "..."
client_secret = "..."
username = "..."
password = "..."

[llm]
openrouter_key = "..."
gemini_key = "..."
groq_key = "..."

[auth]
redirect_uri = "..."
cookie_secret = "..."

[auth.google]
client_id = "..."
client_secret = "..."
server_metadata_url = "..."
```

Supported env vars:

- `WC_URL`, `WC_KEY`, `WC_SECRET`
- `PATHAO_BASE_URL`, `PATHAO_CLIENT_ID`, `PATHAO_CLIENT_SECRET`, `PATHAO_USERNAME`, `PATHAO_PASSWORD`
- `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `HF_API_KEY`
- `API_RETRY_MAX_ATTEMPTS`, `API_BACKOFF_FACTOR_SECONDS`, `API_BACKOFF_MAX_SECONDS`

The app now validates partially configured integrations at startup and surfaces issues in the sidebar under `Maintenance & Settings`.

## Dependency Layout

```text
requirements/
|-- base.txt
|-- integrations.txt
|-- ai.txt
`-- dev.txt
```

- `requirements.txt` installs runtime dependencies
- `requirements_dev.txt` installs runtime and development tooling
- `requirements.lock` pins runtime transitive dependencies for Docker and CI

Refresh the lock file from a clean environment with:

```bash
python scripts/generate_requirements_lock.py
```

## Project Structure

```text
DEEN-OPS/
|-- app.py
|-- assets/
|-- data/
|-- resources/
|-- scripts/
|-- src/
|   |-- components/
|   |-- config/
|   |-- inventory/
|   |-- pages/
|   |-- processing/
|   |-- services/
|   |-- state/
|   `-- utils/
|-- tests/
`-- _deprecated/
```

## Development

```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=term-missing
pre-commit run --all-files
```

See [DEVELOPMENT.md](DEVELOPMENT.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [ERROR_HANDLING_GUIDE.md](ERROR_HANDLING_GUIDE.md).

## CI

GitHub Actions runs the test suite from [.github/workflows/tests.yml](.github/workflows/tests.yml) using `requirements_dev.txt`, which is constrained by `requirements.lock`.

## Deployment Notes

- Local: `streamlit run app.py`
- Staging: Docker or Docker Compose with env-based secrets injection
- Production: Kubernetes with external secret management, TLS ingress, and autoscaling
- CI/CD: run pytest, build the image, and deploy only after tests pass

The Docker image uses the Streamlit `/_stcore/health` endpoint through [scripts/healthcheck.py](scripts/healthcheck.py), so container health probes do not depend on `curl`.
