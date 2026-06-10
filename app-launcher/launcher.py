"""Entry point for the MicroApps Launcher.

Usage:
    python launcher.py            Run the Textual TUI (app list + config editor).
    python launcher.py --check    Validate apps.json and run prerequisite checks
                                  (headless; does not import Textual).
    python launcher.py --list     List the registered apps and exit.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `microapps_launcher` importable no matter where we are launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Print Unicode (emoji, box-drawing, em-dash) on legacy Windows consoles that
# default to cp1252; fall back gracefully if the stream cannot be reconfigured.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass

from microapps_launcher import paths, prepare, prerequisites
from microapps_launcher.manifest import ManifestError, load_registry


def _repo_root() -> Path:
    return paths.find_repo_root(Path(__file__).resolve().parent)


def cmd_list() -> int:
    registry = load_registry(_repo_root())
    for app in registry.apps:
        icon = f"{app.icon} " if app.icon else ""
        print(f"  {icon}{app.id:<22} {app.name}  [{app.stack}/{app.launch_mode}]")
    return 0


def cmd_check() -> int:
    root = _repo_root()
    print(f"Repo root : {root}")
    registry = load_registry(root)
    print(f"apps.json : valid — {len(registry.apps)} app(s)\n")

    all_ok = True
    for app in registry.apps:
        icon = f"{app.icon} " if app.icon else ""
        print(f"{icon}{app.name}  ({app.id})")
        for result in prerequisites.check_all(app):
            mark = "ok " if result.ok else "MISS"
            print(f"    [{mark}] {result.label}: {result.detail}")
            if not result.ok:
                all_ok = False
                if result.fix_hint:
                    print(f"           -> {result.fix_hint}")
        print(f"    prepare needed: {'yes' if prepare.needs_prepare(root, app) else 'no'}")
        print()

    print("All prerequisites satisfied."
          if all_ok else "Some prerequisites are missing (see above).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="launcher", description="MicroApps Launcher")
    parser.add_argument("--check", action="store_true",
                        help="Validate apps.json + run prerequisite checks (no UI).")
    parser.add_argument("--list", action="store_true",
                        help="List the registered apps and exit.")
    args = parser.parse_args(argv)

    try:
        if args.list:
            return cmd_list()
        if args.check:
            return cmd_check()
    except (ManifestError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Default: launch the Textual TUI (imported lazily so --check/--list stay
    # dependency-free).
    try:
        from microapps_launcher.tui.app import run_app
    except ImportError as exc:
        print(
            "ERROR: the TUI requires Textual. Install the launcher deps first:\n"
            "    pip install -r requirements.txt\n"
            f"(import error: {exc})",
            file=sys.stderr,
        )
        return 3
    try:
        run_app()
    except (ManifestError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
