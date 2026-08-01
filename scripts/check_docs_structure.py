#!/usr/bin/env python3
"""Assert that editing a document's prose did not move its numbered sections.

The code cites these documents by filename and section number in 221 places across 115 files —
`08_Security_Architecture.md Section 1`. Renumbering or dropping a section silently invalidates
every pointer to it, and nothing else in the build would notice.

    python3 scripts/check_docs_structure.py --snapshot   # record the current structure
    python3 scripts/check_docs_structure.py              # compare against the record
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SNAPSHOT = ROOT / "scripts" / "docs_structure.json"

#: `## 3. Section name` — the numbered headings citations point at.
NUMBERED = re.compile(r"^(#{2,3})\s*(\d+)\.\s*(.+?)\s*$", re.M)


def structure() -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    for path in sorted(DOCS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        out[path.name] = [[m.group(1), m.group(2), m.group(3)] for m in NUMBERED.finditer(text)]
    return out


def main() -> int:
    current = structure()
    if "--snapshot" in sys.argv:
        SNAPSHOT.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        total = sum(len(v) for v in current.values())
        print(f"recorded {total} numbered sections across {len(current)} documents")
        return 0

    if not SNAPSHOT.exists():
        print("no snapshot; run with --snapshot first", file=sys.stderr)
        return 2

    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    problems: list[str] = []
    for name, sections in expected.items():
        got = current.get(name)
        if got is None:
            problems.append(f"{name}: document is gone")
            continue
        want_numbers = [s[1] for s in sections]
        got_numbers = [s[1] for s in got]
        if want_numbers != got_numbers:
            problems.append(f"{name}: section numbers changed {want_numbers} -> {got_numbers}")

    if problems:
        print("STRUCTURE CHANGED — citations in the code may no longer resolve:")
        for p in problems:
            print("  " + p)
        return 1

    total = sum(len(v) for v in expected.values())
    print(f"{total} numbered sections intact across {len(expected)} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
