"""TRD 6.2: "Domain boshqa domainning implementatsiyasini import qilmaydi —
faqat ID/reference kontrakti yoki application port orqali." A domain module
importing another domain's models/services directly would let two domains'
storage and business rules silently couple — the opposite of the modular
monolith boundary ADR-001 depends on. Static AST check, no DB needed.
"""

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).parents[2] / "src" / "doda" / "domain"

# `base` is the shared SQLAlchemy declarative Base — a deliberate shared
# kernel, not a domain, so importing it isn't a boundary violation.
ALLOWED_SHARED_MODULES = {"base"}


def _domain_names() -> list[str]:
    return sorted(p.name for p in DOMAIN_ROOT.iterdir() if p.is_dir() and not p.name.startswith("__"))


def _imported_domain_modules(tree: ast.Module) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("doda.domain."):
            found.add(node.module.split(".")[2])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("doda.domain."):
                    found.add(alias.name.split(".")[2])
    return found


def test_no_domain_module_imports_another_domains_implementation() -> None:
    domain_names = _domain_names()
    assert domain_names, "expected at least one domain package under src/doda/domain"

    violations = []
    for domain_name in domain_names:
        for py_file in (DOMAIN_ROOT / domain_name).rglob("*.py"):
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
            imported = _imported_domain_modules(tree) - {domain_name} - ALLOWED_SHARED_MODULES
            if imported:
                violations.append(f"{py_file.relative_to(DOMAIN_ROOT)} imports domain(s) {sorted(imported)}")

    assert not violations, "domain boundary violation(s):\n" + "\n".join(violations)
