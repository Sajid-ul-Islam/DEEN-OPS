# Contributing to DEEN-OPS Terminal

Thank you for contributing to **DEEN-OPS Terminal**! Whether you are a human software engineer or an autonomous AI agent, please adhere to the following workflow and quality standards.

---

## 1. Development Workflow

1. **Clone & Environment Setup**:
   ```bash
   git clone https://github.com/Sajid-ul-Islam/DEEN-OPS.git
   cd DEEN-OPS
   python -m venv .venv
   .venv\Scripts\activate      # On Linux/macOS: source .venv/bin/activate
   pip install -r requirements_dev.txt
   ```

2. **Branching Strategy**:
   - Work directly on or branch from `main`.
   - Feature branches should follow: `feat/<feature-name>`, `fix/<bug-name>`, or `refactor/<scope>`.

3. **Running Locally**:
   ```bash
   streamlit run app.py
   ```

---

## 2. Mandatory Pre-Commit / Pre-Push Quality Gates

Before pushing any commit or opening a Pull Request, all of the following checks **must pass with 0 errors**:

```powershell
# 1. Lint checks
.venv\Scripts\ruff.exe check .

# 2. Formatting verification
.venv\Scripts\ruff.exe format --check .

# 3. Syntax compile validation
.venv\Scripts\python.exe -m compileall -q src app.py

# 4. Strict 63-module import verification
$env:PYTHONPATH="."
.venv\Scripts\python.exe scripts/check_imports.py

# 5. Full automated test suite (432+ unit tests)
$env:PYTHONPATH="."
.venv\Scripts\pytest.exe tests/ -q --disable-warnings

# 6. Streamlit configuration check
.venv\Scripts\python.exe -c "import toml; toml.load('.streamlit/config.toml'); print('Streamlit config OK')"
```

---

## 3. Commit Message Conventions

We adhere to **Conventional Commits**:

| Type | When to use | Example |
| :--- | :--- | :--- |
| `feat` | Adding a new user-facing capability | `feat(pathao): add bulk barcode printing support` |
| `fix` | Bug fix or regression patch | `fix(dashboard): resolve comparison frame fallback on cold start` |
| `refactor` | Code restructuring without changing behavior | `refactor(sip): consolidate outlet processor logic` |
| `test` | Adding or updating unit tests | `test(order-view): add regression tests for status filtering` |
| `docs` | Documentation updates | `docs(agents): add layer separation rules to AGENTS.md` |
| `chore` | Dependency updates, tooling, or CI changes | `chore(ci): update github actions python version` |

---

## 4. Architectural Constraints

- **Strict Layer Separation**: Read [AGENTS.md](AGENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md). Never import UI modules into `src/processing/`, `src/services/`, or `src/utils/`.
- **Timezone Awareness**: Always use `bd_now()` / `bd_today()` from `src.config.constants` for business logic (Bangladesh Time UTC+6).
- **Zero Secret Commits**: Never commit `.env`, `.streamlit/secrets.toml`, or private credentials.
