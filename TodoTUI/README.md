# Todo TUI

A simple terminal-based to-do manager with tabbed **Todo** / **Completed**
views. Built with [Textual](https://textual.textualize.io/).

Part of the [MicroApps](../README.md) collection — launch it from the
**[AppLauncher](../AppLauncher/)** or run it directly.

## Run via the launcher (recommended)

```bash
cd ../AppLauncher
python launcher.py        # pick "Todo TUI" → Launch
```

On Windows the app opens in a new console; on Linux/macOS it opens in a new
terminal window of its own, so it never shares (and corrupts) the launcher's
terminal.

## Run directly

Requires Python 3.10+ and `textual`.

```bash
pip install -r requirements.txt
python todo_tui.py
```

## Keyboard shortcuts

| Key     | Action                                                          |
|---------|----------------------------------------------------------------|
| `a`     | Add a new task                                                  |
| `Enter` | Mark the selected task complete (or undo it on the Completed tab) |
| `d`     | Delete the selected task                                        |
| `q`     | Quit                                                            |

Switch tabs by clicking them or with `Tab` / `Shift+Tab`.

## Data storage

Tasks are saved to `~/.local/share/todo-tui/tasks.json` and persist between
sessions. Writes are atomic (temp file + rename) and the previous save is kept
as `tasks.json.bak`, which is used as a fallback if the main file is unreadable.
