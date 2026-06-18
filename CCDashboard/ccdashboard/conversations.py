"""
conversations.py — index, search, and resume Claude Code conversations.

Claude Code stores every conversation as a JSONL transcript under
``~/.claude/projects/<encoded-cwd>/<session-id>.jsonl``. Each line is a JSON
event carrying ``cwd``, ``gitBranch``, ``sessionId``, ``timestamp``, an
``aiTitle`` (Claude's generated title), and a ``message`` with role + content.

This module:
  * ``index_conversations()`` — scan all transcripts into ``Conversation`` records.
  * ``search()``               — full-text keyword search with snippets.
  * ``launch_resume()``        — open an ELEVATED Windows PowerShell that cd's to
                                 the conversation's working dir and runs
                                 ``claude --resume <session-id>``.

Security: ``launch_resume`` only ever resumes a ``session_id`` that exists in the
index, takes the working directory from the (trusted) transcript — never from the
caller — and validates the id against a strict pattern. The elevated command runs
from a generated ``.ps1`` so there is no shell-string interpolation of untrusted
input.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_TEXT_PER_CONVO = 500_000  # cap searchable text per conversation (chars)


@dataclass(frozen=True)
class Conversation:
    """One Claude Code conversation (transcript)."""

    session_id: str
    cwd: str
    git_branch: str
    title: str
    started_at: str
    last_at: str
    message_count: int
    project_dir: str
    file_path: str
    text: str = ""  # concatenated message text, for search (not serialized to clients)

    def to_dict(self, *, include_text: bool = False) -> dict:
        data = {
            "session_id": self.session_id,
            "cwd": self.cwd,
            "git_branch": self.git_branch,
            "title": self.title,
            "started_at": self.started_at,
            "last_at": self.last_at,
            "message_count": self.message_count,
            "project_dir": self.project_dir,
        }
        if include_text:
            data["text"] = self.text
        return data


def _projects_dir(projects_dir: Path | None) -> Path:
    return projects_dir or (Path.home() / ".claude" / "projects")


def _block_text(content: object) -> str:
    """Extract human-readable text from a message ``content`` (str or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, str):
                    parts.append(inner)
                elif isinstance(inner, list):
                    parts.append(_block_text(inner))
        return "\n".join(parts)
    return ""


def _parse_session(path: Path) -> Conversation | None:
    """Parse one transcript file into a Conversation (or None if unreadable/empty)."""
    cwd = ""
    branch = ""
    title = ""
    first_user = ""
    started = ""
    last = ""
    msg_count = 0
    text_parts: list[str] = []
    text_len = 0
    session_id = path.stem

    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue

                if not cwd and isinstance(ev.get("cwd"), str):
                    cwd = ev["cwd"]
                if not branch and isinstance(ev.get("gitBranch"), str):
                    branch = ev["gitBranch"]
                if not title and isinstance(ev.get("aiTitle"), str) and ev["aiTitle"].strip():
                    title = ev["aiTitle"].strip()
                if isinstance(ev.get("sessionId"), str):
                    session_id = ev["sessionId"]

                ts = ev.get("timestamp")
                if isinstance(ts, str):
                    if not started or ts < started:
                        started = ts
                    if ts > last:
                        last = ts

                msg = ev.get("message")
                if isinstance(msg, dict):
                    role = msg.get("role")
                    if role in ("user", "assistant"):
                        msg_count += 1
                    body = _block_text(msg.get("content"))
                    if body:
                        if role == "user" and not first_user:
                            first_user = body.strip()
                        if text_len < _MAX_TEXT_PER_CONVO:
                            text_parts.append(body)
                            text_len += len(body)
    except OSError:
        return None

    if msg_count == 0 and not text_parts:
        return None

    if not title:
        title = (first_user[:120] + "…") if len(first_user) > 120 else (first_user or "(untitled)")
    if not cwd:
        cwd = _decode_project_dir(path.parent.name)

    return Conversation(
        session_id=session_id,
        cwd=cwd,
        git_branch=branch or "—",
        title=title,
        started_at=started,
        last_at=last,
        message_count=msg_count,
        project_dir=path.parent.name,
        file_path=str(path),
        text="\n".join(text_parts),
    )


def _decode_project_dir(name: str) -> str:
    """Best-effort decode of an encoded project dir name back to a path.

    Claude encodes the cwd by replacing path separators with ``-`` (e.g.
    ``C--Users-Nithin-MyGit``). This is a lossy fallback only used when an event
    has no explicit ``cwd``; ``\\`` cannot be reliably distinguished from a literal
    ``-``, so we just present the encoded form with the drive colon restored.
    """
    if len(name) >= 2 and name[1] == "-" and name[0].isalpha():
        return name[0] + ":" + name[1:].replace("-", "\\")
    return name.replace("-", "\\")


def index_conversations(projects_dir: Path | None = None) -> list[Conversation]:
    """Scan all transcripts into Conversation records, newest activity first."""
    root = _projects_dir(projects_dir)
    if not root.exists():
        return []
    convos: list[Conversation] = []
    for path in root.glob("*/*.jsonl"):
        convo = _parse_session(path)
        if convo is not None:
            convos.append(convo)
    convos.sort(key=lambda c: c.last_at, reverse=True)
    return convos


def _snippet(text: str, terms: list[str], width: int = 160) -> str:
    """Return a context window around the first matching term."""
    lower = text.lower()
    pos = -1
    for term in terms:
        i = lower.find(term)
        if i != -1 and (pos == -1 or i < pos):
            pos = i
    if pos == -1:
        return ""
    start = max(0, pos - width // 2)
    end = min(len(text), pos + width // 2)
    snip = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + snip + ("…" if end < len(text) else "")


def search(conversations: list[Conversation], query: str) -> list[dict]:
    """Full-text search: every term must appear in the title or body (AND).

    Returns result dicts (conversation metadata + a ``snippet``), newest first.
    An empty query returns all conversations (no snippet).
    """
    terms = [t for t in query.lower().split() if t]
    results: list[dict] = []
    for convo in conversations:
        if terms:
            haystack = (convo.title + "\n" + convo.text).lower()
            if not all(term in haystack for term in terms):
                continue
        item = convo.to_dict()
        item["snippet"] = _snippet(convo.text, terms) if terms else ""
        results.append(item)
    return results


def _build_ps1(cwd: str, session_id: str) -> str:
    """Generate the PowerShell script the elevated window runs."""
    cwd_lit = cwd.replace("'", "''")  # escape single quotes for a PS literal
    return (
        "$Host.UI.RawUI.WindowTitle = 'Claude — resume'\n"
        f"Set-Location -LiteralPath '{cwd_lit}'\n"
        f"claude --resume {session_id}\n"
    )


def build_resume_plan(convo: Conversation) -> dict:
    """Build (without running) the elevated-resume plan for inspection/dry-run."""
    if not _SESSION_ID_RE.match(convo.session_id):
        raise ValueError(f"refusing to resume — invalid session id: {convo.session_id!r}")
    return {
        "session_id": convo.session_id,
        "cwd": convo.cwd,
        "ps1": _build_ps1(convo.cwd, convo.session_id),
    }


def launch_resume(
    session_id: str,
    conversations: list[Conversation],
    *,
    dry_run: bool = False,
) -> dict:
    """Open an elevated PowerShell that resumes ``session_id`` in its working dir.

    The id must exist in ``conversations``; the working dir is taken from that
    record (never the caller). With ``dry_run=True`` the command is returned but
    nothing is spawned (used for tests, so no UAC prompt fires).
    """
    convo = next((c for c in conversations if c.session_id == session_id), None)
    if convo is None:
        raise KeyError(f"unknown session id: {session_id!r}")
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session id: {session_id!r}")

    ps1 = _build_ps1(convo.cwd, convo.session_id)
    tmp = Path(tempfile.gettempdir()) / f"ccchats-resume-{session_id}.ps1"
    # Outer (non-elevated) command: Start-Process elevates a new PowerShell that
    # runs the generated script file. -File avoids any inline-command quoting.
    outer = (
        "Start-Process -FilePath powershell -Verb RunAs -ArgumentList "
        f"'-NoExit','-NoProfile','-ExecutionPolicy','Bypass','-File','{str(tmp)}'"
    )
    argv = ["powershell", "-NoProfile", "-Command", outer]

    if dry_run:
        return {"session_id": session_id, "cwd": convo.cwd, "ps1_path": str(tmp), "argv": argv, "ps1": ps1}

    tmp.write_text(ps1, encoding="utf-8")
    subprocess.Popen(argv)  # fires the UAC prompt; the elevated window then resumes
    return {"session_id": session_id, "cwd": convo.cwd, "ps1_path": str(tmp), "argv": argv}


if __name__ == "__main__":  # built-in smoke test (no elevation; dry-run only)
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    idx = index_conversations()
    print(f"Indexed {len(idx)} conversations")
    for c in idx[:5]:
        print(f"  [{c.git_branch:<22.22}] {Path(c.cwd).name:<18.18} {c.message_count:>4} msgs  "
              f"{c.last_at[:16]}  {c.title[:46]}")
    if idx:
        hits = search(idx, "dashboard")
        print(f"\nsearch 'dashboard' -> {len(hits)} hits; first: "
              f"{(hits[0]['title'][:50] + ' :: ' + hits[0]['snippet'][:60]) if hits else '—'}")
        plan = launch_resume(idx[0].session_id, idx, dry_run=True)
        print(f"\ndry-run resume of newest ({idx[0].session_id[:12]}…):")
        print("  argv:", plan["argv"])
        print("  ps1 :", plan["ps1"].replace(chr(10), " | "))
