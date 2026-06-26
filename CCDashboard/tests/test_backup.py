"""Tests for the backup engine (``ccdashboard.backup``).

Every test stays inside ``tmp_path``: settings round-trips use an explicit
``path=`` argument, and the ``get_backup_dir`` / ``set_backup_dir`` helpers (which
read the module-level :func:`ccdashboard.backup.settings_path`) are isolated by
monkeypatching that function to a temp file. The user's real
``~/.claude/ccdashboard/settings.json`` and real backup directory are never read
or written.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ccdashboard import backup

pytestmark = pytest.mark.unit

_DEST_RE = re.compile(r"^claude-backup-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _build_config_tree(root: Path) -> dict[str, str]:
    """Create a small fake ~/.claude tree under ``root``; return {relpath: content}."""
    files = {
        "settings.json": '{"theme": "dark"}',
        "CLAUDE.md": "# global instructions\nbe concise\n",
        "projects/foo/progress.md": "did a thing\n",
        "rules/python/style.md": "use black\n",
    }
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return files


# --------------------------------------------------------------------------- #
# settings: save/load round-trip (explicit temp path — no monkeypatch)
# --------------------------------------------------------------------------- #


def test_save_load_settings_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    payload = {"backup_dir": "D:\\Backups\\cc", "other": 5}

    backup.save_settings(payload, path=p)
    assert p.exists()
    assert backup.load_settings(path=p) == payload


def test_load_settings_missing_returns_empty(tmp_path: Path) -> None:
    assert backup.load_settings(path=tmp_path / "nope.json") == {}


def test_load_settings_malformed_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{ not valid json", encoding="utf-8")
    assert backup.load_settings(path=p) == {}


# --------------------------------------------------------------------------- #
# get_backup_dir / set_backup_dir (monkeypatched settings_path)
# --------------------------------------------------------------------------- #


def test_get_backup_dir_defaults_when_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_file = tmp_path / "settings.json"  # does not exist
    monkeypatch.setattr(backup, "settings_path", lambda: settings_file)

    assert backup.get_backup_dir() == str(backup.DEFAULT_BACKUP_DIR)


def test_set_then_get_backup_dir_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(backup, "settings_path", lambda: settings_file)

    backup.set_backup_dir("E:\\Snapshots\\claude")

    assert backup.get_backup_dir() == "E:\\Snapshots\\claude"
    assert backup.load_settings(path=settings_file)["backup_dir"] == "E:\\Snapshots\\claude"


def test_set_backup_dir_merges_existing_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(backup, "settings_path", lambda: settings_file)

    backup.save_settings({"other": "keep-me"})  # uses monkeypatched path
    backup.set_backup_dir("F:\\cc")

    stored = backup.load_settings(path=settings_file)
    assert stored == {"other": "keep-me", "backup_dir": "F:\\cc"}


# --------------------------------------------------------------------------- #
# backup_claude
# --------------------------------------------------------------------------- #


def test_backup_claude_copies_tree(tmp_path: Path) -> None:
    config_dir = tmp_path / "dot-claude"
    backup_dir = tmp_path / "Backup Claude Code"
    files = _build_config_tree(config_dir)

    result = backup.backup_claude(config_dir, backup_dir)

    dest = Path(result["dest"])
    # The dated destination lives under backup_dir and matches the naming contract.
    assert dest.parent == backup_dir
    assert _DEST_RE.match(dest.name)

    assert result["files"] == len(files)
    assert result["bytes"] > 0
    assert result["skipped"] == 0
    assert result["errors"] == []

    # Every source file is reproduced byte-for-byte at the same relative path.
    expected_bytes = 0
    for rel, content in files.items():
        copied = dest / rel
        assert copied.is_file()
        assert copied.read_text(encoding="utf-8") == content
        expected_bytes += (config_dir / rel).stat().st_size
    assert result["bytes"] == expected_bytes


def test_backup_claude_dry_run_creates_nothing(tmp_path: Path) -> None:
    config_dir = tmp_path / "dot-claude"
    backup_dir = tmp_path / "backups"  # intentionally not pre-created
    _build_config_tree(config_dir)

    result = backup.backup_claude(config_dir, backup_dir, dry_run=True)

    assert result == {"dest": result["dest"], "dry_run": True}
    assert set(result) == {"dest", "dry_run"}
    assert _DEST_RE.match(Path(result["dest"]).name)
    # Nothing was written: neither the dated dest nor the backup root exist.
    assert not Path(result["dest"]).exists()
    assert not backup_dir.exists()


def test_backup_claude_rejects_backup_dir_inside_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "dot-claude"
    _build_config_tree(config_dir)
    backup_dir = config_dir / "nested" / "backups"  # inside config_dir -> recursion

    with pytest.raises(ValueError):
        backup.backup_claude(config_dir, backup_dir)


def test_backup_claude_rejects_backup_dir_equal_to_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "dot-claude"
    _build_config_tree(config_dir)

    with pytest.raises(ValueError):
        backup.backup_claude(config_dir, config_dir)


def test_backup_claude_empty_tree_still_creates_dest(tmp_path: Path) -> None:
    config_dir = tmp_path / "empty-claude"
    config_dir.mkdir()
    backup_dir = tmp_path / "backups"

    result = backup.backup_claude(config_dir, backup_dir)

    assert result["files"] == 0
    assert result["bytes"] == 0
    assert result["skipped"] == 0
    assert Path(result["dest"]).is_dir()
