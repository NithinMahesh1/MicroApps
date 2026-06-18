"""
claude_bench.py — ClaudeBench CLI entry point.

Usage
-----
python claude_bench.py [--config-dir DIR] [--model MODEL] [--json] <subcommand>

Subcommands (Phase 1):
  list                    Scan config, tokenize, print table. No snapshot saved.
  snapshot [--label NAME] Scan, tokenize, save snapshot, print report.

Phase 2+ subcommands (diff, bench) are not implemented in Phase 1.

This file adds its own parent directory to sys.path so ``from claudebench import``
resolves correctly regardless of how the script is invoked.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows consoles default to cp1252; reconfigure stdout/stderr to UTF-8 so
# non-ASCII output (em-dashes, table glyphs) renders cleanly rather than as
# mojibake or a UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-standard streams
        pass

# ---------------------------------------------------------------------------
# Path bootstrap — make "from claudebench import ..." work when this file is
# invoked directly (python claude_bench.py) from any working directory.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from claudebench import models, report, scanner, snapshot, tokenizer  # noqa: E402

# Snapshot files live in ClaudeBench/snapshots/ (git-ignored), resolved
# relative to this file so the path is stable regardless of cwd.
_SNAPSHOTS_DIR = _HERE / "snapshots"

_DEFAULT_CONFIG_DIR = Path.home() / ".claude"
_DEFAULT_MODEL = "claude-opus-4-8"
_FALLBACK_MODE = "claude-p-fallback"
_FALLBACK_WARNING = (
    "\nWARNING: count_tokens requires an Anthropic API key "
    "(ANTHROPIC_API_KEY or an active Claude login).\n"
    "Token counts are placeholders (0) — set an API key for real measurements.\n"
)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _cmd_list(args: argparse.Namespace) -> int:
    """Scan -> tokenize -> print table.  Does not save a snapshot."""
    config_dir: Path = args.config_dir.expanduser().resolve()
    model: str = args.model

    components = scanner.scan(config_dir)
    filled, mode = tokenizer.tokenize(components, config_dir=config_dir, model=model)

    if mode == _FALLBACK_MODE:
        print(_FALLBACK_WARNING, file=sys.stderr)

    if args.json:
        data = [c.to_dict() for c in filled]
        print(json.dumps(data, indent=2))
    else:
        print(report.render_list(filled))

    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    """Scan -> tokenize -> build snapshot -> save -> print report."""
    config_dir: Path = args.config_dir.expanduser().resolve()
    model: str = args.model
    label: str | None = args.label

    components = scanner.scan(config_dir)
    filled, mode = tokenizer.tokenize(components, config_dir=config_dir, model=model)

    if mode == _FALLBACK_MODE:
        print(_FALLBACK_WARNING, file=sys.stderr)

    taken_at = datetime.now(timezone.utc).isoformat()
    snap = models.build_snapshot(
        filled,
        config_dir=str(config_dir),
        model=model,
        tokenizer=mode,
        label=label,
        taken_at=taken_at,
    )

    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = snapshot.save(snap, _SNAPSHOTS_DIR)

    if args.json:
        print(report.render_snapshot(snap, as_json=True))
    else:
        print(report.render_snapshot(snap))

    print(f"\nSnapshot saved: {saved_path}")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude_bench",
        description=(
            "Measure and track the token footprint of your ~/.claude/ config. "
            "count_tokens (Phase 1) is FREE — no inference, no subscription spend."
        ),
    )

    # Global flags
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=_DEFAULT_CONFIG_DIR,
        metavar="DIR",
        help=f"Claude config directory to scan (default: {_DEFAULT_CONFIG_DIR})",
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        metavar="MODEL",
        help=f"Model used for count_tokens (default: {_DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a console table",
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    subparsers.required = True

    # list
    subparsers.add_parser(
        "list",
        help="Scan and print static token counts. No snapshot is saved.",
    )

    # snapshot
    snap_parser = subparsers.add_parser(
        "snapshot",
        help="Take a static snapshot and save it to snapshots/.",
    )
    snap_parser.add_argument(
        "--label",
        default=None,
        metavar="NAME",
        help="Human-readable label for this snapshot (optional)",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.subcommand == "list":
            return _cmd_list(args)
        if args.subcommand == "snapshot":
            return _cmd_snapshot(args)
        # Unreachable given subparsers.required = True, but satisfies type checker
        parser.error(f"Unknown subcommand: {args.subcommand}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
