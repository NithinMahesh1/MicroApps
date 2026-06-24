# MeetingTracker — Claude Code Instructions

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python meeting_tracker.py

# Exit: Ctrl+C
```

## What This Is

A **Python TUI (Terminal User Interface)** dashboard that shows:
- Live ASCII clock (pyfiglet)
- Today's Google Calendar meetings with countdown timers
- Meeting alerts at 15/10/5 minutes before start (flashing, color-coded)
- One-key meeting join (press 1-9 to open video link)
- Unread Gmail inbox messages

**Single-file application:** `meeting_tracker.py` (~671 lines, no classes, all functions)

## Tech Stack

| Aspect | Technology |
|--------|-----------|
| Language | Python 3.13 (min 3.7+) |
| UI | `rich` (Console, Live, Table, Panel, Layout) |
| ASCII art | `pyfiglet` (font: "big") |
| APIs | Google Calendar v3, Gmail v1 (`google-api-python-client`) |
| Auth | Google OAuth 2.0 Desktop flow (`google-auth-oauthlib`) |
| Keyboard | `msvcrt` (Windows-only) |

## Key Constants

- `REFRESH_INTERVAL = 300` — re-fetches Google data every 5 minutes
- Alert thresholds: 15, 10, 5 minutes before meeting
- Max 10 unread emails displayed

## Keyboard Controls

| Key | Action |
|-----|--------|
| Up/Down | Scroll meetings or emails |
| Tab | Switch between meetings and emails panels |
| 1-9 | Open meeting video link in browser |
| Enter/Space | Acknowledge alert |
| Ctrl+R | Force refresh data |
| Ctrl+C | Exit |

## Sensitive Files — DO NOT COMMIT

- `credentials.json` — Google OAuth client credentials
- `token.json` — Auto-generated OAuth access/refresh token

**Note:** These are git-ignored — the repo-root `.gitignore` excludes `**/credentials.json` and `**/token.json` everywhere, and the real files live in the git-ignored `config/` folder (only `*.example.json` templates are committed). Verified with `git check-ignore`.

## Known Issues

- `python-dateutil` is imported but not in `requirements.txt` (optional, for Windows DST handling)
- `msvcrt` keyboard handling is Windows-only — no cross-platform support
- No test suite exists
