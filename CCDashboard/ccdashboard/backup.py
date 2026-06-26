"""
backup.py — back up the user's global ``~/.claude`` folder to a dated snapshot.

UI-agnostic and pure stdlib. The backup destination is a persisted user setting
stored OUTSIDE the repo at ``~/.claude/ccdashboard/settings.json`` (the same
out-of-repo, atomically-written JSON store style used by ``quiz.py`` —
``tempfile.mkstemp`` + ``os.replace``), so a value the user types in the TUI
survives restarts without ever touching tracked files.

Public surface:
  * settings_path()              -> Path to the private settings JSON.
  * load_settings() / save_settings(...)  -> round-trippable dict store (atomic).
  * get_backup_dir() / set_backup_dir(...) -> the persisted backup directory,
                                   defaulting to ``DEFAULT_BACKUP_DIR`` when unset.
  * backup_claude(config_dir, backup_dir, *, dry_run=False) -> dict
        Copy ``config_dir`` recursively into a freshly-dated subfolder
        ``claude-backup-YYYY-MM-DD_HH-MM-SS`` under ``backup_dir``. Robust: a
        single unreadable file is skipped and recorded, never fatal. Guards
        against backing the folder up into itself.

Nothing here mutates its inputs: ``set_backup_dir`` merges into a NEW dict and
``backup_claude`` only reads ``config_dir`` and writes under ``backup_dir``.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_BACKUP_DIR: Path = Path.home() / "Backup Claude Code"
_BACKUP_PREFIX = "claude-backup-"
_STAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"


# --------------------------------------------------------------------------- #
# Persistent settings (OUT OF REPO, atomic JSON — mirrors quiz.py)
# --------------------------------------------------------------------------- #


def settings_path() -> Path:
    """Path to the private settings store at ``~/.claude/ccdashboard/settings.json``."""
    return Path.home() / ".claude" / "ccdashboard" / "settings.json"


def load_settings(path: Path | None = None) -> dict:
    """Load the settings dict; return ``{}`` if missing, unreadable or malformed."""
    p = path or settings_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_settings(settings: dict, path: Path | None = None) -> None:
    """Atomically write ``settings``, creating ``~/.claude/ccdashboard`` on first use."""
    p = path or settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def get_backup_dir() -> str:
    """Return the persisted backup directory, or ``str(DEFAULT_BACKUP_DIR)`` if unset."""
    return load_settings().get("backup_dir") or str(DEFAULT_BACKUP_DIR)


def set_backup_dir(path: str) -> None:
    """Persist ``path`` as the backup directory, merging (not clobbering) other keys."""
    settings = load_settings()
    save_settings({**settings, "backup_dir": path})


# --------------------------------------------------------------------------- #
# Backup engine
# --------------------------------------------------------------------------- #


def backup_claude(
    config_dir: Path,
    backup_dir: str | Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Copy ``config_dir`` into a dated snapshot folder under ``backup_dir``.

    The destination is ``backup_dir/claude-backup-YYYY-MM-DD_HH-MM-SS``.

    Guards FIRST against recursion: if ``backup_dir`` resolves to a location
    inside (or equal to) ``config_dir`` a :class:`ValueError` is raised before
    anything is created, so the folder is never backed up into itself.

    With ``dry_run=True`` nothing is copied — only the planned destination is
    returned as ``{"dest": str, "dry_run": True}``.

    Otherwise the tree is walked with :func:`os.walk` and copied file-by-file
    with :func:`shutil.copy2`, creating destination subdirectories as needed. A
    per-file ``OSError``/``PermissionError`` (e.g. a locked or unreadable file)
    is swallowed: the source path is appended to ``errors`` and ``skipped`` is
    incremented; that file is NOT counted in ``files``. A single bad file never
    aborts the backup.

    Returns ``{"dest", "files", "bytes", "skipped", "errors"}``.
    """
    config_path = Path(config_dir)
    backup_root = Path(backup_dir)

    # Recursion guard FIRST: refuse to back a folder up into itself / a subfolder.
    if backup_root.resolve().is_relative_to(config_path.resolve()):
        raise ValueError(
            f"backup_dir ({backup_root}) is inside config_dir ({config_path}); "
            "refusing to back the folder up into itself."
        )

    dest = backup_root / (_BACKUP_PREFIX + datetime.now().strftime(_STAMP_FORMAT))

    if dry_run:
        return {"dest": str(dest), "dry_run": True}

    files = 0
    total_bytes = 0
    skipped = 0
    errors: list[str] = []

    # Always materialise the dated root so an empty (or absent) tree still yields it.
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # per-file copies below will surface the failure as skips

    for root, _dirs, filenames in os.walk(config_path):
        rel = Path(root).relative_to(config_path)
        target_dir = dest / rel
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # let each copy2 fail and be recorded per-file
        for name in filenames:
            src_file = Path(root) / name
            dst_file = target_dir / name
            try:
                shutil.copy2(src_file, dst_file)
                total_bytes += dst_file.stat().st_size
                files += 1
            except (OSError, PermissionError):
                errors.append(str(src_file))
                skipped += 1

    return {
        "dest": str(dest),
        "files": files,
        "bytes": total_bytes,
        "skipped": skipped,
        "errors": errors,
    }


if __name__ == "__main__":  # read-only smoke test (copies nothing)
    print(f"settings_path : {settings_path()}")
    print(f"backup_dir    : {get_backup_dir()}")
    print(f"default       : {DEFAULT_BACKUP_DIR}")
