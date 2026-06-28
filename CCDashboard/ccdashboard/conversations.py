"""
conversations.py — index and resume Claude Code conversations.

Claude Code stores every conversation as a JSONL transcript under
``~/.claude/projects/<encoded-cwd>/<session-id>.jsonl``. Each line is a JSON
event carrying ``cwd``, ``gitBranch``, ``sessionId``, ``timestamp``, an
``aiTitle`` (Claude's generated title), and a ``message`` with role + content.

This module:
  * ``index_conversations()`` — scan all transcripts into ``Conversation`` records.
  * ``launch_resume()``        — open ``cd <cwd>; claude --resume <id>`` (claude by its
                                 FULL path) in the user's terminal. The mechanism is
                                 per-OS: on **Windows** the command is placed on the
                                 clipboard and the user's own Start-menu admin launch
                                 (Win -> "powershell" -> Ctrl+Shift+Enter) is replayed
                                 to open THEIR elevated terminal to paste into; on
                                 **Linux** a terminal emulator is spawned to run it; on
                                 **macOS** it runs in Terminal.app via ``osascript``.

Security: ``launch_resume`` only ever resumes a ``session_id`` that exists in the
index, takes the working directory from the (trusted) transcript — never from the
caller — and validates the id against a strict pattern. The cwd and the claude path
are quoted for the target shell (single-quote-escaped for the Windows PowerShell
literal; ``shlex.quote`` for the POSIX shell). On Windows we never spawn a shell
ourselves (the user pastes), and UIPI is why the command is delivered via the
clipboard rather than typed into the elevated window.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_TEXT_PER_CONVO = 1_000_000  # cap searchable text per conversation (chars)


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
    # Precomputed search fields, built once at index time (not serialized):
    title_lc: str = ""  # title.lower()
    body_lc: str = ""  # text.lower()
    project_lc: str = ""  # cwd.lower() (full path, so project:smart-gift-card works)
    branch_lc: str = ""  # git_branch.lower()
    project_name: str = ""  # Path(cwd).name (leaf folder, for display + dropdown)
    last_date: date | None = None  # parsed date(last_at), for range filters + recency

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


def _parse_date(ts: str) -> date | None:
    """Parse an ISO-8601 timestamp's date (or None)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return None


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
        title_lc=title.lower(),
        body_lc=body_text.lower(),
        project_lc=cwd.lower(),
        branch_lc=(branch or "—").lower(),
        project_name=Path(cwd).name,
        last_date=_parse_date(last),
    )


def _decode_project_dir(name: str) -> str:
    """Best-effort decode of an encoded project dir name back to a path.

    Claude encodes the cwd by replacing path separators with ``-`` (e.g.
    ``C--Users-Nithin-MyGit`` on Windows, ``-home-nithin-MyGit`` on POSIX). This is a
    lossy, display-only fallback used when an event has no explicit ``cwd``; a real
    separator cannot be reliably distinguished from a literal ``-``. The separator we
    restore is platform-appropriate: ``\\`` (with the drive colon) on Windows, ``/``
    on POSIX.
    """
    if os.name == "nt":
        if len(name) >= 2 and name[1] == "-" and name[0].isalpha():
            return name[0] + ":" + name[1:].replace("-", "\\")
        return name.replace("-", "\\")
    return name.replace("-", "/")


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


# Linux terminal emulators we try, in order; the first one ``shutil.which`` finds
# hosts the resume. ``x-terminal-emulator`` is Debian's "default terminal" alternative;
# ``ptyxis`` is the modern GNOME/Fedora default and ``kgx`` is GNOME Console; the rest
# are common concrete emulators.
_LINUX_TERMINALS: tuple[str, ...] = (
    "x-terminal-emulator",
    "ptyxis",
    "gnome-terminal",
    "kgx",
    "konsole",
    "xfce4-terminal",
    "alacritty",
    "kitty",
    "foot",
    "xterm",
)


def _find_terminal() -> str | None:
    """Full path to the first installed Linux terminal emulator, or None if none."""
    for name in _LINUX_TERMINALS:
        found = shutil.which(name)
        if found:
            return found
    return None


def _posix_shell_command(cwd: str, claude_exe: str, session_id: str) -> str:
    """``cd <cwd>; <claude> --resume <id>`` with cwd + claude path POSIX-shell-quoted.

    ``session_id`` is already validated against ``_SESSION_ID_RE`` (no whitespace or
    shell metacharacters), so only the two paths need ``shlex.quote``.
    """
    import shlex

    return f"cd {shlex.quote(cwd)}; {shlex.quote(claude_exe)} --resume {session_id}"


def _linux_resume_argv(
    term: str, cwd: str, claude_exe: str, session_id: str
) -> list[str]:
    """Argv that opens ``term`` running the resume, then drops to an interactive shell.

    Emulators disagree on how to pass a command: ptyxis / gnome-terminal / kgx take it
    after ``--`` (ptyxis also needs ``--standalone`` so it spawns its own window rather
    than handing off to the D-Bus service and exiting); kitty / foot take it directly;
    the rest take it after ``-e``. ``exec bash`` keeps the window open after Claude exits
    so the user isn't dropped immediately.
    """
    inner = f"{_posix_shell_command(cwd, claude_exe, session_id)}; exec bash"
    cmd = ["bash", "-lc", inner]
    name = os.path.basename(term)
    if name == "ptyxis":
        return [term, "--standalone", "--new-window", "--", *cmd]
    if name in ("gnome-terminal", "kgx"):
        return [term, "--", *cmd]
    if name in ("kitty", "foot"):
        return [term, *cmd]
    return [term, "-e", *cmd]


def _macos_resume_argv(cwd: str, claude_exe: str, session_id: str) -> list[str]:
    """Argv for ``osascript`` that runs the resume in a new Terminal.app window.

    The shell command is POSIX-quoted, then ``\\`` and ``"`` are escaped for the
    AppleScript double-quoted string literal the command is embedded in.
    """
    shell_cmd = _posix_shell_command(cwd, claude_exe, session_id)
    applescript_literal = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Terminal" to do script "{applescript_literal}"'
    return ["osascript", "-e", script]


def _resume_plan(convo: Conversation) -> dict:
    """The OS-appropriate resume plan, built but never run (safe for dry-run).

    * Windows: a PowerShell one-liner (``command``) delivered via the clipboard + a
      synthetic Start-menu admin launch — no argv is spawned, so the returned plan
      keeps exactly its original keys (``session_id``/``cwd``/``claude_exe``/``command``).
    * Linux: a plan that adds ``mode``/``platform`` and the exact terminal-emulator
      ``argv`` that would be spawned. Raises ``RuntimeError`` if no terminal is found.
    * macOS: likewise, with an ``osascript`` ``argv``.

    ``cwd`` always comes from the indexed transcript (never the caller); the caller is
    responsible for validating ``session_id`` against ``_SESSION_ID_RE`` beforehand.
    """
    cwd = convo.cwd
    session_id = convo.session_id
    claude_exe = _claude_exe()

    if os.name == "nt":
        return {
            "session_id": session_id,
            "cwd": cwd,
            "claude_exe": claude_exe,
            "command": _build_resume_command(cwd, claude_exe, session_id),
        }

    if sys.platform == "darwin":
        argv = _macos_resume_argv(cwd, claude_exe, session_id)
        mode = "macos-osascript"
    else:
        term = _find_terminal()
        if term is None:
            raise RuntimeError(
                "no terminal emulator found to open the resume — install one of: "
                + ", ".join(_LINUX_TERMINALS)
            )
        argv = _linux_resume_argv(term, cwd, claude_exe, session_id)
        mode = "linux-terminal"

    import shlex

    return {
        "session_id": session_id,
        "cwd": cwd,
        "claude_exe": claude_exe,
        "mode": mode,
        "platform": sys.platform,
        "argv": argv,
        "command": shlex.join(argv),  # display/inspection copy of the argv
    }


def build_resume_plan(convo: Conversation) -> dict:
    """Build (without running) the OS-appropriate resume plan for inspection/dry-run."""
    if not _SESSION_ID_RE.match(convo.session_id):
        raise ValueError(f"refusing to resume — invalid session id: {convo.session_id!r}")
    return _resume_plan(convo)


def launch_resume(
    session_id: str,
    conversations: list[Conversation],
    *,
    dry_run: bool = False,
) -> dict:
    """Resume ``session_id`` in the user's terminal, using the per-OS mechanism.

    * **Windows**: copies ``cd <cwd>; claude --resume <id>`` (claude by full path) to
      the clipboard, then replays Win -> "powershell" -> Ctrl+Shift+Enter so the SAME
      elevated terminal the user normally uses opens; they finish with Ctrl+V + Enter.
    * **Linux**: spawns the first available terminal emulator running the resume.
    * **macOS**: runs the resume in Terminal.app via ``osascript``.

    The id must exist in ``conversations`` and the working dir comes from that record
    (never the caller). With ``dry_run=True`` nothing is copied, typed, or launched —
    the plan is just returned (so tests fire no keystrokes, UAC prompt, or processes).
    Off Windows the plan also carries ``mode``/``platform`` and the exact ``argv`` that
    would be spawned, so the launch decision is inspectable without running it.
    """
    convo = next((c for c in conversations if c.session_id == session_id), None)
    if convo is None:
        raise KeyError(f"unknown session id: {session_id!r}")
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session id: {session_id!r}")

    plan = _resume_plan(convo)
    if dry_run:
        return plan

    if os.name == "nt":
        _set_clipboard(plan["command"])
        _open_admin_terminal_via_search()
    else:
        import subprocess

        # Detach: own session + no inherited stdio, so the spawned terminal never
        # corrupts CCDashboard's own TUI and survives if the dashboard exits.
        subprocess.Popen(
            plan["argv"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return plan


if __name__ == "__main__":  # built-in smoke test (no elevation; dry-run only)
    from ccdashboard import search

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
        hits = search.rank(idx, search.parse_query("dashboard"))
        print(f"\nsearch 'dashboard' -> {len(hits)} hits; first: "
              f"{(hits[0].title[:50]) if hits else '—'}")
        plan = launch_resume(idx[0].session_id, idx, dry_run=True)
        print(f"\ndry-run resume of newest ({idx[0].session_id[:12]}…):")
        print("  claude :", plan["claude_exe"])
        print("  command:", plan["command"])
