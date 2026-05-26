import ast
import sys
import re
from pathlib import Path

# Map PyPI package names to their Python import names
PKG_TO_MODULE = {
    "scikit-learn": "sklearn",
    "python-levenshtein": "Levenshtein",
    "python-dateutil": "dateutil",
    "pyyaml": "yaml",
    "pillow": "PIL",
}

# Standard library modules to ignore during the check
STDLIB = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {
    "os", "sys", "json", "time", "asyncio", "hashlib", "typing", "dataclasses",
    "datetime", "collections", "threading", "io", "re", "math", "random", "pathlib"
}

def get_actual_imports(base_dir: Path) -> set:
    """Scan all .py files and extract top-level imports."""
    imports = set()
    for filepath in base_dir.rglob("*.py"):
        # Skip virtual environments
        if ".venv" in filepath.parts or "venv" in filepath.parts:
            continue
            
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(filepath))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
        except Exception as e:
            print(f"⚠️ Failed to parse {filepath.name}: {e}")
            
    return imports - STDLIB

def get_requirements(req_path: Path) -> dict:
    """Parse requirements.txt into a set of package names."""
    reqs = {}
    if not req_path.exists():
        return reqs
        
    with open(req_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line or line.startswith("-"):
                continue
            # Strip version specifiers (==, >=, <=, etc.)
            pkg = re.split(r'[=><!~]', line)[0].strip()
            module_name = PKG_TO_MODULE.get(pkg.lower(), pkg.replace("-", "_"))
            reqs[pkg] = module_name.lower()
            
    return reqs

if __name__ == "__main__":
    root_dir = Path(__file__).resolve().parent.parent
    req_path = root_dir / "requirements.txt"
    
    print("🔍 Scanning AST for active imports...")
    actual_imports = {m.lower() for m in get_actual_imports(root_dir)}
    
    print("📄 Parsing requirements.txt...")
    reqs = get_requirements(req_path)
    req_modules = set(reqs.values())
    
    print("\n--- 📋 RESULTS ---")
    unused = [pkg for pkg, mod in reqs.items() if mod not in actual_imports and mod != "streamlit"]
    if unused:
        print("⚠️  Potentially Unused Packages in requirements.txt:\n" + "\n".join(f"  - {p}" for p in unused))
        sys.exit(1)
    else:
        print("✅ All packages in requirements.txt appear to be used.")