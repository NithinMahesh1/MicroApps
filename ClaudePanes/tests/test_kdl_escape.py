from __future__ import annotations

import unittest

import claude_panes


class TestKdlEscape(unittest.TestCase):
    """_kdl_escape must neutralize every character that could terminate or
    inject into a KDL double-quoted string. Guards the Zellij layout writer
    against node-injection via a pane cmd / tab title (docs/security.md s4)."""

    def test_plain_string_unchanged(self) -> None:
        self.assertEqual(claude_panes._kdl_escape("claude --resume"), "claude --resume")

    def test_backslash_is_doubled(self) -> None:
        self.assertEqual(claude_panes._kdl_escape("\\"), "\\\\")

    def test_double_quote_is_escaped(self) -> None:
        self.assertEqual(claude_panes._kdl_escape('"'), '\\"')

    def test_backslash_escaped_before_quote(self) -> None:
        # Order matters: the backslash must be doubled first, otherwise the
        # backslash introduced for the quote would itself be doubled.
        self.assertEqual(claude_panes._kdl_escape('a\\b"c'), 'a\\\\b\\"c')

    def test_control_characters_escaped(self) -> None:
        self.assertEqual(claude_panes._kdl_escape("\n"), "\\n")
        self.assertEqual(claude_panes._kdl_escape("\r"), "\\r")
        self.assertEqual(claude_panes._kdl_escape("\t"), "\\t")

    def test_quote_smuggling_is_neutralized(self) -> None:
        # A payload trying to close the string early and inject a sibling KDL
        # node must come back with every quote backslash-escaped, so the KDL
        # string never terminates prematurely.
        payload = 'x" command="evil'
        escaped = claude_panes._kdl_escape(payload)
        self.assertEqual(escaped, 'x\\" command=\\"evil')
        # No bare (unescaped) double quote survives.
        for i, ch in enumerate(escaped):
            if ch == '"':
                self.assertEqual(escaped[i - 1], "\\", "found an unescaped quote")

    def test_newline_cannot_start_a_new_line(self) -> None:
        # A literal newline in a cmd stays on one logical KDL line after escaping.
        self.assertNotIn("\n", claude_panes._kdl_escape("a\nb"))


if __name__ == "__main__":
    unittest.main()
