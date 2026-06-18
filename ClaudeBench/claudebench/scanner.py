"""
scanner.py — walk ~/.claude/ and produce a list of Component instances.

Token fields are left at zero; the tokenizer fills them in the next step.

Public API
----------
scan(config_dir: Path) -> list[Component]
    Return all discovered config components, sorted deterministically by
    (kind, id).  Missing directories are tolerated; the function always
    returns a list (possibly empty).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Sequence

from claudebench.models import Component

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Directories and files that must never be read or hashed (contain secrets).
_SECRET_PATTERNS: frozenset[str] = frozenset({
    "token.json",
    ".credentials.json",
})

_SECRET_GLOBS: tuple[str, ...] = ("credentials*",)


def _is_secret(path: Path) -> bool:
    """Return True if the file should never be read (secrets guard)."""
    name = path.name
    if name in _SECRET_PATTERNS:
        return True
    for glob in _SECRET_GLOBS:
        if path.match(glob):
            return True
    return False


def _sha256(path: Path) -> str:
    """Return ``"sha256:<hexdigest>"`` for the file's UTF-8 bytes.

    Falls back to hashing the raw bytes if the file is not valid UTF-8.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return "sha256:" + "0" * 64
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _relative_posix(config_dir: Path, path: Path) -> str:
    """Return a forward-slash path of ``path`` relative to ``config_dir``."""
    return path.relative_to(config_dir).as_posix()


# ---------------------------------------------------------------------------
# YAML frontmatter name extraction
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^---[ \t]*\r?\n(.*?)^---[ \t]*\r?\n", re.DOTALL | re.MULTILINE
)
_NAME_RE = re.compile(r"^name\s*:\s*(.+)$", re.MULTILINE)


def _name_from_frontmatter(path: Path) -> str | None:
    """Read ``name:`` from YAML frontmatter in a markdown file.

    Returns ``None`` if the file cannot be read or has no ``name`` key.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm = m.group(1)
    name_match = _NAME_RE.search(fm)
    if not name_match:
        return None
    return name_match.group(1).strip().strip("\"'")


def _humanize_id(slug: str) -> str:
    """Convert a kebab-case or underscore slug to a Title Case display name.

    Examples:
        ``"commit-message"`` -> ``"Commit Message"``
        ``"coding_style"``   -> ``"Coding Style"``
    """
    return re.sub(r"[-_]", " ", slug).title()


# ---------------------------------------------------------------------------
# Per-kind scanners
# ---------------------------------------------------------------------------

def _scan_skills(config_dir: Path) -> list[Component]:
    """Discover skills/*/SKILL.md under config_dir.

    id = skill directory name (e.g. ``"commit-message"``).
    name = frontmatter ``name:`` value, falling back to humanized id.
    """
    skills_dir = config_dir / "skills"
    if not skills_dir.is_dir():
        return []

    components: list[Component] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        if _is_secret(skill_file):
            continue

        skill_id = skill_dir.name
        name = _name_from_frontmatter(skill_file) or _humanize_id(skill_id)
        components.append(Component(
            kind="skill",
            id=skill_id,
            name=name,
            path=_relative_posix(config_dir, skill_file),
            content_hash=_sha256(skill_file),
        ))
    return components


def _scan_agents(config_dir: Path) -> list[Component]:
    """Discover agents/*.md under config_dir.

    id = stem of the .md file (e.g. ``"backend-engineer"``).
    name = frontmatter ``name:`` if present, else humanized id.
    """
    agents_dir = config_dir / "agents"
    if not agents_dir.is_dir():
        return []

    components: list[Component] = []
    for agent_file in sorted(agents_dir.glob("*.md")):
        if not agent_file.is_file():
            continue
        if _is_secret(agent_file):
            continue

        agent_id = agent_file.stem
        name = _name_from_frontmatter(agent_file) or _humanize_id(agent_id)
        components.append(Component(
            kind="agent",
            id=agent_id,
            name=name,
            path=_relative_posix(config_dir, agent_file),
            content_hash=_sha256(agent_file),
        ))
    return components


def _scan_memory(config_dir: Path) -> list[Component]:
    """Discover CLAUDE.md (always-loaded user memory) in config_dir."""
    claude_md = config_dir / "CLAUDE.md"
    if not claude_md.is_file():
        return []

    return [Component(
        kind="memory",
        id="CLAUDE.md",
        name="CLAUDE.md",
        path=_relative_posix(config_dir, claude_md),
        content_hash=_sha256(claude_md),
    )]


def _scan_rules(config_dir: Path) -> list[Component]:
    """Discover rules/**/*.md recursively under config_dir/rules/.

    id = POSIX path relative to the rules dir (e.g. ``"common/coding-style"``).
    name = humanized last path component.
    """
    rules_dir = config_dir / "rules"
    if not rules_dir.is_dir():
        return []

    components: list[Component] = []
    for rule_file in sorted(rules_dir.rglob("*.md")):
        if not rule_file.is_file():
            continue
        if _is_secret(rule_file):
            continue

        # id: relative to rules_dir, no extension (e.g. "common/coding-style")
        rel = rule_file.relative_to(rules_dir)
        rule_id = rel.with_suffix("").as_posix()
        name = _humanize_id(rule_file.stem)
        components.append(Component(
            kind="rule",
            id=rule_id,
            name=name,
            path=_relative_posix(config_dir, rule_file),
            content_hash=_sha256(rule_file),
        ))
    return components


def _scan_settings(config_dir: Path) -> list[Component]:
    """Discover settings.json in config_dir."""
    settings_file = config_dir / "settings.json"
    if not settings_file.is_file():
        return []

    return [Component(
        kind="setting",
        id="settings.json",
        name="Settings",
        path=_relative_posix(config_dir, settings_file),
        content_hash=_sha256(settings_file),
    )]


def _scan_mcp(config_dir: Path) -> list[Component]:
    """Best-effort MCP component discovery from .mcp.json if present.

    MCP tool schemas are not local files in the standard layout, so this
    attempts to read server names from ``.mcp.json`` (project-level) or
    ``settings.json`` mcpServers keys.  Token fields are left at zero and
    content_hash is set to a sentinel.  Missing config is silently skipped.
    """
    import json

    components: list[Component] = []
    server_names: list[str] = []

    # Check .mcp.json in config_dir (non-standard but possible)
    mcp_json = config_dir / ".mcp.json"
    if mcp_json.is_file() and not _is_secret(mcp_json):
        try:
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                server_names.extend(data.get("mcpServers", {}).keys())
        except (OSError, json.JSONDecodeError):
            pass

    # Check settings.json for mcpServers key
    settings_file = config_dir / "settings.json"
    if settings_file.is_file() and not _is_secret(settings_file):
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                server_names.extend(data.get("mcpServers", {}).keys())
        except (OSError, json.JSONDecodeError):
            pass

    seen: set[str] = set()
    for name in server_names:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or name
        if slug in seen:
            continue
        seen.add(slug)
        components.append(Component(
            kind="mcp",
            id=slug,
            name=name,
            path="settings.json",  # best-effort; no local schema file
            content_hash="sha256:" + hashlib.sha256(name.encode()).hexdigest(),
            tokens_always_loaded=0,
            tokens_invocation=None,
        ))

    return sorted(components, key=lambda c: c.id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_KIND_ORDER: dict[str, int] = {k: i for i, k in enumerate(
    ("skill", "agent", "mcp", "memory", "rule", "setting")
)}


def scan(config_dir: Path) -> list[Component]:
    """Walk config_dir and return all discovered config components.

    Parameters
    ----------
    config_dir:
        Absolute path to the Claude config directory (typically ``~/.claude``).
        Missing sub-directories are silently skipped.

    Returns
    -------
    list[Component]
        Sorted by ``(kind, id)`` for deterministic snapshot output.
        Token fields are all zero (filled by the tokenizer in the next step).
    """
    all_components: list[Component] = []
    all_components.extend(_scan_skills(config_dir))
    all_components.extend(_scan_agents(config_dir))
    all_components.extend(_scan_mcp(config_dir))
    all_components.extend(_scan_memory(config_dir))
    all_components.extend(_scan_rules(config_dir))
    all_components.extend(_scan_settings(config_dir))

    # Stable sort: primary = kind order, secondary = id alphabetical
    all_components.sort(key=lambda c: (_KIND_ORDER.get(c.kind, 99), c.id))
    return all_components
