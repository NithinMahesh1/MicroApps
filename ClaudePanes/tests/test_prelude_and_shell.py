"""Unit tests for two cross-platform behaviors in ClaudePanes:

1. ``_apply_prelude`` — the ``[shell].prelude`` string is prepended to every
   pane's ``cmd`` joined with `` && `` so the pane command runs only if the
   prelude succeeds (per docs/config-format.md s2.2 / s5.2).
2. ``_shell_wrap`` — the host-shell invocation wrapped around an opaque ``cmd``
   string. Windows uses ``cmd.exe /c``; POSIX honors ``$SHELL`` with ``-lc``
   when set and falls back to ``/bin/sh -c`` otherwise (per docs/security.md s4
   and docs/terminal-adapters.md).

These mirror the import/bootstrap pattern in tests/test_config.py: import the
single-file module directly and resolve fixtures relative to this file.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

import claude_panes


FIXTURES = Path(__file__).parent / "fixtures"


class TestApplyPrelude(unittest.TestCase):
    """`_apply_prelude` joins the prelude to each pane cmd with ' && '."""

    def _make_panes(self) -> tuple[claude_panes.Pane, ...]:
        return (
            claude_panes.Pane(cmd="echo first", title="First"),
            claude_panes.Pane(cmd="echo second", split="vertical", size=0.5),
        )

    def test_prelude_joined_with_double_ampersand(self) -> None:
        """Each resulting pane cmd is exactly f'{prelude} && {original_cmd}'."""
        prelude = "cd ~/work"
        panes = self._make_panes()
        result = claude_panes._apply_prelude(panes, prelude)

        self.assertEqual(len(result), len(panes))
        for original, wrapped in zip(panes, result):
            self.assertEqual(wrapped.cmd, f"{prelude} && {original.cmd}")

    def test_prelude_preserves_other_pane_fields(self) -> None:
        """Joining the prelude rebuilds panes without disturbing other fields."""
        panes = self._make_panes()
        result = claude_panes._apply_prelude(panes, "cd ~/work")

        # The second pane carried split/size; those must survive verbatim.
        self.assertEqual(result[0].title, "First")
        self.assertEqual(result[1].split, "vertical")
        self.assertEqual(result[1].size, 0.5)

    def test_empty_prelude_leaves_cmds_unchanged(self) -> None:
        """An empty prelude returns the panes untouched (no ' && ' prepended)."""
        panes = self._make_panes()
        result = claude_panes._apply_prelude(panes, "")

        self.assertEqual([p.cmd for p in result], [p.cmd for p in panes])
        # Empty prelude is a no-op: the original tuple is returned as-is.
        self.assertIs(result, panes)

    def test_prelude_applied_through_load_layout(self) -> None:
        """The fixture's prelude is joined to every loaded pane cmd with ' && '."""
        layout = claude_panes.load_layout(FIXTURES / "with_shell_prelude.toml")
        prelude = layout.shell_prelude
        self.assertTrue(prelude, "fixture is expected to define a non-empty prelude")

        panes = layout.tabs[0].panes
        self.assertEqual(panes[0].cmd, f"{prelude} && echo first")
        self.assertEqual(panes[1].cmd, f"{prelude} && echo second")


class TestShellWrap(unittest.TestCase):
    """`_shell_wrap` selects the host shell invocation per platform/$SHELL.

    Each branch is made deterministic by patching the names as referenced
    inside the module: `claude_panes.sys.platform` and `claude_panes.os.environ`.
    """

    def test_windows_uses_cmd_exe(self) -> None:
        """On win32, wrap with ['cmd.exe', '/c', cmd] regardless of $SHELL."""
        with mock.patch.object(claude_panes.sys, "platform", "win32"):
            # $SHELL must be irrelevant on Windows; set one to prove it.
            with mock.patch.dict(claude_panes.os.environ, {"SHELL": "/usr/bin/zsh"}):
                self.assertEqual(
                    claude_panes._shell_wrap("X"), ["cmd.exe", "/c", "X"]
                )

    def test_posix_with_shell_set_uses_login_shell(self) -> None:
        """On POSIX with $SHELL set, wrap with [$SHELL, '-lc', cmd]."""
        with mock.patch.object(claude_panes.sys, "platform", "linux"):
            with mock.patch.dict(
                claude_panes.os.environ, {"SHELL": "/usr/bin/zsh"}
            ):
                self.assertEqual(
                    claude_panes._shell_wrap("X"), ["/usr/bin/zsh", "-lc", "X"]
                )

    def test_posix_without_shell_falls_back_to_bin_sh(self) -> None:
        """On POSIX with $SHELL unset, fall back to ['/bin/sh', '-c', cmd]."""
        with mock.patch.object(claude_panes.sys, "platform", "linux"):
            # clear=True drops $SHELL (and everything else) from the env.
            with mock.patch.dict(claude_panes.os.environ, {}, clear=True):
                self.assertNotIn("SHELL", os.environ)
                self.assertEqual(
                    claude_panes._shell_wrap("X"), ["/bin/sh", "-c", "X"]
                )


if __name__ == "__main__":
    unittest.main()
