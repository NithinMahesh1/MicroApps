"""
ccdashboard — a futuristic Textual TUI for your ~/.claude config + conversations.

Public surface
--------------
scan.build_view_model(config_dir: Path) -> dict
    Scan a Claude config directory and return a view-model of its components
    (skills / agents / memory / rules / settings). Reuses ClaudeBench's scanner;
    merges token-cost data from the newest ClaudeBench snapshot when available.

conversations (module)
    index_conversations() / search() / launch_resume() over
    ~/.claude/projects/**/*.jsonl — full-text search and elevated ``claude --resume``.

tui.app.run(config_dir: Path) -> None
    Launch the Textual TUI (Config + Conversations tabs) over the engine above.

cc_dashboard (entry point, alongside this package)
    CLI: python CCDashboard/cc_dashboard.py [--config-dir PATH]
"""
