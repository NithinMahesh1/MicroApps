"""
snapshot.py — read and write timestamped JSON snapshot files.

Snapshot files are stored under a ``snapshots/`` directory (git-ignored).
Each file is named ``<UTC-timestamp>[_<label>].json`` and contains a
schema-conformant JSON serialization of a Snapshot.

Public API
----------
save(snap, snapshots_dir) -> Path
    Serialize snap to a new JSON file; return the written path.
load(path) -> Snapshot
    Deserialize a snapshot file; return a Snapshot instance.
find_latest(snapshots_dir, n=1) -> list[Path]
    Return up to n snapshot paths, newest-first.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from claudebench.models import Snapshot

# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

_TIMESTAMP_FMT_IN = "%Y-%m-%dT%H:%M:%SZ"   # ISO-8601 input from taken_at
_TIMESTAMP_FMT_OUT = "%Y%m%dT%H%M%SZ"       # compact file prefix


def _label_to_slug(label: str) -> str:
    """Sanitize a label string for use in a filename.

    Replaces any character that is not alphanumeric, hyphen, or underscore
    with an underscore, and truncates to 64 characters.
    """
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", label)
    return slug[:64]


def _taken_at_to_file_prefix(taken_at: str) -> str:
    """Convert an ISO-8601 UTC taken_at string to the compact file prefix.

    ``"2026-06-18T14:30:05Z"`` -> ``"20260618T143005Z"``

    Falls back to the original string (with colons removed) if parsing fails.
    """
    from datetime import datetime, timezone
    try:
        dt = datetime.strptime(taken_at, _TIMESTAMP_FMT_IN)
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime(_TIMESTAMP_FMT_OUT)
    except ValueError:
        # Best-effort: strip colons and hyphens from whatever was given
        return re.sub(r"[-:]", "", taken_at).replace(" ", "T")


def _snapshot_filename(snap: Snapshot) -> str:
    """Build the snapshot filename from taken_at and optional label."""
    prefix = _taken_at_to_file_prefix(snap.taken_at)
    if snap.label:
        slug = _label_to_slug(snap.label)
        return f"{prefix}_{slug}.json"
    return f"{prefix}.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save(snap: Snapshot, snapshots_dir: Path) -> Path:
    """Serialize snap to a timestamped JSON file in snapshots_dir.

    Creates snapshots_dir (and any missing parents) if it does not exist.
    The file is written as 2-space-indented JSON with a trailing newline,
    conforming to snapshot.schema.json.

    Parameters
    ----------
    snap:
        The Snapshot to persist.
    snapshots_dir:
        Directory in which to write the file.  Created if absent.

    Returns
    -------
    Path
        Absolute path to the file that was written.
    """
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    filename = _snapshot_filename(snap)
    out_path = snapshots_dir / filename
    payload = snap.to_dict()
    out_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path


def load(path: Path) -> Snapshot:
    """Read a snapshot JSON file and return a Snapshot instance.

    Parameters
    ----------
    path:
        Absolute or relative path to the snapshot ``.json`` file.

    Returns
    -------
    Snapshot
        Fully-populated immutable Snapshot.

    Raises
    ------
    FileNotFoundError
        If the path does not exist.
    json.JSONDecodeError
        If the file is not valid JSON.
    KeyError
        If required fields are missing from the snapshot dict.
    """
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    return Snapshot.from_dict(data)


def find_latest(snapshots_dir: Path, n: int = 1) -> list[Path]:
    """Return up to n snapshot file paths from snapshots_dir, newest-first.

    Ordering is based on file modification time.  Returns an empty list if
    snapshots_dir does not exist or contains no ``.json`` files.

    Parameters
    ----------
    snapshots_dir:
        Directory to search.
    n:
        Maximum number of paths to return (default 1).

    Returns
    -------
    list[Path]
        Up to n Paths, sorted newest-first by mtime.
    """
    if not snapshots_dir.is_dir():
        return []

    json_files = [p for p in snapshots_dir.iterdir() if p.suffix == ".json" and p.is_file()]
    if not json_files:
        return []

    json_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return json_files[:n]
