"""
models.py — frozen dataclasses for ClaudeBench's core data model.

All types are immutable.  Callers that need to set fields on an existing
instance must use ``dataclasses.replace(instance, field=value)``.

Public API
----------
Component       — one config item (kind, id, name, path, content_hash, tokens_*)
Snapshot        — point-in-time record of all Component token counts
build_snapshot  — compute totals and construct a Snapshot from a Component list
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace  # noqa: F401 — re-exported for callers
from typing import Any

# ---------------------------------------------------------------------------
# Valid kind values (used for totals.by_kind key ordering)
# ---------------------------------------------------------------------------

_ALL_KINDS: tuple[str, ...] = ("skill", "agent", "mcp", "memory", "rule", "setting")


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Component:
    """A single discovered config item within ~/.claude/.

    Attributes
    ----------
    kind:
        Category — one of ``skill | agent | mcp | memory | rule | setting``.
    id:
        Stable slug identifier (e.g. ``"commit-message"``).
    name:
        Human-readable display name (e.g. ``"Commit Message"``).
    path:
        POSIX path relative to config_dir (forward slashes).
    content_hash:
        SHA-256 hexdigest of the file's UTF-8 bytes, prefixed ``"sha256:"``.
    tokens_always_loaded:
        Tokens from this component present in context on every invocation.
        Populated by tokenizer; zero before tokenization.
    tokens_invocation:
        Tokens loaded only when the component is actively invoked.
        ``None`` for kinds that are always fully loaded (agent, memory, rule,
        setting, mcp).  Zero-before-tokenization for skills that have a body.
    empirical:
        Live-API bench statistics dict, or ``None`` when bench has not been run.
    """

    kind: str
    id: str
    name: str
    path: str
    content_hash: str
    tokens_always_loaded: int = 0
    tokens_invocation: int | None = None
    empirical: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict matching snapshot.schema.json."""
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "content_hash": self.content_hash,
            "tokens_always_loaded": self.tokens_always_loaded,
            "tokens_invocation": self.tokens_invocation,
            "empirical": self.empirical,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Component":
        """Construct a Component from a deserialized snapshot dict."""
        return Component(
            kind=d["kind"],
            id=d["id"],
            name=d["name"],
            path=d["path"],
            content_hash=d["content_hash"],
            tokens_always_loaded=d["tokens_always_loaded"],
            tokens_invocation=d.get("tokens_invocation"),
            empirical=d.get("empirical"),
        )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """Point-in-time record of all Component token counts in a config directory.

    Attributes
    ----------
    taken_at:
        ISO-8601 UTC string (e.g. ``"2026-06-18T14:30:05Z"``).
    label:
        Optional human-readable annotation; ``None`` when omitted.
    config_dir:
        Absolute path to the scanned config directory.
    model:
        Anthropic model identifier used for tokenization (e.g. ``"claude-opus-4-8"``).
    tokenizer:
        ``"count_tokens"`` or ``"claude-p-fallback"``.
    totals:
        Aggregate counts: ``{"always_loaded": int, "invocation": int,
        "by_kind": {kind: int, ...}}``.
    components:
        Immutable tuple of Component instances.
    """

    taken_at: str
    label: str | None
    config_dir: str
    model: str
    tokenizer: str
    totals: dict[str, Any]
    components: tuple[Component, ...]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict matching snapshot.schema.json."""
        return {
            "taken_at": self.taken_at,
            "label": self.label,
            "config_dir": self.config_dir,
            "model": self.model,
            "tokenizer": self.tokenizer,
            "totals": self.totals,
            "components": [c.to_dict() for c in self.components],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Snapshot":
        """Construct a Snapshot from a deserialized JSON dict."""
        components = tuple(Component.from_dict(c) for c in d.get("components", []))
        return Snapshot(
            taken_at=d["taken_at"],
            label=d.get("label"),
            config_dir=d["config_dir"],
            model=d["model"],
            tokenizer=d["tokenizer"],
            totals=d["totals"],
            components=components,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_snapshot(
    components: Sequence[Component],
    *,
    config_dir: str,
    model: str,
    tokenizer: str,
    label: str | None,
    taken_at: str,
) -> Snapshot:
    """Compute totals from components and return a fully-constructed Snapshot.

    Parameters
    ----------
    components:
        Component list with token fields already filled by the tokenizer.
    config_dir:
        Absolute path to the scanned config directory (string).
    model:
        Anthropic model identifier used for tokenization.
    tokenizer:
        ``"count_tokens"`` or ``"claude-p-fallback"``.
    label:
        Optional snapshot label; ``None`` when omitted.
    taken_at:
        ISO-8601 UTC timestamp string, supplied by the caller.

    Returns
    -------
    Snapshot
        Immutable snapshot with ``totals`` computed from the supplied components.
    """
    always_loaded_total = sum(c.tokens_always_loaded for c in components)
    invocation_total = sum(
        c.tokens_invocation for c in components if c.tokens_invocation is not None
    )
    by_kind: dict[str, int] = {k: 0 for k in _ALL_KINDS}
    for component in components:
        if component.kind in by_kind:
            by_kind[component.kind] += component.tokens_always_loaded

    totals: dict[str, Any] = {
        "always_loaded": always_loaded_total,
        "invocation": invocation_total,
        "by_kind": by_kind,
    }

    return Snapshot(
        taken_at=taken_at,
        label=label,
        config_dir=config_dir,
        model=model,
        tokenizer=tokenizer,
        totals=totals,
        components=tuple(components),
    )
