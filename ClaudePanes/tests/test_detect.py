"""Unit tests for ``detect_terminal`` precedence, override, and failure modes.

The detection logic (claude_panes.detect_terminal) walks ADAPTER_PRIORITY
("wt", "wezterm", "tmux", "zellij") and returns the first adapter whose
binary is found, unless an explicit override is supplied. Availability is
made deterministic by patching ``shutil.which`` (the name each adapter's
``is_available`` calls into) so these tests never depend on what is actually
installed on the host.

Note: WindowsTerminalAdapter.is_available() is additionally gated on
sys.platform == "win32"; the relevant tests pin the platform so the gate is
explicit rather than incidental to the test runner's OS.

Mirrors the import/bootstrap pattern in tests/test_config.py.
"""

from __future__ import annotations

import unittest
from unittest import mock

import claude_panes


def _which_for(*available: str):
    """Return a fake ``shutil.which`` that only resolves the given binaries."""
    present = set(available)

    def fake_which(binary: str, *_args, **_kwargs):
        return f"/usr/bin/{binary}" if binary in present else None

    return fake_which


class TestDetectPrecedence(unittest.TestCase):
    """The first available adapter in ADAPTER_PRIORITY order wins."""

    def test_priority_order_matches_documented_constant(self) -> None:
        """Sanity-check the order this suite relies on."""
        self.assertEqual(
            claude_panes.ADAPTER_PRIORITY, ("wt", "wezterm", "tmux", "zellij")
        )

    def test_wt_wins_when_all_available(self) -> None:
        """wt is highest priority, so it wins when everything is installed."""
        with mock.patch.object(claude_panes.sys, "platform", "win32"):
            with mock.patch(
                "shutil.which", side_effect=_which_for("wt", "wezterm", "tmux", "zellij")
            ):
                self.assertEqual(claude_panes.detect_terminal(), "wt")

    def test_wezterm_wins_when_wt_absent(self) -> None:
        """With wt missing, wezterm is the next in priority order."""
        with mock.patch.object(claude_panes.sys, "platform", "win32"):
            with mock.patch(
                "shutil.which", side_effect=_which_for("wezterm", "tmux", "zellij")
            ):
                self.assertEqual(claude_panes.detect_terminal(), "wezterm")

    def test_tmux_wins_over_zellij(self) -> None:
        """tmux precedes zellij in priority order."""
        with mock.patch(
            "shutil.which", side_effect=_which_for("tmux", "zellij")
        ):
            self.assertEqual(claude_panes.detect_terminal(), "tmux")

    def test_zellij_last_resort(self) -> None:
        """zellij is chosen only when it is the sole available terminal."""
        with mock.patch("shutil.which", side_effect=_which_for("zellij")):
            self.assertEqual(claude_panes.detect_terminal(), "zellij")

    def test_wt_skipped_off_windows_even_if_on_path(self) -> None:
        """wt.is_available() is win32-gated: off Windows it is skipped even if
        ``which('wt')`` would resolve, so the next available adapter wins."""
        with mock.patch.object(claude_panes.sys, "platform", "linux"):
            with mock.patch(
                "shutil.which", side_effect=_which_for("wt", "tmux")
            ):
                self.assertEqual(claude_panes.detect_terminal(), "tmux")


class TestDetectOverride(unittest.TestCase):
    """An explicit override pre-empts priority detection when available."""

    def test_override_wins_when_available(self) -> None:
        """A valid, installed override is returned even if a higher-priority
        terminal is also present."""
        with mock.patch.object(claude_panes.sys, "platform", "win32"):
            with mock.patch(
                "shutil.which", side_effect=_which_for("wt", "tmux", "zellij")
            ):
                # wt would win by priority; the override forces zellij.
                self.assertEqual(claude_panes.detect_terminal("zellij"), "zellij")

    def test_override_unavailable_raises(self) -> None:
        """A valid override whose binary is missing raises NoTerminalError that
        names the requested terminal and its binary."""
        with mock.patch("shutil.which", side_effect=_which_for("tmux")):
            with self.assertRaises(claude_panes.NoTerminalError) as ctx:
                claude_panes.detect_terminal("zellij")
        message = str(ctx.exception)
        self.assertIn("zellij", message)

    def test_invalid_override_name_raises(self) -> None:
        """An override outside SUPPORTED_TERMINALS raises NoTerminalError before
        any availability probing."""
        with self.assertRaises(claude_panes.NoTerminalError) as ctx:
            claude_panes.detect_terminal("kitty")
        self.assertIn("kitty", str(ctx.exception))


class TestDetectNoneAvailable(unittest.TestCase):
    """When nothing usable is on PATH, NoTerminalError is raised."""

    def test_no_terminal_raises(self) -> None:
        """No adapter available -> NoTerminalError listing the attempted names."""
        with mock.patch.object(claude_panes.sys, "platform", "linux"):
            with mock.patch("shutil.which", return_value=None):
                with self.assertRaises(claude_panes.NoTerminalError) as ctx:
                    claude_panes.detect_terminal()
        message = str(ctx.exception)
        # The diagnostic enumerates what it tried.
        for name in claude_panes.ADAPTER_PRIORITY:
            self.assertIn(name, message)


if __name__ == "__main__":
    unittest.main()
