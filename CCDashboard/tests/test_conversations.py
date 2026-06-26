"""Tests for the conversation indexer (``ccdashboard.conversations``).

These write tiny real JSONL transcripts to ``tmp_path`` in the same layout Claude
Code uses (``<projects-dir>/<encoded-cwd>/<session-id>.jsonl``) and assert that
``index_conversations`` / ``_parse_session`` derive the precomputed search fields
(Section 3 of the spec): ``project_name``, ``last_date``, ``title_lc``/``body_lc``,
the raised 1 MB cap, and newest-first index order.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ccdashboard import conversations
from ccdashboard.conversations import Conversation

pytestmark = pytest.mark.unit


def _write_transcript(
    projects_dir: Path,
    *,
    encoded_dir: str,
    session_id: str,
    events: list[dict],
) -> Path:
    """Write a JSONL transcript (one JSON event per line) and return its path."""
    convo_dir = projects_dir / encoded_dir
    convo_dir.mkdir(parents=True, exist_ok=True)
    path = convo_dir / f"{session_id}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for ev in events:
            handle.write(json.dumps(ev) + "\n")
    return path


def _event(
    *,
    cwd: str,
    branch: str,
    session_id: str,
    timestamp: str,
    role: str,
    content: object,
    ai_title: str | None = None,
) -> dict:
    ev: dict = {
        "cwd": cwd,
        "gitBranch": branch,
        "sessionId": session_id,
        "timestamp": timestamp,
        "message": {"role": role, "content": content},
    }
    if ai_title is not None:
        ev["aiTitle"] = ai_title
    return ev


def test_parse_session_derives_search_fields(tmp_path: Path) -> None:
    cwd = "C:\\Users\\dev\\MyGit\\smart-gift-card"
    path = _write_transcript(
        tmp_path,
        encoded_dir="C--Users-dev-MyGit-smart-gift-card",
        session_id="sess-abc-123",
        events=[
            _event(
                cwd=cwd,
                branch="feature/login",
                session_id="sess-abc-123",
                timestamp="2026-06-20T09:00:00.000Z",
                role="user",
                content="How do I GREP the logs?",
                ai_title="Grep The Logs",
            ),
            _event(
                cwd=cwd,
                branch="feature/login",
                session_id="sess-abc-123",
                timestamp="2026-06-20T09:05:00.000Z",
                role="assistant",
                content="Use ripgrep instead.",
            ),
        ],
    )

    convo = conversations._parse_session(path)
    assert convo is not None
    assert isinstance(convo, Conversation)

    # project_name is the leaf folder of cwd.
    assert convo.project_name == "smart-gift-card"
    # last_date is the parsed date of the newest timestamp.
    assert convo.last_date == date(2026, 6, 20)
    # title_lc / body_lc / project_lc / branch_lc are lowercased.
    assert convo.title == "Grep The Logs"
    assert convo.title_lc == "grep the logs"
    assert "grep the logs?" in convo.body_lc
    assert "ripgrep instead." in convo.body_lc
    assert convo.project_lc == cwd.lower()
    assert convo.branch_lc == "feature/login"
    # message_count counts user + assistant messages.
    assert convo.message_count == 2


def test_parse_session_missing_branch_defaults_to_dash(tmp_path: Path) -> None:
    cwd = "C:\\Repos\\app"
    path = _write_transcript(
        tmp_path,
        encoded_dir="C--Repos-app",
        session_id="no-branch",
        events=[
            {
                "cwd": cwd,
                "sessionId": "no-branch",
                "timestamp": "2026-06-01T00:00:00.000Z",
                "message": {"role": "user", "content": "hi"},
            }
        ],
    )
    convo = conversations._parse_session(path)
    assert convo is not None
    assert convo.git_branch == "—"
    assert convo.branch_lc == "—"


def test_parse_session_bad_timestamp_yields_none_last_date(tmp_path: Path) -> None:
    path = _write_transcript(
        tmp_path,
        encoded_dir="C--Repos-app",
        session_id="bad-ts",
        events=[
            {
                "cwd": "C:\\Repos\\app",
                "sessionId": "bad-ts",
                "timestamp": "not-a-timestamp",
                "message": {"role": "user", "content": "hello"},
            }
        ],
    )
    convo = conversations._parse_session(path)
    assert convo is not None
    assert convo.last_date is None


def test_parse_date_helper() -> None:
    assert conversations._parse_date("2026-06-24T10:30:00.000Z") == date(2026, 6, 24)
    assert conversations._parse_date("2026-06-24T10:30:00+00:00") == date(2026, 6, 24)
    assert conversations._parse_date("") is None
    assert conversations._parse_date("garbage") is None


def test_text_truncation_cap_is_one_megabyte() -> None:
    # The spec raised the cap from 500k to 1 MB.
    assert conversations._MAX_TEXT_PER_CONVO == 1_000_000


def test_parse_session_respects_text_cap(tmp_path: Path) -> None:
    cap = conversations._MAX_TEXT_PER_CONVO
    big_chunk = "x" * 200_000  # 200k chars per message
    events = [
        _event(
            cwd="C:\\Repos\\big",
            branch="main",
            session_id="big-convo",
            timestamp=f"2026-06-{(i % 27) + 1:02d}T00:00:00.000Z",
            role="user",
            content=big_chunk,
        )
        for i in range(10)  # ~2 MB of body before the cap
    ]
    path = _write_transcript(
        tmp_path, encoded_dir="C--Repos-big", session_id="big-convo", events=events
    )
    convo = conversations._parse_session(path)
    assert convo is not None
    # Body is truncated near the cap: it stops appending once text_len >= cap, so the
    # captured text never grows unboundedly. With 200k-char chunks it lands within one
    # chunk of the cap.
    assert len(convo.text) <= cap + len(big_chunk)
    assert len(convo.text) >= cap  # but it did capture up to the cap


def test_index_conversations_newest_first(tmp_path: Path) -> None:
    _write_transcript(
        tmp_path,
        encoded_dir="C--Repos-a",
        session_id="old",
        events=[
            _event(
                cwd="C:\\Repos\\a",
                branch="main",
                session_id="old",
                timestamp="2026-05-01T10:00:00.000Z",
                role="user",
                content="oldest",
            )
        ],
    )
    _write_transcript(
        tmp_path,
        encoded_dir="C--Repos-b",
        session_id="new",
        events=[
            _event(
                cwd="C:\\Repos\\b",
                branch="main",
                session_id="new",
                timestamp="2026-06-24T10:00:00.000Z",
                role="user",
                content="newest",
            )
        ],
    )
    _write_transcript(
        tmp_path,
        encoded_dir="C--Repos-c",
        session_id="mid",
        events=[
            _event(
                cwd="C:\\Repos\\c",
                branch="main",
                session_id="mid",
                timestamp="2026-06-01T10:00:00.000Z",
                role="user",
                content="middle",
            )
        ],
    )

    index = conversations.index_conversations(tmp_path)
    assert [c.session_id for c in index] == ["new", "mid", "old"]
    # last_at descending == newest-first.
    assert index[0].last_at > index[-1].last_at


def test_index_conversations_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert conversations.index_conversations(tmp_path) == []


def test_index_conversations_skips_empty_transcripts(tmp_path: Path) -> None:
    convo_dir = tmp_path / "C--Repos-empty"
    convo_dir.mkdir(parents=True)
    (convo_dir / "empty.jsonl").write_text("", encoding="utf-8")
    assert conversations.index_conversations(tmp_path) == []
