"""Keep package ownership and dependency direction explicit."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "litereality_agent"
LAYERS = {"agent", "models", "runtimes", "scene", "pipeline"}
ALLOWED = {
    "agent": {"scene"},
    "models": {"runtimes"},
    "runtimes": set(),
    "scene": set(),
    "pipeline": {"agent", "models", "scene"},
}


def imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_layer_imports_only_point_inward():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        owner = relative.parts[0]
        if owner not in LAYERS:
            continue
        for imported in imports(path):
            if not imported.startswith("litereality_agent."):
                continue
            target = imported.split(".")[1]
            if target in LAYERS and target != owner and target not in ALLOWED[owner]:
                violations.append(f"{relative}:{owner} -> {target}")
    assert not violations, "invalid layer imports:\n" + "\n".join(violations)


def test_only_supported_package_areas_exist():
    retired = {"adapters", "services", "shared"}
    present = {
        path.name for path in PACKAGE.iterdir() if path.is_dir() and any(path.rglob("*.py"))
    }
    assert not present & retired
