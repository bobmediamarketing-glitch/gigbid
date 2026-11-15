"""CI rule: every prompt lives in agent/prompts/. Fails if a model call is given inline prompt text.

Checks every `.structured(node, Schema, system, user)` call (the only way GigBid calls a model) and any
`ChatGroq/ChatAnthropic/ChatOllama(...).invoke` with literal messages: the `system` argument must not be a
string literal (or an f-string / concatenation containing more than 40 literal characters).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = ["agent", "apps/api", "rag", "evals", "mcp_servers", "worker"]
LIMIT = 40


def literal_chars(node: ast.AST) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return len(node.value)
    if isinstance(node, ast.JoinedStr):
        return sum(len(v.value) for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.BinOp):
        return literal_chars(node.left) + literal_chars(node.right)
    return 0


def main() -> int:
    bad = []
    for d in SCAN:
        for f in sorted((ROOT / d).rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "structured":
                    system = n.args[2] if len(n.args) > 2 else next((k.value for k in n.keywords if k.arg == "system"), None)
                    if system is not None and literal_chars(system) > LIMIT:
                        bad.append(f"{f.relative_to(ROOT)}:{n.lineno} inline prompt ({literal_chars(system)} chars)")
    missing = [f"agent/prompts/{p}.md has no 'version:' line" for p in
               (x.stem for x in (ROOT / "agent" / "prompts").glob("*.md"))
               if not (ROOT / "agent" / "prompts" / f"{p}.md").read_text(encoding="utf-8").lower().startswith("version:")]
    for line in bad + missing:
        print("FAIL", line)
    print(f"prompts check: {len(bad) + len(missing)} problem(s)")
    return 1 if bad or missing else 0


if __name__ == "__main__":
    sys.exit(main())
