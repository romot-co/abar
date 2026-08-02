import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_compare_core_does_not_depend_on_upper_layers() -> None:
    for path in Path("src/abar/compare").rglob("*.py"):
        imports = _imports(path)
        assert not any(
            name.startswith(("abar.project", "abar.research", "abar.app")) for name in imports
        )


def test_current_best_rule_is_isolated_from_workflow() -> None:
    imports = _imports(Path("src/abar/project/current_best.py"))
    assert imports == {"abar.project.models"}


def test_domain_layers_do_not_import_application() -> None:
    for directory in ("project", "research"):
        for path in Path(f"src/abar/{directory}").glob("*.py"):
            assert not any(name.startswith("abar.app") for name in _imports(path))


def test_internal_package_dependency_graph_is_acyclic() -> None:
    root = Path("src/abar")
    nodes = {path.name for path in root.iterdir() if path.is_dir()}
    graph: dict[str, set[str]] = {name: set() for name in nodes}
    for package in nodes:
        for path in (root / package).rglob("*.py"):
            for imported in _imports(path):
                parts = imported.split(".")
                if len(parts) >= 2 and parts[0] == "abar" and parts[1] in nodes:
                    target = parts[1]
                    if target != package:
                        graph[package].add(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        assert node not in visiting, f"package dependency cycle through {node}: {graph}"
        if node in visited:
            return
        visiting.add(node)
        for target in graph[node]:
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
