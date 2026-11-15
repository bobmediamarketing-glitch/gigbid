"""Render docs/REPORT.md to docs/REPORT.pdf (A4) with headless Chromium (Playwright from apps/web).

    python scripts/render_report.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9.6pt; line-height: 1.38; color: #111; }
h1 { font-size: 17pt; margin: 0 0 4pt; } h2 { font-size: 12.5pt; margin: 12pt 0 4pt; border-bottom: 1px solid #ccc; }
h3 { font-size: 10.5pt; margin: 8pt 0 3pt; } p, li { margin: 3pt 0; } ul, ol { margin: 2pt 0 4pt 16pt; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 6pt; font-size: 8.4pt; page-break-inside: avoid; }
th, td { border: 1px solid #bbb; padding: 2pt 4pt; text-align: left; vertical-align: top; } th { background: #eef1f6; }
code { font-family: Consolas, monospace; font-size: 8.4pt; background: #f3f3f3; padding: 0 2px; }
pre { background: #f6f6f6; padding: 5pt; font-size: 8pt; white-space: pre-wrap; }
"""


def main() -> int:
    md = (ROOT / "docs" / "REPORT.md").read_text(encoding="utf-8")
    html = markdown.markdown(md, extensions=["tables", "fenced_code"])
    page = ROOT / "docs" / "_report.html"
    page.write_text(f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html}</body></html>",
                    encoding="utf-8")
    out = ROOT / "docs" / "REPORT.pdf"
    js = (f"const {{chromium}}=require('@playwright/test');(async()=>{{const b=await chromium.launch();const p=await b.newPage();"
          f"await p.goto('file:///{page.as_posix()}');await p.pdf({{path:'{out.as_posix()}',format:'A4',printBackground:true,"
          f"margin:{{top:'16mm',bottom:'16mm',left:'15mm',right:'15mm'}},displayHeaderFooter:true,headerTemplate:'<span></span>',"
          f"footerTemplate:'<div style=\"font-size:8px;width:100%;text-align:center\">GigBid R&D report - page <span class=pageNumber></span> of <span class=totalPages></span></div>'}});"
          f"await b.close();}})();")
    subprocess.run(["node", "-e", js], cwd=ROOT / "apps" / "web", check=True, shell=sys.platform == "win32")
    page.unlink()
    from pypdf import PdfReader
    n = len(PdfReader(str(out)).pages)
    print(f"wrote docs/REPORT.pdf ({n} pages)")
    return 0 if n <= 10 else 1


if __name__ == "__main__":
    sys.exit(main())
