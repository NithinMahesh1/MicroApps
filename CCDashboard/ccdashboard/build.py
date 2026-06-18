"""
build.py — CCDashboard HTML assembler.

Inlines the four web assets (CSS + data + HUD JS + app JS) into index.html via
single-pass placeholder replacement, producing one self-contained HTML string.

Two entry points:
  * ``render()``   — return the assembled HTML (used by both the static generator
                     and the live server).
  * ``generate()`` — render, write to a file, optionally open in the browser.

``server_base`` distinguishes the two runtime modes: when set, the page knows a
local API is available (live conversation search / resume / quiz); when ``None``,
it is a static, config-only snapshot.
"""
from __future__ import annotations

import json
import re
import webbrowser
from pathlib import Path

# Resolved once at import time; all asset lookups are relative to this.
_WEB = Path(__file__).parent / "web"

# Exact placeholder tokens that must appear in web/index.html.
_TOKEN_CSS = "/*__CCDASH_CSS__*/"
_TOKEN_DATA = "/*__CCDASH_DATA__*/"
_TOKEN_HUD = "/*__CCDASH_HUD_JS__*/"
_TOKEN_APP = "/*__CCDASH_APP_JS__*/"


def _read(path: Path) -> str:
    """Read a UTF-8 text file, raising a descriptive error if missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"CCDashboard web asset not found: {path}\n"
            "The web assets (index.html, styles.css, app.js, hud.js) must be "
            f"present in {_WEB} before building the dashboard."
        )
    return path.read_text(encoding="utf-8")


def render(view_model: dict, *, server_base: str | None = None) -> str:
    """Assemble the self-contained dashboard HTML from the view model.

    Parameters
    ----------
    view_model:
        The dict returned by ``ccdashboard.scan.build_view_model``.
    server_base:
        When provided (e.g. ``"http://127.0.0.1:8765"``), the page runs in server
        mode and may call the local API; when ``None`` it is a static snapshot.
    """
    index_html = _read(_WEB / "index.html")
    css = _read(_WEB / "styles.css")
    hud_js = _read(_WEB / "hud.js")
    app_js = _read(_WEB / "app.js")

    # Escape "</" -> "<\/" so serialized JSON can't accidentally close the script.
    payload = json.dumps(view_model, ensure_ascii=False).replace("</", "<\\/")
    server_js = json.dumps(server_base) if server_base else "null"
    data_js = f"window.CCDASH_DATA = {payload};\nwindow.CCDASH_SERVER = {server_js};"

    # Single-pass replacement: token-like text inside one asset is never mistaken
    # for a placeholder belonging to another (a plain replace chain is order-
    # dependent). No str.format/% so braces/percent signs in CSS/JS are untouched.
    tokens = {_TOKEN_CSS: css, _TOKEN_DATA: data_js, _TOKEN_HUD: hud_js, _TOKEN_APP: app_js}
    pattern = re.compile("|".join(re.escape(t) for t in tokens))
    return pattern.sub(lambda m: tokens[m.group(0)], index_html)


def generate(view_model: dict, *, out_path: Path, open_browser: bool = True) -> Path:
    """Render a static, config-only dashboard to ``out_path`` and optionally open it."""
    html = render(view_model, server_base=None)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    if open_browser:
        webbrowser.open(out_path.resolve().as_uri())
    return out_path
