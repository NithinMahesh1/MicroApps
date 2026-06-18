"""
cc_dashboard.py — CCDashboard entry point (Textual TUI).

    python CCDashboard/cc_dashboard.py [--config-dir PATH]

Launches a futuristic terminal dashboard for your global Claude Code config
(``~/.claude``): browse skills / agents / memory / rules / settings, and search
your past conversations — pressing Enter on one resumes it in an elevated
PowerShell (``claude --resume`` in that conversation's working directory).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# UTF-8 fix for Windows cp1252 consoles.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# Make `from ccdashboard import ...` resolve no matter the working directory.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Futuristic terminal dashboard for your ~/.claude config + conversations.",
    )
    parser.add_argument(
        "--config-dir", type=Path, default=Path.home() / ".claude", metavar="PATH",
        help="Claude Code config directory (default: ~/.claude)",
    )
    args = parser.parse_args()

    # Lazy import so --help works without textual installed.
    from ccdashboard.tui.app import run

    run(args.config_dir.expanduser().resolve())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
