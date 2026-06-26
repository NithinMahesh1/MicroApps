"""Shared pytest fixtures for the CCDashboard test suite.

The engine (``search`` / ``conversations``) is pure and UI-agnostic, so most
fixtures here build real :class:`ccdashboard.conversations.Conversation` records
in-memory. ``make_convo`` mirrors exactly how ``_parse_session`` derives the
precomputed ``*_lc`` fields, ``project_name`` and ``last_date`` so unit tests
exercise the same shape the indexer produces at runtime — no hand-maintained
duplicates that could drift from the real model.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Callable

import pytest

# Make ``from ccdashboard import ...`` resolve no matter pytest's CWD: the package
# lives at ``CCDashboard/ccdashboard`` and the repo's entry point puts ``CCDashboard``
# on ``sys.path`` (it is not pip-installed). Mirror that here.
_CCDASHBOARD_ROOT = Path(__file__).resolve().parent.parent
if str(_CCDASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(_CCDASHBOARD_ROOT))

from ccdashboard import conversations  # noqa: E402  (after sys.path shim)
from ccdashboard.conversations import Conversation  # noqa: E402

# A fixed "today" so recency math is deterministic across runs. Every default
# timestamp below is anchored relative to this date.
_FROZEN_NOW = date(2026, 6, 24)


@pytest.fixture
def freeze_now() -> date:
    """A deterministic ``now`` date passed to ``search.rank``/``search`` for stable recency."""
    return _FROZEN_NOW


@pytest.fixture
def make_convo() -> Callable[..., Conversation]:
    """Factory building a real ``Conversation`` with sensible defaults.

    Computes ``title_lc``/``body_lc``/``project_lc``/``branch_lc``/``project_name``/
    ``last_date`` the same way :func:`conversations._parse_session` does, so tests
    use the indexer's true derived fields. Pass ``**overrides`` for any base field;
    the derived fields are recomputed from the (possibly overridden) base fields and
    can themselves be overridden explicitly if a test needs an unusual shape.
    """

    _DERIVED_FIELDS = (
        "title_lc",
        "body_lc",
        "project_lc",
        "branch_lc",
        "project_name",
        "last_date",
    )

    def _make(**overrides: object) -> Conversation:
        base: dict = {
            "session_id": "sess0001-aaaa-bbbb-cccc-000000000001",
            "cwd": "C:\\Users\\dev\\MyGit\\smart-gift-card",
            "git_branch": "main",
            "title": "Untitled conversation",
            "started_at": "2026-06-24T09:00:00.000Z",
            "last_at": "2026-06-24T10:30:00.000Z",
            "message_count": 4,
            "project_dir": "C--Users-dev-MyGit-smart-gift-card",
            "file_path": "C:\\fake\\transcript.jsonl",
            "text": "",
        }
        # Split overrides: base-field overrides feed the derived computation; derived
        # overrides (e.g. last_date=None) are applied after and never duplicated.
        base_overrides = {k: v for k, v in overrides.items() if k not in _DERIVED_FIELDS}
        base.update(base_overrides)

        title = str(base["title"])
        text = str(base["text"])
        cwd = str(base["cwd"])
        branch = str(base["git_branch"])

        derived: dict = {
            "title_lc": title.lower(),
            "body_lc": text.lower(),
            "project_lc": cwd.lower(),
            "branch_lc": (branch or "—").lower(),
            "project_name": Path(cwd).name,
            "last_date": conversations._parse_date(str(base["last_at"])),
        }
        # Allow a test to override a derived field explicitly (e.g. last_date=None).
        for key in _DERIVED_FIELDS:
            if key in overrides:
                derived[key] = overrides[key]

        return Conversation(**base, **derived)

    return _make
