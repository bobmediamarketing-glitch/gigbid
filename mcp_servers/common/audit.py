"""Append-only audit log: one JSON line per tool call (user, tool, arguments, result, trace id).

Arguments and results are PII-masked before they are written. The file is only
ever opened in append mode; rotation is an operator task (docs/RUNBOOK.md).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_servers.common.context import caller, current_trace
from mcp_servers.common.pii import mask


class AuditLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, server: str, tool: str, args: dict, *, status: str, result: Any = None,
               error: str | None = None) -> str:
        who = caller()
        row = {"id": uuid.uuid4().hex, "ts": datetime.now(timezone.utc).isoformat(), "server": server, "tool": tool,
               "user": who.user_id, "tenant": who.tenant, "trace_id": current_trace.get(),
               "args": mask(args), "status": status, "result": mask(_summarise(result)), "error": mask(error)}
        line = json.dumps(row, default=str, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return row["id"]

    def tail(self, n: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines()[-n:]]


def _summarise(result: Any) -> Any:
    if result is None:
        return None
    if hasattr(result, "model_dump"):
        result = result.model_dump(mode="json")
    if isinstance(result, dict) and "items" in result and isinstance(result["items"], list):
        return {"count": len(result["items"]), "ids": [i.get("id") for i in result["items"][:20] if isinstance(i, dict)]}
    return result
