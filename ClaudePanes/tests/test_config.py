from __future__ import annotations

import unittest
from pathlib import Path

import claude_panes


FIXTURES = Path(__file__).parent / "fixtures"


class TestMinimalConfig(unittest.TestCase):
    """Loading the smallest valid layout: one top-level [[panes]] entry."""

    def test_loads_minimal_config(self) -> None:
        """A one-pane TOML loads as one tab containing one pane with the cmd."""
        layout = claude_panes.load_layout(FIXTURES / "minimal.toml")
        self.assertEqual(len(layout.tabs), 1)
        self.assertEqual(len(layout.tabs[0].panes), 1)
        self.assertEqual(layout.tabs[0].panes[0].cmd, "echo hello")

    def test_minimal_normalizes_to_tab(self) -> None:
        """Top-level [[panes]] is normalized to a single implicit Tab wrapper."""
        layout = claude_panes.load_layout(FIXTURES / "minimal.toml")
        self.assertEqual(len(layout.tabs), 1)
        self.assertIsInstance(layout.tabs[0], claude_panes.Tab)
        self.assertIsInstance(layout.tabs[0].panes[0], claude_panes.Pane)


class TestTwoPanesVSplit(unittest.TestCase):
    """A two-pane single-tab layout with a vertical split and explicit size."""

    def setUp(self) -> None:
        self.layout = claude_panes.load_layout(FIXTURES / "two_panes_vsplit.toml")
        self.panes = self.layout.tabs[0].panes

    def test_loads_two_panes(self) -> None:
        """The fixture yields one tab with two panes and a 0.4 size on pane 1."""
        self.assertEqual(len(self.layout.tabs), 1)
        self.assertEqual(len(self.panes), 2)
        self.assertEqual(self.panes[1].split, "vertical")
        self.assertEqual(self.panes[1].size, 0.4)

    def test_first_pane_has_no_split(self) -> None:
        """The anchor pane (index 0) has no split direction."""
        self.assertIsNone(self.panes[0].split)

    def test_second_pane_split_vertical(self) -> None:
        """Pane index 1 declares split = vertical per the fixture."""
        self.assertEqual(self.panes[1].split, "vertical")


class TestThreePanesMixed(unittest.TestCase):
    """Three panes: vertical split then horizontal split with explicit parent."""

    def setUp(self) -> None:
        self.layout = claude_panes.load_layout(FIXTURES / "three_panes_mixed.toml")
        self.panes = self.layout.tabs[0].panes

    def test_parent_field(self) -> None:
        """Pane index 2 anchors against pane index 1 via the parent field."""
        self.assertEqual(self.panes[2].parent, 1)

    def test_split_values(self) -> None:
        """Pane 0 has no split, pane 1 is vertical, pane 2 is horizontal."""
        self.assertIsNone(self.panes[0].split)
        self.assertEqual(self.panes[1].split, "vertical")
        self.assertEqual(self.panes[2].split, "horizontal")


class TestMultiTab(unittest.TestCase):
    """A [[tabs]] layout with two tabs, each holding two panes."""

    def setUp(self) -> None:
        self.layout = claude_panes.load_layout(FIXTURES / "multi_tab.toml")

    def test_two_tabs(self) -> None:
        """The fixture defines exactly two tabs."""
        self.assertEqual(len(self.layout.tabs), 2)

    def test_tab_titles(self) -> None:
        """Each tab carries its declared title verbatim."""
        self.assertEqual(self.layout.tabs[0].title, "Tab one")
        self.assertEqual(self.layout.tabs[1].title, "Tab two")

    def test_tab_panes(self) -> None:
        """Both tabs contain two panes each."""
        self.assertEqual(len(self.layout.tabs[0].panes), 2)
        self.assertEqual(len(self.layout.tabs[1].panes), 2)


class TestTerminalOverride(unittest.TestCase):
    """The top-level terminal field pins the adapter explicitly."""

    def test_terminal_field_loaded(self) -> None:
        """layout.terminal reflects the explicit terminal = "wezterm" value."""
        layout = claude_panes.load_layout(FIXTURES / "terminal_override.toml")
        self.assertEqual(layout.terminal, "wezterm")


class TestShellPrelude(unittest.TestCase):
    """The [shell].prelude string is exposed on the loaded Layout."""

    def test_shell_prelude_loaded(self) -> None:
        """layout.shell_prelude matches the verbatim string from the fixture."""
        layout = claude_panes.load_layout(FIXTURES / "with_shell_prelude.toml")
        self.assertEqual(layout.shell_prelude, "cd ~/work")


class TestValidationErrors(unittest.TestCase):
    """Each invalid fixture raises ConfigError with a useful diagnostic."""

    def test_missing_cmd_raises(self) -> None:
        """A pane without cmd raises ConfigError mentioning cmd and a field path."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            claude_panes.load_layout(FIXTURES / "missing_cmd.toml")
        message = str(ctx.exception)
        self.assertIn("cmd", message)
        self.assertTrue(
            "panes[0]" in message or "tabs[0].panes[0]" in message,
            f"expected diagnostic to mention 'panes[0]' or 'tabs[0].panes[0]', got: {message!r}",
        )

    def test_bad_size_raises(self) -> None:
        """A pane size outside (0, 1) raises ConfigError mentioning size."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            claude_panes.load_layout(FIXTURES / "bad_size.toml")
        self.assertIn("size", str(ctx.exception))

    def test_both_panes_and_tabs_raises(self) -> None:
        """A file with both [[panes]] and [[tabs]] raises ConfigError mentioning the conflict."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            claude_panes.load_layout(FIXTURES / "both_panes_and_tabs.toml")
        message = str(ctx.exception)
        self.assertTrue(
            "panes" in message and "tabs" in message,
            f"expected diagnostic to mention both 'panes' and 'tabs', got: {message!r}",
        )

    def test_missing_file_raises(self) -> None:
        """Loading a path that does not exist raises FileNotFoundError or ConfigError."""
        missing = Path("does/not/exist.toml")
        with self.assertRaises((FileNotFoundError, claude_panes.ConfigError)):
            claude_panes.load_layout(missing)


class TestUnknownField(unittest.TestCase):
    """Per config-format.md s6, unknown top-level keys produce a warning, not an error."""

    def test_unknown_field_handling(self) -> None:
        """Unknown fields trigger a UserWarning but the layout still loads."""
        with self.assertWarns(Warning):
            layout = claude_panes.load_layout(FIXTURES / "unknown_field.toml")
        self.assertIsInstance(layout, claude_panes.Layout)
        self.assertGreaterEqual(len(layout.tabs), 1)
        self.assertGreaterEqual(len(layout.tabs[0].panes), 1)


if __name__ == "__main__":
    unittest.main()
