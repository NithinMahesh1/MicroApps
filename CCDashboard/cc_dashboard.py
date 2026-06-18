"""
cc_dashboard.py — CCDashboard entry point.

Usage:
    python CCDashboard/cc_dashboard.py [--config-dir PATH] [--out PATH] [--no-open]

Scans the Claude Code config directory, builds a self-contained HTML dashboard,
and opens it in the browser.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# --- UTF-8 fix for Windows cp1252 consoles ----------------------------------
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# --- sys.path bootstrap so `from ccdashboard import ...` resolves -----------
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from ccdashboard import build, scan  # noqa: E402  (import after path fix)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a read-only HTML dashboard of your ~/.claude/ config.",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path.home() / ".claude",
        metavar="PATH",
        help="Claude Code config directory (default: ~/.claude)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_HERE / "dist" / "dashboard.html",
        metavar="PATH",
        help="Output HTML file (default: CCDashboard/dist/dashboard.html)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Build the HTML but do not open it in the browser",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config_dir = args.config_dir.expanduser().resolve()

    vm = scan.build_view_model(config_dir)

    # One-line progress summary drawn from the view model's summary block.
    summary = vm.get("summary", {})
    n_components = summary.get("total_items", len(vm.get("items", [])))
    print(f"Scanned {n_components} components from {config_dir}")

    path = build.generate(vm, out_path=args.out, open_browser=not args.no_open)
    print(f"Dashboard: {path}")


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
