"""
memory.py — index Claude Code auto-memories for the MEMORIES tab.

Claude Code stores per-project "memories" as Markdown files under
``~/.claude/projects/<encoded-cwd>/memory/<name>.md``. Each memory carries a small
YAML-ish frontmatter block (``name``, ``description``, and a ``type`` that is either
top-level *or* nested under a ``metadata:`` key) followed by the memory body.
``MEMORY.md`` in the same folder is the human-readable index (one bullet per memory),
not a memory itself, so it is skipped.

This module:
  * ``index_memories()`` — scan every project's ``memory/*.md`` into ``Memory`` records.
  * ``Memory``           — a frozen record carrying display fields PLUS the *exact*
                           precomputed ``*_lc`` / ``last_date`` / ``session_id`` fields
                           the UI-agnostic :mod:`ccdashboard.search` engine already
                           reads. Exposing the same field contract lets the MEMORIES
                           tab reuse ``search.parse_query`` / ``rank`` /
                           ``highlight_title`` **unchanged** — no edits to the engine
                           that powers the CONVERSATIONS tab.
  * ``preview()``        — a memory-specific reading-pane renderable (header +
                           description + full body with matched terms highlighted),
                           because memories are short-form and meant to be read whole
                           rather than snippet-windowed like a transcript.
  * ``split_type_operator()`` — pull an inline ``type:feedback`` token out of the
                           search text so the shared parser never sees it (keeping the
                           memory-only Type facet out of the shared engine).

Like ``conversations`` / ``search`` this module is UI-agnostic: it depends only on the
standard library and ``rich.text``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from rich.text import Text

# Caps: memories are tiny, but a stray non-memory file (e.g. a progress log that lives
# in the same folder) could be large, so bound the searchable text and the rendered body.
_MAX_BODY_CHARS = 100_000
_PREVIEW_BODY_CHARS = 4_000

# Highlight / styling — the same cyan accent the search preview uses, kept local so this
# module never reaches into ``search``'s private style constants.
_STYLE_MATCH = "bold #00e5ff"
_STYLE_HEADER = "bold #00e5ff"
_STYLE_DIM = "#5a7a88"
_STYLE_DESC = "italic #9fd9e8"

# Frontmatter is fenced by a leading '---' line and a closing '---' line.
_FENCE = "---"
# A "key: value" line; the key is captured so we can tell ``type:`` from ``node_type:``
# (only an exact ``type`` key is the memory type; ``node_type`` is metadata noise).
_KV_RE = re.compile(r"^(\s*)([A-Za-z0-9_]+):\s*(.*)$")
# Inline ``type:foo`` operator in the search box, anchored at a token boundary.
_TYPE_OP_RE = re.compile(r"(?<!\S)type:(\S+)", re.IGNORECASE)

_FRONTMATTER_KEYS = ("name", "description", "type")
_UNTYPED = "untyped"


@dataclass(frozen=True)
class Memory:
    """One Claude Code auto-memory (a frontmatter ``.md`` under a project's memory dir).

    The first block is human/display data; the second block is the precomputed search
    contract read verbatim by :mod:`ccdashboard.search` (mirroring ``Conversation``),
    so the MEMORIES tab ranks/highlights through the same engine as CONVERSATIONS.
    """

    name: str
    description: str
    type: str
    body: str
    project_name: str          # recognizable home-relative label, e.g. "MyGit-MicroApps"
    project_slug: str          # raw encoded dir name, e.g. "C--Users-…-MicroApps"
    file_path: str
    modified: str              # display string "YYYY-MM-DD HH:MM"

    # --- search-engine contract (read by ccdashboard.search; mirrors Conversation) ---
    title: str = ""            # == name (the title-weighted field in the ranker)
    title_lc: str = ""
    body_lc: str = ""          # description + body, lowercased (both are searchable)
    project_lc: str = ""       # project_name.lower() (so project: filters/matches work)
    branch_lc: str = ""        # memories have no branch; empty contributes nothing
    last_at: str = ""          # mtime ISO string (newest-first browse + recency blend)
    last_date: date | None = None
    session_id: str = ""       # stable unique id for the ranker's deterministic tiebreak


def _strip_quotes(value: str) -> str:
    """Drop a single matching pair of surrounding quotes from a frontmatter value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split ``text`` into (frontmatter fields, body).

    Handles the two shapes seen in real memories: a top-level ``type:`` and a ``type:``
    nested under a ``metadata:`` block (the key match ignores indentation, so both are
    found, while ``node_type:`` is left alone). Only the block fenced by the leading
    ``---`` / closing ``---`` is parsed. A file with no (or unterminated) frontmatter
    yields ``({}, full-text)`` so untyped notes still surface.
    """
    lines = text.splitlines()

    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != _FENCE:
        return {}, text

    start = idx + 1
    end: int | None = None
    for j in range(start, len(lines)):
        if lines[j].strip() == _FENCE:
            end = j
            break
    if end is None:
        return {}, text

    fields: dict[str, str] = {}
    for line in lines[start:end]:
        match = _KV_RE.match(line)
        if not match:
            continue
        key = match.group(2).lower()
        value = _strip_quotes(match.group(3).strip())
        # First occurrence of each wanted key wins; empty values are ignored.
        if key in _FRONTMATTER_KEYS and key not in fields and value:
            fields[key] = value
    body = "\n".join(lines[end + 1:]).strip("\n")
    return fields, body


def _encode_home() -> str:
    """The slug form of ``Path.home()`` (path separators / drive colon → ``-``).

    Mirrors how Claude Code encodes a cwd into the project-dir name, derived at runtime
    from the real home dir — nothing machine-specific is hardcoded.
    """
    home = str(Path.home())
    return home.replace(":", "-").replace("\\", "-").replace("/", "-")


def _project_label(slug: str) -> str:
    """A recognizable project label from the encoded ``slug``.

    Claude encodes a cwd by replacing every path separator with ``-``; a literal ``-`` in
    a repo name is then indistinguishable from a separator, so naively taking the last
    segment mangles ``smart-gift-card`` into ``card``. Instead we strip the home-dir
    prefix (derived from ``Path.home()``) and keep the remainder intact — yielding stable,
    readable labels like ``MyGit-smart-gift-card`` that also distinguish same-named repos
    in different parents (e.g. a worktree under ``temp-…``). Falls back to the raw slug
    for a cwd outside home.
    """
    home_slug = _encode_home()
    lowered = slug.lower()
    home_lower = home_slug.lower()
    if lowered.startswith(home_lower + "-"):
        return slug[len(home_slug) + 1:]
    if lowered == home_lower:
        return Path.home().name
    return slug


def _prettify_stem(stem: str) -> str:
    """A readable display name from a filename stem (for notes lacking a ``name:``)."""
    return stem.replace("-", " ").replace("_", " ").strip() or stem


def _first_body_line(body: str) -> str:
    """First non-empty body line (heading markers stripped), for a missing description."""
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:200]
    return ""


def _mtime_fields(path: Path) -> tuple[str, str, date | None]:
    """(iso, display, date) from the file mtime — the memory's "last touched" stamp."""
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return "", "", None
    moment = datetime.fromtimestamp(stamp)
    return (
        moment.isoformat(timespec="seconds"),
        moment.strftime("%Y-%m-%d %H:%M"),
        moment.date(),
    )


def _parse_memory(path: Path) -> Memory | None:
    """Parse one ``memory/*.md`` file into a :class:`Memory` (or None if unreadable)."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    fields, body = _parse_frontmatter(raw)
    body = body[:_MAX_BODY_CHARS]
    slug = path.parent.parent.name  # <encoded-cwd>/memory/<file>.md -> <encoded-cwd>
    project_name = _project_label(slug)

    name = fields.get("name") or _prettify_stem(path.stem)
    description = fields.get("description") or _first_body_line(body)
    mem_type = (fields.get("type") or _UNTYPED).lower()
    last_at, modified, last_date = _mtime_fields(path)

    # Description + body are both searchable; name carries the heavier title weight.
    searchable = f"{description}\n{body}".lower()

    return Memory(
        name=name,
        description=description,
        type=mem_type,
        body=body,
        project_name=project_name,
        project_slug=slug,
        file_path=str(path),
        modified=modified,
        title=name,
        title_lc=name.lower(),
        body_lc=searchable,
        project_lc=project_name.lower(),
        branch_lc="",
        last_at=last_at,
        last_date=last_date,
        session_id=f"{slug}/{path.name}",
    )


def index_memories(projects_dir: Path | None = None) -> list[Memory]:
    """Scan every project's ``memory/*.md`` into Memory records, newest-touched first.

    ``MEMORY.md`` (the index) is skipped. Unreadable files are dropped silently. The
    layout mirrors ``conversations.index_conversations`` (``<projects>/<slug>/memory``).
    """
    root = projects_dir or (Path.home() / ".claude" / "projects")
    if not root.exists():
        return []
    memories: list[Memory] = []
    for path in root.glob("*/memory/*.md"):
        if path.name == "MEMORY.md":
            continue
        mem = _parse_memory(path)
        if mem is not None:
            memories.append(mem)
    memories.sort(key=lambda m: m.last_at, reverse=True)
    return memories


def split_type_operator(text: str) -> tuple[str, str | None]:
    """Extract an inline ``type:foo`` token from ``text``.

    Returns ``(text_without_type_tokens, type_or_None)``. Pulling ``type:`` out before
    the text reaches ``search.parse_query`` keeps the memory-only Type facet entirely
    out of the shared engine (the parser would otherwise treat ``type:foo`` as a literal
    AND term and drop everything). The last ``type:`` token wins.
    """
    found: list[str] = []

    def _capture(match: re.Match[str]) -> str:
        found.append(match.group(1).lower())
        return " "

    cleaned = " ".join(_TYPE_OP_RE.sub(_capture, text).split())
    return cleaned, (found[-1] if found else None)


# --- Reading-pane preview ----------------------------------------------------


def _match_spans(haystack_lc: str, needles: list[str]) -> list[tuple[int, int]]:
    """All (start, end) offsets where any needle occurs in ``haystack_lc`` (sorted)."""
    spans: list[tuple[int, int]] = []
    for needle in needles:
        if not needle:
            continue
        start = haystack_lc.find(needle)
        while start != -1:
            spans.append((start, start + len(needle)))
            start = haystack_lc.find(needle, start + 1)
    spans.sort()
    return spans


def _needles(query) -> list[str]:
    """The flat list of phrases+terms to highlight, or [] for an empty/None query."""
    if query is None or query.is_empty:
        return []
    return [n for n in (*query.phrases, *query.terms) if n]


def _highlight(text: str, needles: list[str], *, style: str = "") -> Text:
    """A rich ``Text`` of ``text`` with each needle span styled in the match accent."""
    if not text:
        return Text("")
    if not needles:
        return Text(text, style=style) if style else Text(text)
    out = Text()
    cursor = 0
    for start, end in _match_spans(text.lower(), needles):
        if start < cursor:
            continue  # overlapping/adjacent match already consumed
        if start > cursor:
            out.append(text[cursor:start], style=style)
        out.append(text[start:end], style=_STYLE_MATCH)
        cursor = end
    if cursor < len(text):
        out.append(text[cursor:], style=style)
    return out


def preview(memory: Memory, query=None) -> Text:
    """Reading-pane renderable: header + description + full body, query matches styled.

    Memories are short, so the whole body is rendered (capped at ``_PREVIEW_BODY_CHARS``)
    rather than snippet-windowed. ``query`` may be ``None`` or empty for a plain read.
    """
    needles = _needles(query)
    header = f"{memory.name}  —  {memory.project_name} · {memory.type} · {memory.modified}"
    result = Text(header, style=_STYLE_HEADER)
    result.append("\n")
    result.append(memory.file_path, style=_STYLE_DIM)

    if memory.description:
        result.append("\n\n")
        result.append(_highlight(memory.description, needles, style=_STYLE_DESC))

    body = memory.body[:_PREVIEW_BODY_CHARS]
    if body:
        result.append("\n\n")
        result.append(_highlight(body, needles))
        if len(memory.body) > _PREVIEW_BODY_CHARS:
            result.append("\n…(truncated)", style=_STYLE_DIM)
    return result


if __name__ == "__main__":  # built-in smoke test (no network, read-only)
    import sys

    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    idx = index_memories()
    print(f"Indexed {len(idx)} memories")
    by_type: dict[str, int] = {}
    for _m in idx:
        by_type[_m.type] = by_type.get(_m.type, 0) + 1
    print("by type:", dict(sorted(by_type.items())))
    print("projects:", sorted({_m.project_name for _m in idx}))
    for _m in idx[:8]:
        print(f"  [{_m.project_name:<28.28}] {_m.type:<9.9} {_m.name[:42]}")
