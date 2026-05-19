# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Schema-backed secrets contract in `src/config/secrets_schema.json`
- Container healthcheck helper in `scripts/healthcheck.py`
- Contributor workflow files: `CONTRIBUTING.md`, `.pre-commit-config.yaml`
- Runtime HTTP retry helper in `src/utils/http.py`
- GitHub Actions test workflow in `.github/workflows/tests.yml`
- Lock file generator in `scripts/generate_requirements_lock.py`

### Changed

- Split dependencies into `requirements/base.txt`, `requirements/integrations.txt`, `requirements/ai.txt`, and `requirements/dev.txt`
- Startup configuration validation now reports partial integration setup in the app sidebar
- Pathao and WooCommerce config lookup now resolves through `src/config/settings.py`
- Docker and local installs now consume `requirements.lock` as a constraints file

### Security

- Removed the hardcoded Pathao credential fallback from runtime configuration
