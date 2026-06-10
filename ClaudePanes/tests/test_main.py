"""Unit tests for ``main()`` exit-code mapping.

main() dispatches subcommands and maps raised ClaudePanesError subclasses to
their ``exit_code`` (ConfigError -> EXIT_CONFIG, NoTerminalError ->
EXIT_NO_TERMINAL, etc.), with a last-resort EXIT_UNEXPECTED guard. These tests
drive main() directly by passing an ``argv`` list and capture stdout/stderr
with contextlib redirects -- no shelling out.

Where a subcommand probes installed terminals (``detect``), ``shutil.which``
is patched so the result does not depend on the host. ``version`` and an empty
invocation are host-independent.

Mirrors the import/bootstrap pattern in tests/test_config.py: import the
single-file module directly and resolve fixtures relative to this file.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

import claude_panes


FIXTURES = Path(__file__).parent / "fixtures"


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    """Invoke main(argv), returning (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = claude_panes.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestNoSubcommand(unittest.TestCase):
    """An empty invocation prints help and returns EXIT_OK."""

    def test_empty_argv_prints_help_returns_ok(self) -> None:
        """main([]) -> help on stdout, EXIT_OK."""
        rc, out, _err = _run_main([])
        self.assertEqual(rc, claude_panes.EXIT_OK)
        # argparse prints usage/help to stdout for print_help().
        self.assertIn("usage", out.lower())
        # The subcommand list should be advertised in the help text.
        self.assertIn("validate", out)


class TestVersion(unittest.TestCase):
    """`version` prints tool + interpreter versions and returns EXIT_OK."""

    def test_version_returns_ok(self) -> None:
        """main(["version"]) -> EXIT_OK with the version string on stdout."""
        rc, out, _err = _run_main(["version"])
        self.assertEqual(rc, claude_panes.EXIT_OK)
        self.assertIn("claude-panes", out)
        self.assertIn(claude_panes.VERSION, out)


class TestDetectExit(unittest.TestCase):
    """`detect` returns EXIT_OK when a terminal exists, EXIT_NO_TERMINAL else."""

    def test_detect_ok_when_a_terminal_is_available(self) -> None:
        """With at least one terminal on PATH, detect returns EXIT_OK."""
        def fake_which(binary, *_a, **_k):
            return "/usr/bin/wt" if binary == "wt" else None

        with mock.patch.object(claude_panes.sys, "platform", "win32"):
            with mock.patch("shutil.which", side_effect=fake_which):
                rc, out, _err = _run_main(["detect"])
        self.assertEqual(rc, claude_panes.EXIT_OK)
        self.assertIn("wt", out)

    def test_detect_no_terminal_maps_to_exit_no_terminal(self) -> None:
        """With nothing on PATH, the raised NoTerminalError maps to its code."""
        with mock.patch.object(claude_panes.sys, "platform", "linux"):
            with mock.patch("shutil.which", return_value=None):
                rc, _out, err = _run_main(["detect"])
        self.assertEqual(rc, claude_panes.EXIT_NO_TERMINAL)
        # Errors are reported on stderr with an "error:" prefix.
        self.assertIn("error", err.lower())


class TestValidateExit(unittest.TestCase):
    """`validate` returns EXIT_OK on a good config, EXIT_CONFIG on a bad one."""

    def test_validate_good_config_returns_ok(self) -> None:
        """A valid layout path validates and returns EXIT_OK with an OK line."""
        good = str(FIXTURES / "minimal.toml")
        rc, out, _err = _run_main(["validate", good])
        self.assertEqual(rc, claude_panes.EXIT_OK)
        self.assertIn("OK", out)

    def test_validate_bad_config_returns_config_exit_code(self) -> None:
        """A layout failing validation maps ConfigError -> EXIT_CONFIG."""
        bad = str(FIXTURES / "bad_size.toml")
        rc, _out, err = _run_main(["validate", bad])
        self.assertEqual(rc, claude_panes.EXIT_CONFIG)
        # ConfigError.exit_code is the contract under test.
        self.assertEqual(
            claude_panes.ConfigError.exit_code, claude_panes.EXIT_CONFIG
        )
        self.assertIn("error", err.lower())

    def test_validate_missing_file_returns_config_exit_code(self) -> None:
        """A nonexistent layout path also maps to EXIT_CONFIG."""
        missing = str(FIXTURES / "does_not_exist_anywhere.toml")
        rc, _out, err = _run_main(["validate", missing])
        self.assertEqual(rc, claude_panes.EXIT_CONFIG)
        self.assertIn("error", err.lower())


class TestExitCodeConstants(unittest.TestCase):
    """Pin the error-class -> exit-code wiring that main() relies on."""

    def test_error_classes_map_to_expected_codes(self) -> None:
        """Each ClaudePanesError subclass advertises its documented code."""
        self.assertEqual(claude_panes.EXIT_OK, 0)
        self.assertEqual(claude_panes.ClaudePanesError.exit_code, claude_panes.EXIT_UNEXPECTED)
        self.assertEqual(claude_panes.ConfigError.exit_code, claude_panes.EXIT_CONFIG)
        self.assertEqual(claude_panes.NoTerminalError.exit_code, claude_panes.EXIT_NO_TERMINAL)
        self.assertEqual(claude_panes.ExecutionError.exit_code, claude_panes.EXIT_EXEC)


if __name__ == "__main__":
    unittest.main()
