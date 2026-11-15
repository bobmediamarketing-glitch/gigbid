"""CI rule: nothing under gigsim/ changed. Compares every file against the committed manifest of SHA-256
hashes (.github/gigsim.sha256), which is regenerated only when the official kit is dropped in:

    python scripts/ci/check_gigsim.py            # verify (CI)
    python scripts/ci/check_gigsim.py --update   # after replacing gigsim/ with the official kit (one commit)
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".github" / "gigsim.sha256"
SKIP = {"__pycache__", "state"}


def files() -> dict[str, str]:
    out = {}
    for f in sorted((ROOT / "gigsim").rglob("*")):
        if f.is_file() and not SKIP & set(f.relative_to(ROOT).parts) and f.suffix not in (".pyc",):
            data = f.read_bytes().replace(b"\r\n", b"\n")  # line endings do not count as a change
            out[str(f.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(data).hexdigest()
    return out


def main() -> int:
    now = files()
    if "--update" in sys.argv:
        MANIFEST.write_text("".join(f"{h}  {p}\n" for p, h in now.items()), encoding="utf-8")
        print(f"wrote {MANIFEST.relative_to(ROOT)} ({len(now)} files)")
        return 0
    want = dict(reversed(line.split("  ", 1)) for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line)
    changed = sorted(p for p in now if p in want and now[p] != want[p])
    added, removed = sorted(set(now) - set(want)), sorted(set(want) - set(now))
    for label, items in (("changed", changed), ("added", added), ("removed", removed)):
        for p in items:
            print(f"FAIL gigsim file {label}: {p}")
    ok = not (changed or added or removed)
    print(f"gigsim check: {'unchanged' if ok else 'MODIFIED'} ({len(now)} files)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
