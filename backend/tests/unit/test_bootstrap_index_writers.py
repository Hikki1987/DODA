"""The two deliberately RLS-free bootstrap tables may only be written from
their sanctioned call sites — enforced statically, the way
test_domain_isolation.py enforces 6.2's layering.

`workspace_tenant_index` and `user_customer_index` exist to break the
chicken-and-egg in RLS: you cannot look up "which customer owns workspace X"
or "which customers is user Y in" inside a tenant-scoped session without
already knowing the customer_id. They hold nothing but that mapping, and they
carry NO row-level security — which is exactly why test_rls_coverage.py lists
them as its only intentional exemptions.

CLAUDE.md states the rule as an absolute ("hech qachon boshqa joydan
yozilmasin" — never written from anywhere else), and each row must be written
in the same transaction as the membership/workspace it mirrors, or the mirror
drifts from the authority. Nothing enforced that: a future call site adding a
row on its own, or forgetting to remove one, would silently hand out access
the real membership tables never granted. This test is that enforcement.
"""

import ast
import pathlib

SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "doda"

# module path -> the functions allowed to construct it. Each entry is a real
# decision, not a record of what the code happens to do today: adding one
# means accepting that a new place may mint tenant-mapping rows.
ALLOWED_WRITERS: dict[str, dict[str, set[str]]] = {
    "UserCustomerIndex": {
        "application/customer_service.py": {
            # Written alongside the CustomerMembership it mirrors, in the same
            # transaction, and deleted alongside it.
            "create_customer_with_owner",
            "invite_customer_member",
        }
    },
    "WorkspaceTenantIndex": {
        "application/workspace_service.py": {
            # Written alongside the Workspace it maps, in the same transaction.
            "create_workspace",
        }
    },
}

# The class definitions themselves, plus the migrations that create the
# tables, are not call sites.
IGNORED_FILES = {"domain/customer/models.py", "domain/workspace/models.py"}


def _enclosing_function(tree: ast.Module, target: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for child in ast.walk(node):
                if child is target:
                    return node.name
    return None


def test_only_sanctioned_functions_construct_the_bootstrap_index_rows() -> None:
    violations: list[str] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT).as_posix()
        if relative in IGNORED_FILES:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            model = node.func.id
            if model not in ALLOWED_WRITERS:
                continue
            allowed = ALLOWED_WRITERS[model].get(relative, set())
            function = _enclosing_function(tree, node)
            if function not in allowed:
                violations.append(f"{relative}:{node.lineno} constructs {model} in {function}()")

    assert violations == [], (
        "a bootstrap tenant-mapping row was constructed outside its sanctioned call site: "
        + "; ".join(violations)
        + ". These tables carry no RLS, so a row written here grants tenant access the real "
        "membership tables never did — add the call site to ALLOWED_WRITERS only deliberately."
    )
