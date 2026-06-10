"""Unit tests for type-mismatch ConfigErrors raised by load_layout.

These complement tests/test_config.py (which covers happy paths plus a few
semantic errors) by exercising the *type* checks in ``_validate_pane`` and
``load_layout``: a field carrying the wrong TOML type must raise ConfigError
with a message that names the offending field.

Only behaviors the current code actually implements are asserted here. Any
type check that does not yet exist is intentionally left untested and noted
in the accompanying report rather than asserted speculatively.

Mirrors the import/bootstrap pattern in tests/test_config.py: import the
single-file module directly and resolve fixtures relative to this file.
"""

from __future__ import annotations

import unittest
import warnings
from pathlib import Path

import claude_panes


FIXTURES = Path(__file__).parent / "fixtures"


class TestPaneFieldTypeMismatch(unittest.TestCase):
    """Wrong-typed pane fields raise ConfigError naming the field."""

    def _load(self, fixture: str) -> None:
        # Some fixtures also trip unknown-key warnings; silence so the test
        # asserts purely on the raised ConfigError, not on warning noise.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            claude_panes.load_layout(FIXTURES / fixture)

    def test_size_non_numeric_raises(self) -> None:
        """A string `size` raises ConfigError mentioning size."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            self._load("type_mismatch_size.toml")
        message = str(ctx.exception)
        self.assertIn("size", message)
        # The diagnostic should point at the offending pane index.
        self.assertIn("panes[1]", message)

    def test_title_non_string_raises(self) -> None:
        """An integer `title` raises ConfigError mentioning title."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            self._load("type_mismatch_title.toml")
        message = str(ctx.exception)
        self.assertIn("title", message)
        self.assertIn("panes[0]", message)

    def test_parent_non_integer_raises(self) -> None:
        """A string `parent` raises ConfigError mentioning parent."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            self._load("type_mismatch_parent.toml")
        message = str(ctx.exception)
        self.assertIn("parent", message)
        self.assertIn("panes[1]", message)

    def test_working_dir_non_string_raises(self) -> None:
        """An integer `working_dir` raises ConfigError mentioning working_dir."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            self._load("type_mismatch_working_dir.toml")
        self.assertIn("working_dir", str(ctx.exception))


class TestPaneFieldTypeMismatchInline(unittest.TestCase):
    """Same checks driven directly through ``_validate_pane`` with built dicts.

    load_layout only accepts a Path, so these inline cases call the pane
    validator directly to prove the type guards independent of a fixture file.
    """

    def test_size_bool_rejected(self) -> None:
        """A bool `size` is rejected (bool is an int subclass but not a size)."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            claude_panes._validate_pane(
                {"cmd": "echo b", "size": True}, "panes", 1
            )
        self.assertIn("size", str(ctx.exception))

    def test_split_invalid_value_rejected(self) -> None:
        """An out-of-vocabulary `split` raises ConfigError mentioning split."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            claude_panes._validate_pane(
                {"cmd": "echo b", "split": "diagonal"}, "panes", 1
            )
        self.assertIn("split", str(ctx.exception))

    def test_pane_not_a_table_rejected(self) -> None:
        """A scalar where a pane table is expected raises ConfigError."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            claude_panes._validate_pane("not-a-table", "panes", 0)  # type: ignore[arg-type]
        self.assertIn("panes[0]", str(ctx.exception))


class TestTopLevelTypeMismatch(unittest.TestCase):
    """Wrong-typed top-level fields raise ConfigError naming the field."""

    def _load(self, fixture: str) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            claude_panes.load_layout(FIXTURES / fixture)

    def test_panes_scalar_rejected(self) -> None:
        """`panes` as a scalar string raises ConfigError mentioning panes.

        The current validator surfaces this via the "at least one pane" guard
        in ``_validate_panes`` (it isinstance-checks the list first), so the
        message names ``panes`` rather than emitting a dedicated "must be an
        array" diagnostic. We assert the field is named, not the exact phrase.
        """
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            self._load("type_mismatch_panes.toml")
        self.assertIn("panes", str(ctx.exception))

    def test_terminal_non_string_rejected(self) -> None:
        """An integer `terminal` raises ConfigError mentioning terminal."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            self._load("type_mismatch_terminal.toml")
        self.assertIn("terminal", str(ctx.exception))

    def test_shell_scalar_rejected(self) -> None:
        """`shell` as a scalar raises ConfigError mentioning shell."""
        with self.assertRaises(claude_panes.ConfigError) as ctx:
            self._load("type_mismatch_shell.toml")
        self.assertIn("shell", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
