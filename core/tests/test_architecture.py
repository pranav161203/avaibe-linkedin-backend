"""The layer rule from docs/architecture.md, checked on every test run: imports only point down the layers.

If this fails, move the code to the right layer instead of loosening the rule. A service that needs an HTTP status
raises its own error and the view turns it into one; an integration that needs data gets it passed in.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]

# package -> module prefixes it must never import
FORBIDDEN = {
    "core/services": ("core.api",),
    "core/integrations": ("core.api", "core.auth", "core.services", "core.models", "core.schemas"),
    "core/models": ("core.api", "core.auth", "core.services", "core.integrations", "core.schemas"),
    "core/schemas": ("core.api",),
    "core/common": ("core.api", "core.auth", "core.services", "core.integrations", "core.models", "core.schemas"),
    "core/auth": ("core.api",),
    "core": ("dev_tools",),  # production code never depends on development tools
}


def imports(path: Path) -> list[tuple[int, str]]:
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
    return out


class LayerRuleTests(SimpleTestCase):
    def test_imports_point_down_the_layers(self):
        problems = []
        for package, banned in FORBIDDEN.items():
            for f in (ROOT / package).rglob("*.py"):
                rel = f.relative_to(ROOT).as_posix()
                if "/tests/" in rel or "/migrations/" in rel:
                    continue
                for line, mod in imports(f):
                    if any(mod == b or mod.startswith(b + ".") for b in banned):
                        problems.append(f"{rel}:{line} imports {mod}")
        self.assertEqual(problems, [], "Imports against the layer rule (docs/architecture.md):\n" + "\n".join(problems))
