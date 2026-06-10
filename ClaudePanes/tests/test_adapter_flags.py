"""Unit tests for per-pane flag/argv emission across the terminal adapters.

tests/test_adapters.py covers split orientation, tab/session shape, and the
shell-wrapping of cmd. This module focuses narrowly on how a pane's ``size``
and ``working_dir`` surface in each adapter's produced argv / KDL:

- WindowsTerminalAdapter: ``--startingDirectory <dir>`` and ``-s <float>``
- TmuxAdapter:            ``-c <dir>`` and ``-p <int-percent>``
- ZellijAdapter (KDL):    ``size "<int-percent>%"``  (working_dir is NOT
                          emitted today -- see report)

All assertions reflect the REAL current behavior of the code. Where the
user's cmd is shell-wrapped (e.g. ``cmd.exe /c <cmd>`` on this Windows host),
tests assert on the cmd text via substring (assertIn over the joined argv /
KDL) so they stay robust to the exact wrapper, which is owned/edited
elsewhere.

Mirrors the import/bootstrap pattern in tests/test_adapters.py: build Layout
objects directly from the dataclasses.
"""

from __future__ import annotations

import unittest

import claude_panes


def _layout_with(panes: list[claude_panes.Pane]) -> claude_panes.Layout:
    """Single-tab Layout wrapping the given pre-built Pane objects."""
    return claude_panes.Layout(
        name="flags",
        terminal=None,
        working_dir=None,
        shell_prelude="",
        tabs=(claude_panes.Tab(title=None, panes=tuple(panes)),),
    )


class TestWindowsTerminalFlags(unittest.TestCase):
    """wt.exe emits --startingDirectory and -s for working_dir/size."""

    def setUp(self) -> None:
        self.adapter = claude_panes.WindowsTerminalAdapter()

    def test_working_dir_emits_starting_directory(self) -> None:
        """A pane working_dir surfaces as --startingDirectory <dir>."""
        layout = _layout_with([claude_panes.Pane(cmd="echo a", working_dir="/tmp/work")])
        argv = self.adapter.build_command(layout)
        self.assertIn("--startingDirectory", argv)
        idx = argv.index("--startingDirectory")
        # _expand normalizes the path; on POSIX-style input it stays as-is.
        self.assertIn("work", argv[idx + 1])

    def test_size_emits_dash_s_with_raw_float(self) -> None:
        """A split pane's size surfaces as -s <float> (wt takes a fraction)."""
        layout = _layout_with(
            [
                claude_panes.Pane(cmd="echo a"),
                claude_panes.Pane(cmd="echo b", split="vertical", size=0.4),
            ]
        )
        argv = self.adapter.build_command(layout)
        self.assertIn("-s", argv)
        idx = argv.index("-s")
        self.assertEqual(argv[idx + 1], "0.4")

    def test_pane_working_dir_present_on_split(self) -> None:
        """A split pane's own working_dir is emitted for that pane."""
        layout = _layout_with(
            [
                claude_panes.Pane(cmd="echo a"),
                claude_panes.Pane(cmd="echo b", split="vertical", working_dir="/tmp/right"),
            ]
        )
        argv = self.adapter.build_command(layout)
        joined = " ".join(argv)
        self.assertIn("right", joined)
        # The user's cmd survives verbatim somewhere in the argv (assert on the
        # cmd text, not the wrapper which is owned elsewhere).
        self.assertIn("echo b", joined)


class TestTmuxFlags(unittest.TestCase):
    """tmux emits -c for working_dir and -p <percent> for size."""

    def setUp(self) -> None:
        self.adapter = claude_panes.TmuxAdapter()

    def test_working_dir_emits_dash_c(self) -> None:
        """A working_dir on the anchor pane surfaces as -c <dir>."""
        layout = _layout_with([claude_panes.Pane(cmd="echo a", working_dir="/tmp/work")])
        argv = self.adapter.build_command(layout)
        self.assertIn("-c", argv)
        idx = argv.index("-c")
        self.assertIn("work", argv[idx + 1])

    def test_size_emits_dash_p_as_integer_percent(self) -> None:
        """A split pane size of 0.4 surfaces as -p 40 (tmux uses percentages)."""
        layout = _layout_with(
            [
                claude_panes.Pane(cmd="echo a"),
                claude_panes.Pane(cmd="echo b", split="vertical", size=0.4),
            ]
        )
        argv = self.adapter.build_command(layout)
        self.assertIn("-p", argv)
        idx = argv.index("-p")
        self.assertEqual(argv[idx + 1], "40")

    def test_split_pane_working_dir_emits_dash_c(self) -> None:
        """A split pane's own working_dir is emitted via a second -c."""
        layout = _layout_with(
            [
                claude_panes.Pane(cmd="echo a"),
                claude_panes.Pane(cmd="echo b", split="vertical", working_dir="/tmp/right"),
            ]
        )
        argv = self.adapter.build_command(layout)
        joined = " ".join(argv)
        self.assertIn("right", joined)
        # There should be a -c whose value carries the split pane's dir.
        c_values = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-c"]
        self.assertTrue(
            any("right" in v for v in c_values),
            f"expected a -c carrying the split pane dir, got -c values {c_values}",
        )


class TestZellijFlags(unittest.TestCase):
    """Zellij KDL emits size as a quoted percentage in the pane block."""

    def setUp(self) -> None:
        self.adapter = claude_panes.ZellijAdapter()

    def test_size_emits_quoted_percent(self) -> None:
        """A split pane size of 0.4 surfaces as size \"40%\" in the KDL."""
        layout = _layout_with(
            [
                claude_panes.Pane(cmd="echo a"),
                claude_panes.Pane(cmd="echo b", split="vertical", size=0.4),
            ]
        )
        kdl = self.adapter.build_kdl(layout)
        self.assertIn('size "40%"', kdl)

    def test_cmd_survives_in_kdl_args(self) -> None:
        """The user's cmd rides verbatim inside the KDL args (assert on cmd
        text, not the host-shell wrapper which is owned elsewhere)."""
        layout = _layout_with([claude_panes.Pane(cmd="npm run dev")])
        kdl = self.adapter.build_kdl(layout)
        self.assertIn('"npm run dev"', kdl)

    def test_working_dir_not_emitted_today(self) -> None:
        """KNOWN GAP: the KDL renderer does not emit a pane cwd/working_dir.

        This documents (and pins) the current behavior so a future change that
        starts emitting cwd is a deliberate, visible update rather than a
        silent surprise. See report for details.
        """
        layout = _layout_with([claude_panes.Pane(cmd="echo a", working_dir="/tmp/work")])
        kdl = self.adapter.build_kdl(layout)
        self.assertNotIn("cwd", kdl)
        self.assertNotIn("/tmp/work", kdl)


if __name__ == "__main__":
    unittest.main()
