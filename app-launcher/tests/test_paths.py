"""Tests for microapps_launcher.paths.

All tests are pure (no network, no subprocess).  A ``tmp_path``-based fake
repo root is used so nothing touches the real filesystem outside the temp
directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from microapps_launcher.models import App, Launch
from microapps_launcher.paths import (
    find_repo_root,
    resolve_command,
    resolve_cwd,
    resolve_in_cwd,
    resolve_repo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(cwd: str = "some/app") -> App:
    """Return a minimal frozen App suitable for path tests."""
    return App(
        id="test-app",
        name="Test App",
        description="",
        stack="python",
        cwd=cwd,
        launch=Launch(cmd=("python", "main.py")),
        launch_mode="console",
        stoppable=True,
    )


def _make_repo(tmp_path: Path) -> Path:
    """Create a fake repo root: ``apps.json`` + ``.git`` dir."""
    (tmp_path / "apps.json").write_text("{}")
    (tmp_path / ".git").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------


class TestFindRepoRoot:
    def test_finds_root_from_exact_dir(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        assert find_repo_root(root) == root

    def test_walks_up_from_nested_subdir(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        assert find_repo_root(deep) == root

    def test_walks_up_from_single_subdir(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        sub = tmp_path / "subdir"
        sub.mkdir()
        assert find_repo_root(sub) == root

    def test_raises_when_no_root_found(self, tmp_path: Path) -> None:
        # tmp_path has no apps.json or .git — should raise.
        with pytest.raises(FileNotFoundError, match="apps.json"):
            find_repo_root(tmp_path)

    def test_requires_both_markers(self, tmp_path: Path) -> None:
        # Only apps.json present — .git missing.
        (tmp_path / "apps.json").write_text("{}")
        with pytest.raises(FileNotFoundError):
            find_repo_root(tmp_path)

    def test_requires_both_markers_git_only(self, tmp_path: Path) -> None:
        # Only .git present — apps.json missing.
        (tmp_path / ".git").mkdir()
        with pytest.raises(FileNotFoundError):
            find_repo_root(tmp_path)

    def test_default_start_is_module_dir(self, tmp_path: Path) -> None:
        """find_repo_root() with no args must not raise (real repo root exists)."""
        # We can't fully control the default path in unit tests, but we can
        # at least verify it returns a Path and that both markers exist there.
        result = find_repo_root()
        assert isinstance(result, Path)
        assert (result / "apps.json").exists()
        assert (result / ".git").exists()


# ---------------------------------------------------------------------------
# resolve_repo
# ---------------------------------------------------------------------------


class TestResolveRepo:
    def test_forward_slash(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        result = resolve_repo(root, "foo/bar/baz.txt")
        assert result == (root / "foo" / "bar" / "baz.txt").resolve()

    def test_backslash_normalised(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        result = resolve_repo(root, "foo\\bar\\baz.txt")
        assert result == (root / "foo" / "bar" / "baz.txt").resolve()

    def test_simple_filename(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        assert resolve_repo(root, "apps.json") == (root / "apps.json").resolve()


# ---------------------------------------------------------------------------
# resolve_cwd
# ---------------------------------------------------------------------------


class TestResolveCwd:
    def test_returns_resolved_app_cwd(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app(cwd="services/my-service")
        result = resolve_cwd(root, app)
        assert result == (root / "services" / "my-service").resolve()


# ---------------------------------------------------------------------------
# resolve_in_cwd
# ---------------------------------------------------------------------------


class TestResolveInCwd:
    def test_resolves_relative_to_app_cwd(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app(cwd="services/my-service")
        result = resolve_in_cwd(root, app, "node_modules/.bin/tsc")
        expected = (root / "services" / "my-service" / "node_modules" / ".bin" / "tsc").resolve()
        assert result == expected

    def test_backslash_in_rel(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app(cwd="apps/foo")
        result = resolve_in_cwd(root, app, "dist\\main.exe")
        expected = (root / "apps" / "foo" / "dist" / "main.exe").resolve()
        assert result == expected


# ---------------------------------------------------------------------------
# resolve_command
# ---------------------------------------------------------------------------


class TestResolveCommand:
    def test_python_replaced_with_sys_executable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_exe = "/fake/python3.11"
        monkeypatch.setattr(sys, "executable", fake_exe)
        root = _make_repo(tmp_path)
        app = _make_app()
        result = resolve_command(root, app, ["python", "main.py"])
        assert result == [fake_exe, "main.py"]

    def test_pip_spliced_with_m_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_exe = "/fake/python3.11"
        monkeypatch.setattr(sys, "executable", fake_exe)
        root = _make_repo(tmp_path)
        app = _make_app()
        result = resolve_command(root, app, ["pip", "install", "-r", "requirements.txt"])
        assert result == [fake_exe, "-m", "pip", "install", "-r", "requirements.txt"]

    def test_relative_exe_with_forward_slash_resolved(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app(cwd="apps/myapp")
        result = resolve_command(root, app, ["./run.sh", "--port", "8080"])
        expected_head = str((root / "apps" / "myapp" / "./run.sh").resolve())
        assert result == [expected_head, "--port", "8080"]

    def test_relative_exe_with_backslash_resolved(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app(cwd="apps/myapp")
        result = resolve_command(root, app, ["dist\\server.exe", "--debug"])
        expected_head = str((root / "apps" / "myapp" / "dist" / "server.exe").resolve())
        assert result == [expected_head, "--debug"]

    def test_exe_suffix_triggers_resolution(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app(cwd="apps/myapp")
        result = resolve_command(root, app, ["myprogram.exe"])
        expected_head = str((root / "apps" / "myapp" / "myprogram.exe").resolve())
        assert result == [expected_head]

    def test_plain_binary_left_unchanged(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app()
        result = resolve_command(root, app, ["dotnet", "run", "--project", "MyApp.csproj"])
        assert result == ["dotnet", "run", "--project", "MyApp.csproj"]

    def test_node_left_unchanged(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app()
        result = resolve_command(root, app, ["node", "index.js"])
        assert result == ["node", "index.js"]

    def test_empty_cmd_returns_empty_list(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        app = _make_app()
        assert resolve_command(root, app, []) == []

    def test_does_not_mutate_input(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
        root = _make_repo(tmp_path)
        app = _make_app()
        original = ["python", "script.py"]
        result = resolve_command(root, app, original)
        # original must be untouched
        assert original == ["python", "script.py"]
        assert result is not original

    def test_remaining_args_always_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
        root = _make_repo(tmp_path)
        app = _make_app()
        result = resolve_command(root, app, ["python", "--flag", "value"])
        assert result[1:] == ["--flag", "value"]
