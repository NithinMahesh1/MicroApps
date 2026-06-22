"""
scan.py — build the view-model dict that the CCDashboard HTML frontend consumes.

Public API
----------
build_view_model(config_dir: Path) -> dict
    Scan config_dir (typically ~/.claude/) via ClaudeBench's scanner, merge
    token data from the newest ClaudeBench snapshot, and return a dict
    matching the CONTRACT shape exactly.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# ClaudeBench import — resolved at call-time so the function stays testable
# even when the sibling package is not on sys.path yet.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLAUDEBENCH_ROOT = _REPO_ROOT / "ClaudeBench"

_ALL_KINDS: tuple[str, ...] = ("skill", "agent", "memory", "rule", "setting", "mcp")

# Files that must never be previewed (contain secrets).
_SECRET_NAME_PATTERNS: frozenset[str] = frozenset({"token.json", ".credentials.json"})
_SECRET_GLOB_PATTERNS: tuple[str, ...] = ("credentials*", "*secret*")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_secret_file(path: Path) -> bool:
    """Return True when the file's name matches a known secret pattern."""
    name = path.name.lower()
    if path.name in _SECRET_NAME_PATTERNS:
        return True
    for pat in _SECRET_GLOB_PATTERNS:
        if path.match(pat):
            return True
    return False


def _read_text_tolerant(path: Path) -> str:
    """Read a file as UTF-8 text; fall back to latin-1; return '' on error."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1")
        except OSError:
            return ""
    except OSError:
        return ""


def _collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace (including newlines) to single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def _first_non_empty_line(text: str) -> str:
    """Return the first non-blank line from text, stripped."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_frontmatter_field(text: str, field: str) -> str | None:
    """Return the value of a YAML frontmatter field, or None if absent."""
    fm_match = re.match(
        r"^---[ \t]*\r?\n(.*?)^---[ \t]*\r?\n", text, re.DOTALL | re.MULTILINE
    )
    if not fm_match:
        return None
    fm_block = fm_match.group(1)
    field_match = re.search(
        rf"^{re.escape(field)}\s*:\s*(.+)$", fm_block, re.MULTILINE
    )
    if not field_match:
        return None
    return field_match.group(1).strip().strip("\"'")


def _body_after_frontmatter(text: str) -> str:
    """Return the text after the closing '---' of YAML frontmatter, or all text."""
    fm_match = re.match(
        r"^---[ \t]*\r?\n.*?^---[ \t]*\r?\n", text, re.DOTALL | re.MULTILINE
    )
    if fm_match:
        return text[fm_match.end():]
    return text


def _description_for_skill_or_agent(text: str) -> str:
    """Extract a description from a skill or agent markdown file.

    Prefers the YAML frontmatter ``description:`` field.  Falls back to the
    first non-empty line of the body text (after stripping the frontmatter).
    """
    from_frontmatter = _extract_frontmatter_field(text, "description")
    if from_frontmatter:
        return from_frontmatter
    body = _body_after_frontmatter(text)
    return _first_non_empty_line(body)


def _description_for_other(text: str) -> str:
    """Return the first non-empty line of the file as a description."""
    return _first_non_empty_line(text)


def _make_preview(text: str, max_chars: int = 400) -> str:
    """Return a collapsed, truncated preview of text (no secrets)."""
    collapsed = _collapse_whitespace(text)
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[:max_chars]


def _stat_fields(abs_path: Path) -> tuple[int, str]:
    """Return (size_bytes, modified_iso8601_utc) or (0, '') on error."""
    try:
        st = os.stat(abs_path)
        size = st.st_size
        modified_dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        modified = modified_dt.isoformat(timespec="seconds")
        return size, modified
    except OSError:
        return 0, ""


# ---------------------------------------------------------------------------
# Snapshot loading
# ---------------------------------------------------------------------------


def _load_newest_snapshot(claudebench_root: Path) -> dict[str, Any] | None:
    """Load the most recently written snapshot from ClaudeBench/snapshots/*.json.

    Returns the parsed dict, or None when no snapshots exist or parsing fails.
    Only returns data when ``tokenizer == "count_tokens"``; otherwise None.
    """
    snapshots_dir = claudebench_root / "snapshots"
    if not snapshots_dir.is_dir():
        return None

    json_files = sorted(snapshots_dir.glob("*.json"))
    if not json_files:
        return None

    # Newest by file modification time.
    newest = max(json_files, key=lambda p: p.stat().st_mtime)
    try:
        data = json.loads(newest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    if data.get("tokenizer") != "count_tokens":
        return None

    return data


def _build_token_map(
    snapshot: dict[str, Any],
) -> dict[tuple[str, str], tuple[int | None, int | None]]:
    """Build a (kind, id) -> (tokens_always_loaded, tokens_invocation) map."""
    token_map: dict[tuple[str, str], tuple[int | None, int | None]] = {}
    for comp in snapshot.get("components", []):
        if not isinstance(comp, dict):
            continue
        kind = comp.get("kind", "")
        comp_id = comp.get("id", "")
        if not kind or not comp_id:
            continue
        always: int | None = comp.get("tokens_always_loaded")
        invocation: int | None = comp.get("tokens_invocation")
        token_map[(kind, comp_id)] = (always, invocation)
    return token_map


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_view_model(config_dir: Path) -> dict[str, Any]:
    """Scan config_dir and return the CCDashboard view-model dict.

    Parameters
    ----------
    config_dir:
        Absolute path to a Claude config directory (typically ``~/.claude``).

    Returns
    -------
    dict
        Exactly the shape defined in the CCDashboard CONTRACT.  Always returns
        a valid dict; individual bad files are skipped silently.
    """
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ------------------------------------------------------------------ #
    # 1. Import ClaudeBench scanner                                        #
    # ------------------------------------------------------------------ #
    components: list[Any] = []
    if str(_CLAUDEBENCH_ROOT) not in sys.path:
        sys.path.insert(0, str(_CLAUDEBENCH_ROOT))

    try:
        from claudebench import scanner  # type: ignore[import]
        components = scanner.scan(config_dir)
    except (ImportError, Exception):
        # ClaudeBench unavailable or scan failed — return an empty but valid model.
        pass

    # ------------------------------------------------------------------ #
    # 2. Load newest snapshot for token data                              #
    # ------------------------------------------------------------------ #
    snapshot = _load_newest_snapshot(_CLAUDEBENCH_ROOT)
    token_map = _build_token_map(snapshot) if snapshot is not None else {}
    has_tokens = bool(token_map)

    # ------------------------------------------------------------------ #
    # 3. Build item list                                                   #
    # ------------------------------------------------------------------ #
    items: list[dict[str, Any]] = []

    for comp in components:
        kind: str = comp.kind
        comp_id: str = comp.id
        name: str = comp.name
        rel_posix: str = comp.path  # already a posix-relative string per scanner

        # Absolute path for file operations.
        abs_path = config_dir / Path(rel_posix)

        # -- stat -------------------------------------------------------
        size_bytes, modified = _stat_fields(abs_path)

        # -- secret guard -----------------------------------------------
        is_secret = _is_secret_file(abs_path)

        # -- read content (skipped for secrets) -------------------------
        raw_text = "" if is_secret else _read_text_tolerant(abs_path)

        # -- description ------------------------------------------------
        if kind in ("skill", "agent"):
            description = _description_for_skill_or_agent(raw_text)
        else:
            description = _description_for_other(raw_text)

        # -- preview (max 400 chars; blank for secrets) -----------------
        preview = "" if is_secret else _make_preview(raw_text, max_chars=400)

        # -- tokens from snapshot map -----------------------------------
        tokens_always_loaded: int | None = None
        tokens_invocation: int | None = None
        if has_tokens:
            mapped = token_map.get((kind, comp_id))
            if mapped is not None:
                tokens_always_loaded, tokens_invocation = mapped

        items.append({
            "kind": kind,
            "id": comp_id,
            "name": name,
            "description": description,
            "path": rel_posix,
            "abs_path": str(abs_path),
            "size_bytes": size_bytes,
            "modified": modified,
            "preview": preview,
            "tokens_always_loaded": tokens_always_loaded,
            "tokens_invocation": tokens_invocation,
        })

    # ------------------------------------------------------------------ #
    # 4. Sort items by (kind, id) — scanner already sorts, but we sort   #
    #    again here to guarantee order independent of scanner behaviour.  #
    # ------------------------------------------------------------------ #
    items.sort(key=lambda it: (it["kind"], it["id"]))

    # ------------------------------------------------------------------ #
    # 5. Compute summary                                                   #
    # ------------------------------------------------------------------ #
    by_kind: dict[str, int] = {k: 0 for k in _ALL_KINDS}
    for item in items:
        k = item["kind"]
        if k in by_kind:
            by_kind[k] += 1

    summary: dict[str, Any] = {
        "total": len(items),
        "by_kind": by_kind,
    }

    return {
        "generated_at": generated_at,
        "config_dir": str(config_dir),
        "has_tokens": has_tokens,
        "summary": summary,
        "items": items,
    }
