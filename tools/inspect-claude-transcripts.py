"""
inspect-claude-transcripts.py — read-only diagnostic for Claude Code transcripts.

Claude Code stores every conversation as a JSONL transcript under
``~/.claude/projects/<encoded-working-dir>/<session-id>.jsonl``. This script
reports the *structure* of those transcripts (event keys, field presence, and
per-project session counts) so we can build tools on top of them.

It prints metadata and counts ONLY — never message content — so it is safe to
run and commit (no secrets, no conversation text). Run from anywhere:

    python tools/inspect-claude-transcripts.py

Note: this reads the machine's own ``~/.claude``; it needs no arguments and
does not need to be copied anywhere. The conversation-search app reuses this
same transcript layout (cwd / gitBranch / sessionId / timestamp / aiTitle).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Windows consoles default to cp1252; render any non-ASCII cleanly.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main() -> int:
    proj = Path.home() / ".claude" / "projects"
    if not proj.exists():
        print(f"No transcripts directory found at {proj}")
        return 1

    dirs = [d for d in proj.iterdir() if d.is_dir()]
    print(f"Transcripts root : {proj}")
    print(f"Project folders  : {len(dirs)}")
    for d in sorted(dirs)[:8]:
        print(f"  {d.name}  -> {len(list(d.glob('*.jsonl')))} sessions")

    sessions = list(proj.glob("*/*.jsonl"))
    print(f"Total sessions   : {len(sessions)}")
    if not sessions:
        return 0

    sample = max(sessions, key=lambda p: p.stat().st_mtime)
    top: set[str] = set()
    mkeys: set[str] = set()
    roles: set[str] = set()
    flags = {"cwd": False, "gitBranch": False, "timestamp": False, "sessionId": False, "aiTitle": False}
    with sample.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 60:
                break
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            top |= set(ev.keys())
            for key in flags:
                if key in ev:
                    flags[key] = True
            msg = ev.get("message")
            if isinstance(msg, dict):
                mkeys |= set(msg.keys())
                role = msg.get("role")
                if isinstance(role, str):
                    roles.add(role)

    print(f"\nSample session   : {sample.name}")
    print(f"  project dir    : {sample.parent.name}")
    print(f"  top-level keys : {sorted(top)}")
    print(f"  message keys   : {sorted(mkeys)}")
    print(f"  roles          : {sorted(roles)}")
    print(f"  field presence : {flags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
