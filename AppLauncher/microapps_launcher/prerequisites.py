"""Prerequisite detection. Pure stdlib; probes never raise."""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
from dataclasses import dataclass

from microapps_launcher.models import App, Prerequisite


@dataclass(frozen=True)
class PrereqResult:
    ok: bool
    label: str
    detail: str
    fix_hint: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    """Return the numeric components of *text* (e.g. '3.11.2' -> (3, 11, 2))."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def version_ge(found: str, minimum: str) -> bool:
    """True if version string *found* is >= *minimum* (lenient numeric compare)."""
    return parse_version(found) >= parse_version(minimum)


def _run(cmd: list[str]) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or "") + (proc.stderr or "")


def _python(p: Prerequisite) -> PrereqResult:
    label = f"Python >= {p.min_version}"
    exe = shutil.which("python") or shutil.which("python3")
    if not exe:
        return PrereqResult(
            False, label, "not found on PATH",
            "Install Python from https://python.org (tick 'Add to PATH').",
        )
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", _run([exe, "--version"]) or "")
    if not match:
        return PrereqResult(False, label, f"could not read version from {exe}", None)
    found = match.group(1)
    ok = version_ge(found, p.min_version or "0")
    return PrereqResult(
        ok, label, f"found {found} ({exe})",
        None if ok else f"Found {found}; need >= {p.min_version}.",
    )


def _node(p: Prerequisite) -> PrereqResult:
    label = f"Node >= {p.min_version}"
    if not shutil.which("node"):
        return PrereqResult(False, label, "not found on PATH",
                            "Install Node.js from https://nodejs.org.")
    match = re.search(r"(\d+\.\d+\.\d+)", _run(["node", "--version"]) or "")
    found = match.group(1) if match else "?"
    ok = bool(match) and version_ge(found, p.min_version or "0")
    return PrereqResult(ok, label, f"found {found}",
                        None if ok else f"Need Node >= {p.min_version}.")


def _dotnet_sdk(p: Prerequisite) -> PrereqResult:
    label = f".NET SDK >= {p.min_version}"
    if not shutil.which("dotnet"):
        return PrereqResult(False, label, "dotnet not found on PATH",
                            "Install the .NET SDK from https://dot.net.")
    versions = re.findall(r"^(\d+\.\d+\.\d+)", _run(["dotnet", "--list-sdks"]) or "",
                          flags=re.MULTILINE)
    ok = any(version_ge(v, p.min_version or "0") for v in versions)
    return PrereqResult(
        ok, label, f"installed SDKs: {', '.join(versions) or 'none'}",
        None if ok else f"Install .NET SDK >= {p.min_version} from https://dot.net.",
    )


def _binary(p: Prerequisite) -> PrereqResult:
    label = f"binary: {p.name}"
    path = shutil.which(p.name or "")
    return PrereqResult(
        path is not None, label,
        f"found at {path}" if path else "not found on PATH",
        None if path else f"Install '{p.name}' and put it on PATH.",
    )


def _binary_any(p: Prerequisite) -> PrereqResult:
    names = list(p.names or ())
    present = [n for n in names if shutil.which(n)]
    return PrereqResult(
        bool(present), f"one of: {', '.join(names)}",
        f"present: {', '.join(present)}" if present else "none found on PATH",
        None if present else f"Install at least one of: {', '.join(names)}.",
    )


def _os(p: Prerequisite) -> PrereqResult:
    label = f"OS: {p.name}" + (f" >= {p.min_version}" if p.min_version else "")
    alias = {"windows": "windows", "linux": "linux", "darwin": "macos", "macos": "macos"}
    system = platform.system().lower()
    ok = alias.get(system, system) == alias.get((p.name or "").lower(), (p.name or "").lower())
    if ok and p.min_version:
        ok = version_ge(platform.version(), p.min_version)
    return PrereqResult(
        ok, label, f"running {platform.system()} {platform.version()}",
        None if ok else f"Requires {p.name} {p.min_version or ''}".strip() + ".",
    )


_DISPATCH = {
    "python": _python,
    "node": _node,
    "dotnet-sdk": _dotnet_sdk,
    "binary": _binary,
    "binary-any": _binary_any,
    "os": _os,
}


def check(p: Prerequisite) -> PrereqResult:
    """Run the check for a single prerequisite."""
    handler = _DISPATCH.get(p.type)
    if handler is None:
        return PrereqResult(False, f"unknown prerequisite '{p.type}'",
                            "unsupported type", None)
    return handler(p)


def check_all(app: App) -> list[PrereqResult]:
    """Run every prerequisite check declared by *app*."""
    return [check(p) for p in app.prerequisites]
