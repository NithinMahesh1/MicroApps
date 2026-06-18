"""
build.py — CCDashboard HTML builder.

Reads the four web assets, inlines CSS + data + JS into index.html via
literal placeholder replacement, writes the self-contained HTML file, and
optionally opens it in the browser.
"""

from __future__ import annotations

import json
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


def generate(
    view_model: dict,
    *,
    out_path: Path,
    open_browser: bool = True,
) -> Path:
    """
    Build a self-contained dashboard HTML file from the view model.

    Steps:
    1. Read the four web assets from ccdashboard/web/.
    2. Serialize view_model as JSON and wrap it in a JS variable assignment.
    3. Replace the four placeholder tokens in index.html with the inlined content.
    4. Write the result to out_path (creating parent dirs as needed).
    5. Optionally open the file in the default browser.

    Parameters
    ----------
    view_model:
        The dict returned by ``ccdashboard.scan.build_view_model``.
    out_path:
        Destination file path (e.g. ``CCDashboard/dist/dashboard.html``).
    open_browser:
        When True (default), call ``webbrowser.open`` on the generated file.

    Returns
    -------
    Path
        The resolved path of the written file.

    Raises
    ------
    FileNotFoundError
        If any of the four required web assets are missing.
    """
    index_html = _read(_WEB / "index.html")
    css = _read(_WEB / "styles.css")
    hud_js = _read(_WEB / "hud.js")
    app_js = _read(_WEB / "app.js")

    # Build the data injection script.
    # Escape "</" -> "<\/" so the serialized JSON cannot accidentally close the
    # surrounding <script> tag if any string value contains "</".
    json_payload = json.dumps(view_model, ensure_ascii=False).replace("</", "<\\/")
    data_js = f"window.CCDASH_DATA = {json_payload};"

    # Inline assets in a SINGLE PASS so token-like text inside one asset's
    # content is never mistaken for a placeholder belonging to another asset.
    # (A plain chain of str.replace() is order-dependent: a token can survive if
    # a later-inlined asset's text happens to contain it.) Still no str.format/%
    # so braces and percent signs in CSS/JS are untouched.
    import re

    tokens = {_TOKEN_CSS: css, _TOKEN_DATA: data_js, _TOKEN_HUD: hud_js, _TOKEN_APP: app_js}
    pattern = re.compile("|".join(re.escape(t) for t in tokens))
    final_html = pattern.sub(lambda m: tokens[m.group(0)], index_html)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(final_html, encoding="utf-8")

    if open_browser:
        webbrowser.open(out_path.resolve().as_uri())

    return out_path
