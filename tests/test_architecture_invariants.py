"""Repository-level regression tests for security and layer boundaries."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
from pathlib import Path

import toml

ROOT = Path(__file__).resolve().parents[1]


def _python_files(*folders: str):
    for folder in folders:
        yield from (ROOT / folder).rglob("*.py")


def test_processing_and_services_do_not_import_ui_frameworks():
    violations = []
    for path in _python_files("src/processing", "src/services"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name == "streamlit" or name.startswith("streamlit."):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} -> {name}"
                    )
                if name == "src.components" or name.startswith("src.components."):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} -> {name}"
                    )
    assert violations == []


def test_all_relative_imports_resolve_to_existing_modules():
    violations = []
    for path in _python_files("src"):
        relative_module = path.relative_to(ROOT).with_suffix("")
        module_name = ".".join(relative_module.parts)
        package_name = module_name.rpartition(".")[0]

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            relative_name = "." * node.level + (node.module or "")
            absolute_name = importlib.util.resolve_name(relative_name, package_name)
            if importlib.util.find_spec(absolute_name) is None:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} -> {absolute_name}"
                )
    assert violations == []


def test_external_http_uses_shared_helpers():
    violations = []
    for path in _python_files("src"):
        if path == ROOT / "src/utils/http.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "requests":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if (
                isinstance(owner, ast.Name)
                and owner.id == "aiohttp"
                and node.func.attr == "ClientSession"
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_sensitive_runtime_files_are_gitignored():
    sensitive_paths = [
        ".streamlit/secrets.toml",
        "BackEnd/cache/orders_snapshot.parquet",
        "resources/customer_registry_full.json",
        "resources/pathao_status_cache.json",
        "pathao_token.json",
        ".pathao-token-example",
        "data/pathao_dispatch.sqlite3",
    ]
    for relative_path in sensitive_paths:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", relative_path],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 0, f"{relative_path} must be ignored"


def test_streamlit_production_origin_controls_are_enabled():
    server = toml.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))[
        "server"
    ]
    assert server["enableCORS"] is True
    assert server["enableXsrfProtection"] is True
    assert "ops.deencommerce.com" in server["allowedHosts"]


def test_kubernetes_ingress_backend_has_service_manifest():
    service = (ROOT / "deploy/k8s/service.yaml").read_text(encoding="utf-8")
    assert "name: deen-ops-service" in service


def test_completed_orders_widgets_render_once():
    """Both dead functions and their widget keys must be absent from the codebase
    after the dead-code removal pass that deleted _render_completed_orders_section
    and _render_completed_kpis_display from live_components.py."""
    source = (ROOT / "src/pages/live_dashboard.py").read_text(encoding="utf-8")
    assert "_render_completed_orders_section()" not in source
    assert "_render_completed_kpis_display(" not in source
    for widget_key in (
        'key="completed_date_picker"',
        'key="completed_source_filter"',
        'key="show_completed_kpis"',
    ):
        assert source.count(widget_key) == 0

    component_source = (ROOT / "src/components/dashboard/live_components.py").read_text(
        encoding="utf-8"
    )
    assert "_render_completed_orders_section" not in component_source
    assert "_render_completed_kpis_display" not in component_source
    for widget_key in (
        'key="completed_date_picker"',
        'key="completed_source_filter"',
        'key="show_completed_kpis"',
    ):
        assert component_source.count(widget_key) == 0


def test_dashboard_autosync_does_not_force_duplicate_fetch():
    source = (ROOT / "src/components/dashboard/live_components.py").read_text(
        encoding="utf-8"
    )
    assert "_load_live_source(force_refresh=True)" not in source
