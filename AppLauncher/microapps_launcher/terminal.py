"""Open a command in a NEW OS terminal window (Linux / macOS).

On Windows the launcher uses ``subprocess`` creation flags
(``CREATE_NEW_CONSOLE``) to give a ``console`` app its own window. POSIX
desktops have no equivalent flag, so a ``console`` app spawned by the launcher
would *inherit the launcher's terminal* — two full-screen TUIs then fight over
one TTY, which garbles the display (the launcher bleeds through behind the app)
and triggers an ``OSError: [Errno 5]`` in the input thread on quit.

This module fixes that by wrapping the app's command so it runs inside a brand
new terminal-emulator window. The wrapper is chosen so the spawned process
*stays in the foreground for the window's lifetime* (e.g. ``ptyxis
--standalone``, ``gnome-terminal --wait``, ``konsole --nofork``). That keeps the
launcher's existing ``Popen.poll()`` / ``terminate()`` tracking working, so
**Stop** and live status still function for terminal-launched apps.

Pure stdlib; never imports ``textual``.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from collections.abc import Callable, Sequence


class TerminalNotFound(OSError):
    """No supported terminal emulator could be found.

    Subclasses :class:`OSError` so existing ``except OSError`` launch-error
    handling surfaces it with a helpful message.
    """


# A builder turns ``(cwd, argv)`` into the full argv that launches ``argv`` in a
# new window of that terminal. Each is written to keep the spawned process in
# the foreground (no fork to a server / daemon) so the launcher can track it.
_Builder = Callable[[str, list[str]], list[str]]


def _join(argv: Sequence[str]) -> str:
    """POSIX-quote *argv* into a single string (for ``-e``/``-x`` terminals)."""
    return " ".join(shlex.quote(a) for a in argv)


# Ordered preference list of ``(executable, builder)``. The first entry whose
# executable is on PATH wins. GNOME-family first (this is most desktops'
# default), then KDE/XFCE, then modern terminals, then portable fallbacks.
_TERMINALS: tuple[tuple[str, _Builder], ...] = (
    # Ptyxis (a modern GNOME terminal): --standalone runs its own process
    # instead of handing off to the D-Bus service, so the window is trackable.
    ("ptyxis", lambda cwd, argv: [
        "ptyxis", "--standalone", "--new-window",
        f"--working-directory={cwd}", "--", *argv]),
    # gnome-terminal forks to gnome-terminal-server by default; --wait makes the
    # client live until the window closes.
    ("gnome-terminal", lambda cwd, argv: [
        "gnome-terminal", "--wait", f"--working-directory={cwd}", "--", *argv]),
    # GNOME Console.
    ("kgx", lambda cwd, argv: [
        "kgx", "--wait", f"--working-directory={cwd}", "-e", _join(argv)]),
    # KDE Konsole: --nofork keeps it in the foreground.
    ("konsole", lambda cwd, argv: [
        "konsole", "--nofork", f"--workdir={cwd}", "-e", *argv]),
    # XFCE: --disable-server avoids the shared factory process.
    ("xfce4-terminal", lambda cwd, argv: [
        "xfce4-terminal", "--disable-server",
        f"--working-directory={cwd}", "-x", *argv]),
    ("tilix", lambda cwd, argv: [
        "tilix", "--new-process", f"--working-directory={cwd}", "-e", _join(argv)]),
    ("kitty", lambda cwd, argv: ["kitty", f"--directory={cwd}", *argv]),
    ("alacritty", lambda cwd, argv: [
        "alacritty", "--working-directory", cwd, "-e", *argv]),
    ("foot", lambda cwd, argv: ["foot", f"--working-directory={cwd}", *argv]),
    ("wezterm", lambda cwd, argv: ["wezterm", "start", "--cwd", cwd, "--", *argv]),
    ("terminator", lambda cwd, argv: [
        "terminator", f"--working-directory={cwd}", "-x", *argv]),
    # The generic ``x-terminal-emulator`` alias and the universal fallback. No
    # cwd flag — the working directory is inherited from the Popen ``cwd`` arg.
    ("x-terminal-emulator", lambda cwd, argv: ["x-terminal-emulator", "-e", *argv]),
    ("xterm", lambda cwd, argv: ["xterm", "-e", *argv]),
)

_BUILDERS: dict[str, _Builder] = {name: build for name, build in _TERMINALS}


def is_macos() -> bool:
    return sys.platform == "darwin"


def _applescript_quote(text: str) -> str:
    """Quote *text* as an AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _macos_wrap(cwd: str, argv: list[str]) -> list[str]:
    """Open *argv* in a new macOS Terminal.app window (best effort, untracked).

    ``osascript`` returns immediately, so the launcher cannot track or Stop the
    window — acceptable on macOS, which is not the primary target.
    """
    inner = f"cd {shlex.quote(cwd)} && exec {_join(argv)}"
    script = f"tell application \"Terminal\" to do script {_applescript_quote(inner)}"
    return ["osascript", "-e", script]


def _env_terminal() -> str | None:
    """Return the basename of a usable ``$TERMINAL`` override, if any."""
    term = os.environ.get("TERMINAL", "").strip()
    if term and shutil.which(term):
        return os.path.basename(term)
    return None


def chosen_terminal() -> str | None:
    """Return the terminal that :func:`wrap` would use, or ``None`` if none.

    On macOS returns ``"Terminal.app"`` when ``osascript`` is available.
    """
    if is_macos():
        return "Terminal.app" if shutil.which("osascript") else None
    env = _env_terminal()
    if env:
        return env
    for name, _ in _TERMINALS:
        if shutil.which(name):
            return name
    return None


def wrap(cwd: str, argv: Sequence[str]) -> list[str]:
    """Return a command that runs *argv* in a new terminal window under *cwd*.

    Raises :class:`TerminalNotFound` if no supported terminal is available.
    """
    args = list(argv)
    if is_macos():
        if not shutil.which("osascript"):
            raise TerminalNotFound("osascript not found; cannot open Terminal.app.")
        return _macos_wrap(cwd, args)

    # An explicit $TERMINAL wins; use its known builder or a generic `-e` form.
    env = _env_terminal()
    if env:
        builder = _BUILDERS.get(env)
        return builder(cwd, args) if builder else [env, "-e", *args]

    for name, build in _TERMINALS:
        if shutil.which(name):
            return build(cwd, args)

    raise TerminalNotFound(
        "No supported terminal emulator found on PATH. Install one of: "
        + ", ".join(name for name, _ in _TERMINALS)
        + " (or set $TERMINAL)."
    )
