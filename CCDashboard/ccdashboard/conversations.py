"""
conversations.py — index, search, and resume Claude Code conversations.

Claude Code stores every conversation as a JSONL transcript under
``~/.claude/projects/<encoded-cwd>/<session-id>.jsonl``. Each line is a JSON
event carrying ``cwd``, ``gitBranch``, ``sessionId``, ``timestamp``, an
``aiTitle`` (Claude's generated title), and a ``message`` with role + content.

This module:
  * ``index_conversations()`` — scan all transcripts into ``Conversation`` records.
  * ``search()``               — full-text keyword search with snippets.
  * ``launch_resume()``        — replay the user's own Start-menu launch (Win ->
                                 type "powershell" -> Ctrl+Shift+Enter) to open
                                 THEIR elevated terminal, with the resume command
                                 (``cd <cwd>; claude --resume <id>``, claude by its
                                 FULL path) placed on the clipboard to paste.

Security: ``launch_resume`` only ever resumes a ``session_id`` that exists in the
index, takes the working directory from the (trusted) transcript — never from the
caller — and validates the id against a strict pattern. The clipboard command
single-quote-escapes the cwd and the claude path for a PowerShell literal; we never
spawn a shell ourselves (the user pastes), and Windows UIPI is why the command is
delivered via the clipboard rather than typed into the elevated window.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
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
    text: str = ""  # concatenated message text (original case), for snippets (not serialized)
    search_blob: str = ""  # (title + "\n" + text).lower(), precomputed once at index time

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

    body_text = "\n".join(text_parts)
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
        text=body_text,
        search_blob=(title + "\n" + body_text).lower(),
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

    Matching uses each conversation's precomputed lowercased ``search_blob``
    (``title`` + body, built once at index time) so no up-to-500k-char string is
    re-lowercased per call. Returns result dicts (conversation metadata + a
    ``snippet``), newest first. An empty query returns all conversations.
    """
    terms = [t for t in query.lower().split() if t]
    results: list[dict] = []
    for convo in conversations:
        if terms and not all(term in convo.search_blob for term in terms):
            continue
        item = convo.to_dict()
        item["snippet"] = _snippet(convo.text, terms) if terms else ""
        results.append(item)
    return results


def filter_conversations(
    conversations: list[Conversation], query: str
) -> list[Conversation]:
    """Return the Conversation objects matching ``query`` (AND over terms).

    Uses each conversation's precomputed lowercased ``search_blob`` and skips snippet
    building, so it is much cheaper than :func:`search` for callers (the TUI) that
    render the records directly and never show snippets. Order is preserved (the
    index is already newest-first); an empty query returns all conversations.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return list(conversations)
    return [c for c in conversations if all(term in c.search_blob for term in terms)]


def _build_resume_command(cwd: str, claude_exe: str, session_id: str) -> str:
    """The one-line PowerShell command that resumes the conversation.

    Placed on the clipboard for the user to paste into the elevated window (Windows
    UIPI forbids us from typing into a higher-integrity window). The working dir and
    claude's FULL path are baked in so it runs even though an *elevated* shell's PATH
    omits the per-user install dir (``~/.local/bin``) where ``claude`` lives. ``cwd``
    and the exe path are single-quote escaped for a PowerShell literal; ``session_id``
    is already validated against ``_SESSION_ID_RE`` (no spaces or quotes).
    """
    cwd_lit = cwd.replace("'", "''")
    exe_lit = claude_exe.replace("'", "''")
    return f"Set-Location -LiteralPath '{cwd_lit}'; & '{exe_lit}' --resume {session_id}"


def _claude_exe() -> str:
    """Full path to the claude CLI resolved in THIS (non-elevated) process, or bare
    ``claude`` as a last resort. The absolute path is what lets the command succeed
    in an elevated shell whose PATH lacks the per-user install dir."""
    return shutil.which("claude") or "claude"


def _set_clipboard(text: str) -> None:
    """Put ``text`` on the Windows clipboard as CF_UNICODETEXT (stdlib ctypes only)."""
    import ctypes
    from ctypes import wintypes

    cf_unicodetext = 13
    gmem_moveable = 0x0002
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

    buf = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise OSError("could not open the Windows clipboard")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(gmem_moveable, len(buf))
        if not handle:
            raise OSError("clipboard GlobalAlloc failed")
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, buf, len(buf))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(cf_unicodetext, handle):
            raise OSError("clipboard SetClipboardData failed")
        # Ownership of `handle` passes to the clipboard; do not free it.
    finally:
        user32.CloseClipboard()


# Start-menu launch timing. Generous so search results resolve before
# Ctrl+Shift+Enter fires; bump these if your machine is slower.
_WIN_OPEN_DELAY = 0.6   # after the Win tap, wait for Start to open
_TYPE_DELAY = 0.03      # between typed characters
_RESULTS_DELAY = 1.0    # after typing, wait for the top result to resolve
_SEARCH_QUERY = "powershell"


def _open_admin_terminal_via_search() -> None:
    """Replay Win -> type "powershell" -> Ctrl+Shift+Enter (launch as admin).

    Reproduces the user's own muscle-memory so the SAME terminal they normally get
    from Start search opens. Synthetic input via ``keybd_event`` reaches the
    non-elevated Start menu fine; once the *elevated* window appears Windows UIPI
    blocks further injected input into it, which is why the resume command is
    delivered through the clipboard (paste) rather than typed.
    """
    import ctypes
    import time

    user32 = ctypes.windll.user32
    vk_lwin, vk_ctrl, vk_shift, vk_return = 0x5B, 0x11, 0x10, 0x0D
    keyup = 0x0002

    def down(vk: int) -> None:
        user32.keybd_event(vk, 0, 0, 0)

    def up(vk: int) -> None:
        user32.keybd_event(vk, 0, keyup, 0)

    def tap(vk: int) -> None:
        down(vk)
        up(vk)

    tap(vk_lwin)
    time.sleep(_WIN_OPEN_DELAY)
    for ch in _SEARCH_QUERY:
        tap(user32.VkKeyScanW(ord(ch)) & 0xFF)
        time.sleep(_TYPE_DELAY)
    time.sleep(_RESULTS_DELAY)
    down(vk_ctrl)
    time.sleep(0.03)
    down(vk_shift)
    time.sleep(0.03)
    tap(vk_return)  # Ctrl+Shift+Enter -> run the top result as Administrator
    time.sleep(0.03)
    up(vk_shift)
    up(vk_ctrl)


def build_resume_plan(convo: Conversation) -> dict:
    """Build (without running) the resume plan for inspection/dry-run."""
    if not _SESSION_ID_RE.match(convo.session_id):
        raise ValueError(f"refusing to resume — invalid session id: {convo.session_id!r}")
    claude_exe = _claude_exe()
    return {
        "session_id": convo.session_id,
        "cwd": convo.cwd,
        "claude_exe": claude_exe,
        "command": _build_resume_command(convo.cwd, claude_exe, convo.session_id),
    }


def launch_resume(
    session_id: str,
    conversations: list[Conversation],
    *,
    dry_run: bool = False,
) -> dict:
    """Resume ``session_id`` in the user's own admin terminal via Start-menu search.

    Copies ``cd <cwd>; claude --resume <id>`` (claude by full path) to the clipboard,
    then replays Win -> type "powershell" -> Ctrl+Shift+Enter so the SAME elevated
    terminal the user normally uses opens; they finish with Ctrl+V + Enter. The id
    must exist in ``conversations`` and the working dir comes from that record (never
    the caller). With ``dry_run=True`` nothing is copied or typed — the plan is just
    returned (so tests fire no keystrokes and no UAC prompt).
    """
    convo = next((c for c in conversations if c.session_id == session_id), None)
    if convo is None:
        raise KeyError(f"unknown session id: {session_id!r}")
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session id: {session_id!r}")

    claude_exe = _claude_exe()
    command = _build_resume_command(convo.cwd, claude_exe, session_id)
    plan = {
        "session_id": session_id,
        "cwd": convo.cwd,
        "claude_exe": claude_exe,
        "command": command,
    }
    if dry_run:
        return plan

    _set_clipboard(command)
    _open_admin_terminal_via_search()
    return plan


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
        print("  claude :", plan["claude_exe"])
        print("  command:", plan["command"])
