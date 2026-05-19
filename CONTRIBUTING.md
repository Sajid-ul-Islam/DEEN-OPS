# Contributing

## Local Setup

```bash
pip install -r requirements.txt
pip install -r requirements_dev.txt
pre-commit install
streamlit run app.py
```

## Before Opening a PR

- Run `pytest tests/ -v`
- Run `pre-commit run --all-files`
- Keep secrets out of commits
- Update docs when config, deployment, or operator workflows change

## Good First Issues

Issues labeled `good first issue` should stay small, isolated, and easy to validate. Good candidates include:

- Tests for utilities, config validation, or service edge cases
- Documentation improvements
- Small UI polish inside an existing page
- Safe refactors that do not change behavior

Avoid labeling work as `good first issue` when it spans multiple integrations, requires production credentials, or changes session-state contracts.

## Style Expectations

- Prefer focused patches over broad rewrites
- Add tests when behavior changes
- Use the config helpers in `src/config/settings.py` instead of reading secrets ad hoc
- Document new external API assumptions, especially rate limits and auth scope

## Pull Request Notes

- Summarize user-visible changes
- Call out any new secrets, env vars, or deployment expectations
- Mention tests you ran and anything you could not verify locally
