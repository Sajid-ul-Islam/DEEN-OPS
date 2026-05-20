.PHONY: run test format audit

run:
	streamlit run app.py

test:
	pytest tests/ -v --cov=src

format:
	black src/ tests/ app.py
	isort src/ tests/ app.py

audit:
	pip-audit -r requirements.txt