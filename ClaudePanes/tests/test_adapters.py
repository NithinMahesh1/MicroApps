"""Unit tests for the four ClaudePanes terminal adapters.

These tests verify command CONSTRUCTION, not subprocess execution. The actual
launching of host terminals is exercised by --dry-run integration tests
(out of scope here). Adapter classes covered:

- WindowsTerminalAdapter (wt.exe)
- WezTermAdapter (wezterm cli)
- TmuxAdapter
- ZellijAdapter

See docs/terminal-adapters.md for the canonical CLI shape per adapter and
docs/architecture.md for the Adapter Protocol.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import claude_panes


def make_layout(
    panes: list[tuple[str, str | None]],
    *,
    name: str = "test",
    tab_title: str | None = None,
    pane_titles: list[str | None] | None = None,
) -> claude_panes.Layout:
    """Build a single-tab Layout from a list of (cmd, split) tuples.

    Adjust the keyword arguments to match the actual dataclass signatures
    in claude_panes.py. The first pane's split is conventionally ignored.
    """
    titles = pane_titles if pane_titles is not None else [None] * len(panes)
    pane_objs = [
        claude_panes.Pane(cmd=cmd, split=split, title=title)
        for (cmd, split), title in zip(panes, titles)
    ]
    tab = claude_panes.Tab(title=tab_title, panes=tuple(pane_objs))
    return claude_panes.Layout(
        name=name,
        terminal=None,
        working_dir=None,
        shell_prelude="",
        tabs=(tab,),
    )


def make_multi_tab_layout(
    tabs: list[tuple[str | None, list[tuple[str, str | None]]]],
    *,
    name: str = "test",
) -> claude_panes.Layout:
    """Build a multi-tab Layout from a list of (title, panes) tuples."""
    tab_objs = []
    for title, panes in tabs:
        pane_objs = [
            claude_panes.Pane(cmd=cmd, split=split, title=None)
            for cmd, split in panes
        ]
        tab_objs.append(claude_panes.Tab(title=title, panes=tuple(pane_objs)))
    return claude_panes.Layout(
        name=name,
        terminal=None,
        working_dir=None,
        shell_prelude="",
        tabs=tuple(tab_objs),
    )


class TestWindowsTerminalAdapter(unittest.TestCase):
    """Construction tests for the wt.exe adapter."""

    def setUp(self) -> None:
        self.adapter = claude_panes.WindowsTerminalAdapter()

    def test_single_pane_single_tab(self) -> None:
        """One pane produces an argv that starts with wt new-tab and contains the cmd."""
        layout = make_layout([("echo hello", None)])
        argv = self.adapter.build_command(layout)
        joined = " ".join(argv)
        self.assertIn("wt", joined)
        self.assertIn("new-tab", argv)
        new_tab_idx = argv.index("new-tab")
        self.assertGreater(argv.index("wt.exe"), -1)
        self.assertLess(argv.index("wt.exe"), new_tab_idx)
        self.assertIn("echo hello", joined)

    def test_two_panes_vertical_split(self) -> None:
        """A vertical split emits split-pane with -V and the second pane's cmd."""
        layout = make_layout(
            [("echo left", None), ("echo right", "vertical")]
        )
        argv = self.adapter.build_command(layout)
        self.assertIn("split-pane", argv)
        self.assertIn("-V", argv)
        self.assertIn(";", argv)
        joined = " ".join(argv)
        self.assertIn("echo right", joined)

    def test_two_panes_horizontal_split(self) -> None:
        """A horizontal split emits -H rather than -V."""
        layout = make_layout(
            [("echo top", None), ("echo bottom", "horizontal")]
        )
        argv = self.adapter.build_command(layout)
        self.assertIn("split-pane", argv)
        self.assertIn("-H", argv)
        self.assertNotIn("-V", argv)

    def test_multi_tab(self) -> None:
        """Multi-tab layouts emit multiple new-tab directives."""
        layout = make_multi_tab_layout(
            [
                ("Tab A", [("echo a", None)]),
                ("Tab B", [("echo b", None)]),
            ]
        )
        argv = self.adapter.build_command(layout)
        new_tab_count = sum(1 for elem in argv if elem == "new-tab")
        self.assertGreaterEqual(new_tab_count, 2)
        joined = " ".join(argv)
        self.assertIn("echo a", joined)
        self.assertIn("echo b", joined)

    def test_title_passed(self) -> None:
        """A pane with a title produces --title <title> in the argv."""
        layout = make_layout(
            [("echo hello", None)],
            tab_title="My Tab",
            pane_titles=["Claude"],
        )
        argv = self.adapter.build_command(layout)
        self.assertIn("--title", argv)
        title_idx = argv.index("--title")
        self.assertIn(argv[title_idx + 1], ("My Tab", "Claude"))

    def test_dry_run(self) -> None:
        """execute(dry_run=True) prints to stdout, returns 0, raises nothing."""
        layout = make_layout([("echo hello", None)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.adapter.execute(layout, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertGreater(len(buf.getvalue().strip()), 0)


class TestWezTermAdapter(unittest.TestCase):
    """Construction tests for the wezterm cli adapter.

    WezTerm needs sequential, stateful subprocess calls (pane IDs thread
    from one call into the next), so the adapter may not expose a single
    flat build_command. Tests poke at the emitted command sequence
    via dry-run output where necessary.
    """

    def setUp(self) -> None:
        self.adapter = claude_panes.WezTermAdapter()

    def _capture_dry_run(self, layout: claude_panes.Layout) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.adapter.execute(layout, dry_run=True)
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_first_step_is_spawn(self) -> None:
        """The first emitted command spawns a new WezTerm window."""
        layout = make_layout([("claude", None)])
        output = self._capture_dry_run(layout)
        lines = output.strip().splitlines()
        argv_lines = [ln for ln in lines if not ln.lstrip().startswith("[")]
        first_line = argv_lines[0]
        self.assertIn("wezterm", first_line)
        self.assertIn("cli", first_line)
        self.assertIn("spawn", first_line)
        self.assertIn("--new-window", first_line)
        self.assertIn("claude", first_line)

    def test_split_steps_use_split_pane(self) -> None:
        """Each subsequent pane emits a wezterm cli split-pane invocation."""
        layout = make_layout(
            [("claude", None), ("npm run dev", "vertical")]
        )
        output = self._capture_dry_run(layout)
        lines = output.strip().splitlines()
        argv_lines = [ln for ln in lines if not ln.lstrip().startswith("[")]
        self.assertGreaterEqual(len(argv_lines), 2)
        second_line = argv_lines[1]
        self.assertIn("wezterm", second_line)
        self.assertIn("split-pane", second_line)
        self.assertIn("--pane-id", second_line)
        self.assertIn("npm", second_line)

    def test_orientation_mapping(self) -> None:
        """split='vertical' maps to --right; split='horizontal' maps to --bottom."""
        vertical = make_layout(
            [("a", None), ("b", "vertical")]
        )
        horizontal = make_layout(
            [("a", None), ("b", "horizontal")]
        )

        vert_out = self._capture_dry_run(vertical)
        horiz_out = self._capture_dry_run(horizontal)

        self.assertIn("--right", vert_out)
        self.assertNotIn("--bottom", vert_out)

        self.assertIn("--bottom", horiz_out)
        self.assertNotIn("--right", horiz_out)

    def test_dry_run_prints_all_steps(self) -> None:
        """Dry-run prints one line per planned subprocess and returns 0."""
        layout = make_layout(
            [
                ("claude", None),
                ("git status", "vertical"),
                ("npm run dev", "horizontal"),
            ]
        )
        output = self._capture_dry_run(layout)
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        argv_lines = [ln for ln in lines if not ln.lstrip().startswith("[")]
        self.assertEqual(len(argv_lines), 3)


class TestTmuxAdapter(unittest.TestCase):
    """Construction tests for the tmux adapter."""

    def setUp(self) -> None:
        self.adapter = claude_panes.TmuxAdapter()

    def test_new_session_first(self) -> None:
        """argv starts with tmux new-session."""
        layout = make_layout([("claude", None)], name="claudepanes")
        argv = self.adapter.build_command(layout)
        self.assertEqual(argv[0], "tmux")
        self.assertEqual(argv[1], "new-session")

    def test_split_window_v_and_h(self) -> None:
        """tmux uses -h for vertical (side-by-side) and -v for horizontal (stacked)."""
        vertical = make_layout(
            [("a", None), ("b", "vertical")], name="v"
        )
        horizontal = make_layout(
            [("a", None), ("b", "horizontal")], name="h"
        )

        vert_argv = self.adapter.build_command(vertical)
        horiz_argv = self.adapter.build_command(horizontal)

        self.assertIn("split-window", vert_argv)
        self.assertIn("-h", vert_argv)

        self.assertIn("split-window", horiz_argv)
        self.assertIn("-v", horiz_argv)

    def test_session_name_from_layout(self) -> None:
        """Session name derives from layout.name with a millisecond suffix to
        avoid collisions on re-runs (docs/terminal-adapters.md s3)."""
        layout = make_layout([("claude", None)], name="my-session")
        argv = self.adapter.build_command(layout)
        self.assertIn("-s", argv)
        s_idx = argv.index("-s")
        session_name = argv[s_idx + 1]
        self.assertTrue(
            session_name.startswith("my-session"),
            f"expected session name to start with 'my-session', got {session_name!r}",
        )
        # Suffix is a numeric collision-avoidance marker, not just the name.
        self.assertNotEqual(session_name, "my-session")

    def test_attaches_at_end(self) -> None:
        """argv ends with an attach directive (attach or attach-session)."""
        layout = make_layout([("claude", None)], name="my-session")
        argv = self.adapter.build_command(layout)
        attach_tokens = {"attach", "attach-session"}
        self.assertTrue(
            any(token in argv for token in attach_tokens),
            f"expected one of {attach_tokens} in argv, got {argv}",
        )
        last_attach_idx = max(
            argv.index(token) for token in attach_tokens if token in argv
        )
        non_target_args_after = [
            elem for elem in argv[last_attach_idx + 1 :] if elem == ";"
        ]
        self.assertEqual(
            non_target_args_after,
            [],
            f"attach directive should be the final tmux sub-command, got {argv}",
        )

    def test_dry_run(self) -> None:
        """execute(dry_run=True) prints, returns 0, no subprocess invoked."""
        layout = make_layout([("claude", None)])
        buf = io.StringIO()
        with mock.patch("subprocess.run") as fake_run:
            with redirect_stdout(buf):
                rc = self.adapter.execute(layout, dry_run=True)
        self.assertEqual(rc, 0)
        fake_run.assert_not_called()
        self.assertGreater(len(buf.getvalue().strip()), 0)


class TestZellijAdapter(unittest.TestCase):
    """Construction tests for the Zellij adapter.

    Zellij writes a temporary KDL file and invokes `zellij --layout <file>`.
    We test the KDL content via dry-run output (which should surface the
    generated KDL) and the final argv shape.
    """

    def setUp(self) -> None:
        self.adapter = claude_panes.ZellijAdapter()

    def _capture_dry_run(self, layout: claude_panes.Layout) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.adapter.execute(layout, dry_run=True)
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def _get_kdl_content(self, layout: claude_panes.Layout) -> str:
        """Get the generated KDL content, preferring a direct accessor if available."""
        if hasattr(self.adapter, "build_kdl"):
            return self.adapter.build_kdl(layout)
        return self._capture_dry_run(layout)

    def test_kdl_file_generated(self) -> None:
        """The adapter produces KDL content (via direct method or dry-run output)."""
        layout = make_layout([("claude", None)])
        kdl = self._get_kdl_content(layout)
        self.assertIn("layout", kdl)
        self.assertGreater(len(kdl.strip()), 0)

    def test_kdl_has_tab_and_pane(self) -> None:
        """Generated KDL contains tab and pane blocks."""
        layout = make_layout(
            [("claude", None), ("npm run dev", "vertical")],
            tab_title="dev",
        )
        kdl = self._get_kdl_content(layout)
        self.assertIn("tab", kdl)
        self.assertIn("pane", kdl)

    def test_kdl_includes_command(self) -> None:
        """KDL wraps the user's cmd through the host shell (cmd.exe /c on
        Windows, bash -lc on POSIX) so that shell metacharacters survive
        verbatim. The whole user cmd appears as a single quoted args entry
        (docs/security.md s4)."""
        layout = make_layout([("npm run dev", None)])
        kdl = self._get_kdl_content(layout)
        # Host shell is the KDL command; the user's cmd rides inside args.
        self.assertTrue(
            'command="cmd.exe"' in kdl or 'command="bash"' in kdl,
            f"expected host shell as command=, got: {kdl}",
        )
        self.assertIn("args", kdl)
        self.assertIn('"npm run dev"', kdl)

    def test_argv_starts_with_zellij_layout(self) -> None:
        """The final invocation is ['zellij', '--layout', <path>]."""
        layout = make_layout([("claude", None)])
        argv = self.adapter.build_command(layout)
        self.assertEqual(argv[0], "zellij")
        self.assertEqual(argv[1], "--layout")
        self.assertEqual(len(argv), 3)
        self.assertTrue(
            argv[2].endswith(".kdl"),
            f"expected a .kdl path as third argv element, got {argv[2]!r}",
        )


class TestAdapterProtocol(unittest.TestCase):
    """Cross-cutting tests over all four adapters."""

    ADAPTER_CLASSES = (
        ("wt", "WindowsTerminalAdapter"),
        ("wezterm", "WezTermAdapter"),
        ("tmux", "TmuxAdapter"),
        ("zellij", "ZellijAdapter"),
    )

    def _instantiate_all(self) -> list[tuple[str, object]]:
        return [
            (expected_name, getattr(claude_panes, cls_name)())
            for expected_name, cls_name in self.ADAPTER_CLASSES
        ]

    def test_all_adapters_have_name(self) -> None:
        """Each adapter exposes a string 'name' attribute with the expected value."""
        for expected_name, adapter in self._instantiate_all():
            with self.subTest(adapter=type(adapter).__name__):
                self.assertTrue(hasattr(adapter, "name"))
                self.assertIsInstance(adapter.name, str)
                self.assertEqual(adapter.name, expected_name)

    def test_all_adapters_have_is_available(self) -> None:
        """Each adapter exposes an is_available() that returns a bool."""
        for _expected_name, adapter in self._instantiate_all():
            with self.subTest(adapter=type(adapter).__name__):
                self.assertTrue(callable(getattr(adapter, "is_available", None)))
                result = adapter.is_available()
                self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main()
