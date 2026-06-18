"""
ccdashboard — read-only Jarvis HUD dashboard for ~/.claude/ config.

Public surface
--------------
scan.build_view_model(config_dir: Path) -> dict
    Scan a Claude config directory and return a fully-populated view-model
    dict ready for the HTML frontend.  Reuses ClaudeBench's scanner; merges
    token cost data from the newest ClaudeBench snapshot when available.

build (module)
    Contains build_dashboard(config_dir, output_path) — reads the view-model,
    renders the self-contained HTML file to dist/, and returns the output path.

cc_dashboard (entry point, alongside this package)
    CLI: python CCDashboard/cc_dashboard.py [--config-dir PATH] [--no-open]
    Orchestrates scan -> build -> open-in-browser.
"""
