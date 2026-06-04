# Tech Stack

## Core Framework

- **Frontend**: Streamlit 1.42.0+
- **Python**: 3.11+ (devcontainer uses Python 3.11-bookworm)

## Data Processing

- **DataFrames**: pandas 2.2.2+, polars 0.20.30+ (with rtcompat)
- **Numerical**: numpy 1.26.4+
- **Visualization**: Plotly 5.22.0+, matplotlib 3.9.0+
- **Excel**: openpyxl 3.1.2+, xlsxwriter 3.2.0+

## Integrations

- **HTTP**: requests 2.32.3+, aiohttp 3.9.5+
- **Database**: DuckDB 1.0.0+
- **Fuzzy Matching**: fuzzywuzzy 0.18.0+, python-Levenshtein 0.25.1+
- **JSON**: toml 0.10.2+

## Machine Learning / AI

- **ML**: scikit-learn 1.5.0+, xgboost 2.0.3+, statsmodels 0.14.2+
- **LLM Providers**: OpenRouter, Google Gemini, Groq, Ollama, Hugging Face

## Build & Test Tools

- **Build**: Make (standard targets: `run`, `test`, `format`, `audit`)
- **Testing**: pytest with coverage (`pytest tests/ -v --cov=src`)
- **Formatting**: black 24.10.0+, isort 5.13.2+
- **Linting**: flake8 7.1.1+
- **Dependency Audit**: pip-audit

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements_dev.txt

# Run application
streamlit run app.py

# Run tests
pytest tests/ -v
pytest tests/ --cov=src --cov-report=term-missing

# Format code
black src/ tests/ app.py
isort src/ tests/ app.py

# Run linter
pre-commit run --all-files

# Audit dependencies
pip-audit -r requirements.txt

# Generate dependency lock file
python scripts/generate_requirements_lock.py
```

## Deployment

- **Local**: `streamlit run app.py`
- **Container**: Docker with healthcheck via `scripts/healthcheck.py`
- **CI/CD**: GitHub Actions (tests, format, data crunch workflows)