"""
cc_dashboard.py — CCDashboard entry point.

Default (live):
    python CCDashboard/cc_dashboard.py
        Index ~/.claude, start a local server (config + conversation search /
        resume, and QuizMe), and open it in the browser. Runs until Ctrl+C.

Static snapshot:
    python CCDashboard/cc_dashboard.py --static [--out PATH]
        Write a self-contained, config-only HTML file (no live features) and open
        it. Good for a quick offline view.

Common flags: --config-dir, --model, --no-open. Server flags: --host, --port.
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

from ccdashboard import build, scan, server  # noqa: E402  (import after path fix)

_DEFAULT_MODEL = "claude-opus-4-8"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A Jarvis-style local dashboard for your ~/.claude config and conversations.",
    )
    parser.add_argument(
        "--config-dir", type=Path, default=Path.home() / ".claude", metavar="PATH",
        help="Claude Code config directory (default: ~/.claude)",
    )
    parser.add_argument(
        "--model", default=_DEFAULT_MODEL, metavar="MODEL",
        help=f"Model used for any token counts (default: {_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--no-open", action="store_true",
        help="Do not open the dashboard in the browser",
    )
    parser.add_argument(
        "--static", action="store_true",
        help="Write a static, config-only HTML snapshot instead of running the live server",
    )
    parser.add_argument(
        "--out", type=Path, default=_HERE / "dist" / "dashboard.html", metavar="PATH",
        help="Output file for --static (default: CCDashboard/dist/dashboard.html)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Server bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=0, help="Server port (default: 0 = auto-pick a free port)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config_dir = args.config_dir.expanduser().resolve()

    if args.static:
        vm = scan.build_view_model(config_dir)
        total = vm.get("summary", {}).get("total", len(vm.get("items", [])))
        print(f"Scanned {total} components from {config_dir}")
        path = build.generate(vm, out_path=args.out, open_browser=not args.no_open)
        print(f"Static dashboard: {path}")
        return

    # Default: live server (config + conversations + resume + quiz).
    server.serve(
        config_dir=config_dir,
        model=args.model,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
