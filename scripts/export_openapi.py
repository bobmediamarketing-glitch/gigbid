"""Write the API's OpenAPI schema to apps/web/openapi.json (the TypeScript client is generated from it).

    python scripts/export_openapi.py && (cd apps/web && npm run gen:api)

CI runs both and fails if the generated client differs from the committed one (contract drift).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GIGBID_SERVE_WEB", "0")

from apps.api.main import app  # noqa: E402

out = ROOT / "apps" / "web" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=1) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)} ({len(app.openapi()['paths'])} paths)")
