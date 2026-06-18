"""
report.py — Format ClaudeBench output as aligned console tables or JSON.

Public API
----------
render_list(components) -> str
    Aligned text table: Kind | Id | Always | Invocation

render_snapshot(snap, *, as_json=False) -> str
    Full snapshot report: header + component table + Totals section.
    Pass as_json=True to get the raw JSON representation instead.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from claudebench.models import Component, Snapshot

# Column labels used in both render functions
_COL_KIND = "Kind"
_COL_ID = "Id"
_COL_ALWAYS = "Always"
_COL_INVOCATION = "Invocation"

_ALL_KINDS = ("skill", "agent", "mcp", "memory", "rule", "setting")

_DASH = "—"  # em-dash for None values


# ---------------------------------------------------------------------------
# Internal table helpers
# ---------------------------------------------------------------------------

def _fmt_tokens(value: int | None) -> str:
    """Format a token count, using an em-dash for None."""
    if value is None:
        return _DASH
    return f"{value:,}"


def _build_list_rows(components: Sequence[Component]) -> list[tuple[str, str, str, str]]:
    """Return (kind, id, always, invocation) string tuples for each component."""
    return [
        (
            c.kind,
            c.id,
            _fmt_tokens(c.tokens_always_loaded),
            _fmt_tokens(c.tokens_invocation),
        )
        for c in components
    ]


def _render_table(
    headers: tuple[str, str, str, str],
    rows: list[tuple[str, str, str, str]],
) -> str:
    """Render a fixed-width aligned table with a header separator.

    Columns are left-aligned except the two numeric columns (always, invocation)
    which are right-aligned to make it easy to scan magnitudes.
    """
    if not rows:
        return f"{headers[0]:<12}  {headers[1]:<30}  {headers[2]:>10}  {headers[3]:>12}\n(no components found)"

    # Column widths: at least the header width, stretched to fit widest value
    col0_w = max(len(headers[0]), max(len(r[0]) for r in rows))
    col1_w = max(len(headers[1]), max(len(r[1]) for r in rows))
    col2_w = max(len(headers[2]), max(len(r[2]) for r in rows))
    col3_w = max(len(headers[3]), max(len(r[3]) for r in rows))

    header_line = (
        f"{headers[0]:<{col0_w}}  "
        f"{headers[1]:<{col1_w}}  "
        f"{headers[2]:>{col2_w}}  "
        f"{headers[3]:>{col3_w}}"
    )
    separator = "-" * len(header_line)

    data_lines = [
        f"{r[0]:<{col0_w}}  {r[1]:<{col1_w}}  {r[2]:>{col2_w}}  {r[3]:>{col3_w}}"
        for r in rows
    ]

    return "\n".join([header_line, separator, *data_lines])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_list(components: Sequence[Component]) -> str:
    """Return an aligned text table of all components.

    Columns: Kind | Id | Always | Invocation
    Invocation shows an em-dash for components where that field is None.

    Parameters
    ----------
    components:
        Sequence of Component instances (token fields may be 0 if in fallback mode).

    Returns
    -------
    Formatted multi-line string suitable for printing to stdout.
    """
    headers = (_COL_KIND, _COL_ID, _COL_ALWAYS, _COL_INVOCATION)
    rows = _build_list_rows(components)
    return _render_table(headers, rows)


def render_snapshot(snap: Snapshot, *, as_json: bool = False) -> str:
    """Return a formatted report for a Snapshot.

    Parameters
    ----------
    snap:
        The Snapshot to render.
    as_json:
        If True, return ``json.dumps(snap.to_dict(), indent=2)`` instead of
        the console table.

    Returns
    -------
    Formatted string ready for stdout.
    """
    if as_json:
        return json.dumps(snap.to_dict(), indent=2)

    lines: list[str] = []

    # ------------------------------------------------------------------
    # Header block
    # ------------------------------------------------------------------
    lines.append("ClaudeBench Snapshot")
    lines.append("=" * 60)
    lines.append(f"Taken at  : {snap.taken_at}")
    lines.append(f"Label     : {snap.label or '(none)'}")
    lines.append(f"Config dir: {snap.config_dir}")
    lines.append(f"Model     : {snap.model}")
    lines.append(f"Tokenizer : {snap.tokenizer}")
    lines.append("")

    # ------------------------------------------------------------------
    # Component table — grouped by kind for readability
    # ------------------------------------------------------------------
    lines.append("Components")
    lines.append("-" * 60)

    all_rows: list[tuple[str, str, str, str]] = []
    for kind in _ALL_KINDS:
        kind_components = [c for c in snap.components if c.kind == kind]
        for c in kind_components:
            all_rows.append(
                (
                    c.kind,
                    c.id,
                    _fmt_tokens(c.tokens_always_loaded),
                    _fmt_tokens(c.tokens_invocation),
                )
            )

    headers = (_COL_KIND, _COL_ID, _COL_ALWAYS, _COL_INVOCATION)
    lines.append(_render_table(headers, all_rows))
    lines.append("")

    # ------------------------------------------------------------------
    # Totals section
    # ------------------------------------------------------------------
    lines.append("Totals")
    lines.append("-" * 60)
    lines.append(f"Always loaded : {snap.totals['always_loaded']:,}")
    lines.append(f"Invocation    : {snap.totals['invocation']:,}")
    lines.append("")
    lines.append("By kind (always_loaded):")

    by_kind = snap.totals.get("by_kind", {})
    for kind in _ALL_KINDS:
        count = by_kind.get(kind, 0)
        lines.append(f"  {kind:<10}: {count:,}")

    return "\n".join(lines)
