"""
tokenizer.py — Count tokens for each Component using the Anthropic count_tokens endpoint.

count_tokens is FREE: it does not run inference and does not consume the user's
rolling 4-hour generation allowance. This module never calls `claude -p`.

Public API
----------
tokenize(components, *, config_dir, model) -> tuple[list[Component], str]
    Returns new Component instances (immutable — never mutates) with token fields
    filled, plus the tokenizer mode string ("count_tokens" or "claude-p-fallback").
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import anthropic

from claudebench.models import Component


# ---------------------------------------------------------------------------
# YAML frontmatter helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)^---[ \t]*\r?\n", re.DOTALL | re.MULTILINE)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block, body) from a markdown file.

    frontmatter_block is the raw text between the two ``---`` delimiters
    (not including the delimiters themselves).  body is everything after the
    closing delimiter.  If no valid frontmatter is found, returns ("", text).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return "", text
    frontmatter_block = m.group(1)
    body = text[m.end():]
    return frontmatter_block, body


def _extract_frontmatter_summary(frontmatter_block: str) -> str:
    """Return the name + description lines from a frontmatter block.

    Scans for ``name:`` and ``description:`` keys (any order) and returns
    them concatenated.  Falls back to the full block if neither is found.
    """
    name_line = ""
    desc_line = ""
    for line in frontmatter_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:") and not name_line:
            name_line = stripped
        elif stripped.startswith("description:") and not desc_line:
            desc_line = stripped
    if name_line or desc_line:
        return "\n".join(filter(None, [name_line, desc_line]))
    # Fallback: entire frontmatter block so we never return empty string
    return frontmatter_block


# ---------------------------------------------------------------------------
# Anthropic client helpers
# ---------------------------------------------------------------------------

def _make_client() -> anthropic.Anthropic:
    """Construct an Anthropic client using ambient credentials.

    Relies on SDK credential resolution: ANTHROPIC_API_KEY env var, or the
    `ant` / Claude Code login session.  Raises anthropic.AuthenticationError
    (or similar) if no credential is available — callers catch this.
    """
    return anthropic.Anthropic()


def _count_text(client: anthropic.Anthropic, model: str, text: str) -> int:
    """Call count_tokens for ``text`` and return the raw input_tokens value."""
    result = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return result.input_tokens


def _measure_overhead(client: anthropic.Anthropic, model: str) -> int:
    """Measure per-call wrapper overhead by counting a single-space message.

    The Anthropic count_tokens API adds a fixed number of tokens for the
    message envelope (role tags, formatting).  We probe it once with a
    minimal payload so per-component counts can exclude this scaffolding.
    """
    return _count_text(client, model, " ")


# ---------------------------------------------------------------------------
# Per-kind tokenization logic
# ---------------------------------------------------------------------------

def _read_file(config_dir: Path, component: Component) -> str | None:
    """Read a component's file as UTF-8 text.  Returns None on any read error."""
    path = config_dir / component.path
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _net(raw: int, overhead: int) -> int:
    """Subtract per-call overhead and floor at zero."""
    return max(0, raw - overhead)


def _tokenize_skill(
    client: anthropic.Anthropic,
    model: str,
    overhead: int,
    text: str,
) -> tuple[int, int | None]:
    """Return (tokens_always_loaded, tokens_invocation) for a skill component.

    always_loaded = name + description from frontmatter (what the skill list
    injects unconditionally).
    invocation = the body after the frontmatter (what is loaded when triggered).
    """
    frontmatter_block, body = _split_frontmatter(text)

    if frontmatter_block:
        summary = _extract_frontmatter_summary(frontmatter_block)
    else:
        # No frontmatter — treat the whole file as always-loaded; invocation = 0
        summary = text

    always_raw = _count_text(client, model, summary) if summary.strip() else overhead
    always_loaded = _net(always_raw, overhead)

    if frontmatter_block and body.strip():
        invocation_raw = _count_text(client, model, body)
        tokens_invocation: int | None = _net(invocation_raw, overhead)
    else:
        tokens_invocation = None

    return always_loaded, tokens_invocation


def _tokenize_full_file(
    client: anthropic.Anthropic,
    model: str,
    overhead: int,
    text: str,
) -> tuple[int, None]:
    """Count the full file as always-loaded; invocation is null.

    Used for agent, memory, rule, and setting components.
    """
    raw = _count_text(client, model, text)
    return _net(raw, overhead), None


def _tokenize_component(
    client: anthropic.Anthropic,
    model: str,
    overhead: int,
    component: Component,
    config_dir: Path,
) -> Component:
    """Return a new Component with token fields filled.

    Never mutates the input Component.
    """
    text = _read_file(config_dir, component)

    if component.kind == "mcp":
        # Best-effort: if no local schema file or unreadable, leave at zero
        if text is None or not text.strip():
            return component
        raw = _count_text(client, model, text)
        always_loaded = _net(raw, overhead)
        return component.__class__(
            kind=component.kind,
            id=component.id,
            name=component.name,
            path=component.path,
            content_hash=component.content_hash,
            tokens_always_loaded=always_loaded,
            tokens_invocation=None,
            empirical=component.empirical,
        )

    if text is None:
        # Unreadable file — leave token fields at their current values (zero)
        return component

    if component.kind == "skill":
        always_loaded, tokens_invocation = _tokenize_skill(client, model, overhead, text)
    else:
        # agent, memory, rule, setting — full file always loaded
        always_loaded, tokens_invocation = _tokenize_full_file(client, model, overhead, text)

    # dataclasses.replace enforces immutability
    from dataclasses import replace
    return replace(
        component,
        tokens_always_loaded=always_loaded,
        tokens_invocation=tokens_invocation,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tokenize(
    components: Sequence[Component],
    *,
    config_dir: Path,
    model: str,
) -> tuple[list[Component], str]:
    """Tokenize each Component using count_tokens and return filled copies.

    Parameters
    ----------
    components:
        Metadata-filled Component list from scanner.scan(); token fields are 0/None.
    config_dir:
        Absolute path to the config directory (used to resolve component.path).
    model:
        Anthropic model identifier (e.g. "claude-opus-4-8").

    Returns
    -------
    (filled_components, mode)
        filled_components — new Component instances with token fields set.
        mode — "count_tokens" on success, "claude-p-fallback" when no API
        credential is available (token fields remain 0 in that case).
    """
    try:
        client = _make_client()
        overhead = _measure_overhead(client, model)
    except (
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
    ) as exc:
        # No usable API credential — return components unchanged (tokens = 0)
        _ = exc  # referenced to satisfy linters; message surfaced by caller
        return list(components), "claude-p-fallback"
    except Exception as exc:
        # Any other initialisation failure (network, config) — treat as no-creds
        _ = exc
        return list(components), "claude-p-fallback"

    filled: list[Component] = []
    for component in components:
        try:
            filled_component = _tokenize_component(client, model, overhead, component, config_dir)
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
        ):
            # Credential revoked mid-run — return what we have so far (zeros for rest)
            remaining = list(components[len(filled):])
            return filled + remaining, "claude-p-fallback"
        except Exception:
            # Per-component failure (bad file encoding, transient error) — leave at zero
            filled_component = component
        filled.append(filled_component)

    return filled, "count_tokens"
